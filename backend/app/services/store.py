"""Analysis orchestrator and persistent JSON workspace store."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.autopilot import evaluate_mission_submission, generate_onboarding_autopilot
from app.services.graph import build_dependency_graph
from app.services.history import analyze_git_history
from app.services.impact import compute_change_impact
from app.services.ingest import IngestError, clone_repository, extract_zip_safely
from app.services.llm import answer_grounded_question
from app.services.retrieval import CodeRetriever
from app.services.scanner import scan_repository

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceStore:
    """In-memory and JSON-persisted store for repository analyses."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir
        self.repos_dir = data_dir / "repos"
        self.snapshots_dir = data_dir / "snapshots"
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.analyses: dict[str, dict[str, Any]] = {}
        self.graphs: dict[str, Any] = {}
        self.retrievers: dict[str, CodeRetriever] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        for snap_file in sorted(self.snapshots_dir.glob("*.json")):
            try:
                data = json.loads(snap_file.read_text(encoding="utf-8"))
                aid = data.get("id")
                if not aid:
                    continue
                if data.get("status") != "completed":
                    # Clean up interrupted scans from previous killed processes
                    snap_file.unlink(missing_ok=True)
                    shutil.rmtree(self.repos_dir / aid, ignore_errors=True)
                    continue
                self.analyses[aid] = data
                g, _ = build_dependency_graph(
                    data.get("files", []), data.get("file_imports", {})
                )
                self.graphs[aid] = g
                self.retrievers[aid] = CodeRetriever(data.get("chunks", []))
            except Exception:
                pass

    def save_snapshot(self, analysis_id: str) -> None:
        record = self.analyses.get(analysis_id)
        if not record:
            return
        snap_path = self.snapshots_dir / f"{analysis_id}.json"
        snap_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    def create_analysis_record(
        self,
        name: str,
        source_type: str,
        source_url: str,
    ) -> dict[str, Any]:
        aid = uuid.uuid4().hex[:10]
        record: dict[str, Any] = {
            "id": aid,
            "name": name,
            "source_type": source_type,
            "source_url": source_url,
            "commit_sha": "pending",
            "status": "queued",
            "progress": 5,
            "error": None,
            "created_at": _utc_now(),
            "completed_at": None,
            "summary": {},
            "files": [],
            "excluded": [],
            "symbols": [],
            "routes": [],
            "chunks": [],
            "file_imports": {},
            "file_contents": {},
            "graph": {"nodes": [], "edges": [], "hub_files": []},
            "history": {},
            "autopilot": {},
            "chat_history": [],
        }
        self.analyses[aid] = record
        self.save_snapshot(aid)
        return record

    def run_pipeline(
        self,
        analysis_id: str,
        local_source_dir: Path | None = None,
        zip_path: Path | None = None,
    ) -> dict[str, Any]:
        record = self.analyses[analysis_id]
        repo_dest = self.repos_dir / analysis_id
        try:
            record["status"] = "scanning"
            record["progress"] = 20
            self.save_snapshot(analysis_id)

            if local_source_dir is not None:
                if repo_dest.exists():
                    shutil.rmtree(repo_dest, ignore_errors=True)
                shutil.copytree(
                    local_source_dir,
                    repo_dest,
                    ignore=shutil.ignore_patterns(
                        ".venv",
                        "venv",
                        "node_modules",
                        "__pycache__",
                        ".pytest_cache",
                        "data",
                        "sample_repos",
                        "dist",
                    ),
                )
                sha_res = subprocess.run(
                    ["git", "-C", str(repo_dest), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "local-head"
            elif zip_path is not None:
                commit_sha, name = extract_zip_safely(zip_path, repo_dest)
                record["name"] = name
            else:
                commit_sha, name = clone_repository(record["source_url"], repo_dest)
                record["name"] = name

            record["commit_sha"] = commit_sha
            record["progress"] = 45

            scan_data = scan_repository(repo_dest)
            record["status"] = "indexing"
            record["progress"] = 70

            g, graph_data = build_dependency_graph(
                scan_data["files"], scan_data["file_imports"]
            )
            history_data = analyze_git_history(
                repo_dest, scan_data["files"], scan_data["symbols"], g
            )
            retriever = CodeRetriever(scan_data["chunks"])
            autopilot_data = generate_onboarding_autopilot(
                record["source_url"], scan_data, graph_data, history_data, retriever
            )

            # Remove temporary clone on disk now that safe lines & metadata are captured
            shutil.rmtree(repo_dest, ignore_errors=True)

            record.update(
                {
                    "status": "completed",
                    "progress": 100,
                    "completed_at": _utc_now(),
                    "files": scan_data["files"],
                    "excluded": scan_data["excluded"],
                    "symbols": scan_data["symbols"],
                    "routes": scan_data["routes"],
                    "chunks": scan_data["chunks"],
                    "file_imports": scan_data["file_imports"],
                    "file_contents": scan_data["file_contents"],
                    "graph": graph_data,
                    "history": history_data,
                    "autopilot": autopilot_data,
                    "summary": {
                        "total_files": len(scan_data["files"]),
                        "total_lines": sum(f["line_count"] for f in scan_data["files"]),
                        "total_symbols": len(scan_data["symbols"]),
                        "total_routes": len(scan_data["routes"]),
                        "total_edges": len(graph_data["edges"]),
                        "language_counts": scan_data["language_counts"],
                        "frameworks": scan_data["frameworks"],
                        "entrypoints": scan_data["entrypoints"],
                        "hub_files": graph_data["hub_files"],
                        "top_folders": scan_data["top_folders"],
                        "redacted_secrets_total": scan_data["redacted_secrets_total"],
                        "parse_errors": scan_data["parse_errors"],
                        "bus_factor_Alerts": len(history_data.get("concentrated_files", [])),
                    },
                }
            )
            self.graphs[analysis_id] = g
            self.retrievers[analysis_id] = retriever
            self.save_snapshot(analysis_id)
            return record
        except Exception as exc:
            shutil.rmtree(repo_dest, ignore_errors=True)
            record["status"] = "failed"
            record["progress"] = 100
            record["error"] = str(exc)
            self.save_snapshot(analysis_id)
            if isinstance(exc, IngestError):
                raise
            return record

    def list_summaries(self) -> list[dict[str, Any]]:
        items = []
        for r in self.analyses.values():
            items.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "source_type": r["source_type"],
                    "source_url": r["source_url"],
                    "commit_sha": r["commit_sha"],
                    "status": r["status"],
                    "progress": r["progress"],
                    "error": r.get("error"),
                    "created_at": r["created_at"],
                    "completed_at": r.get("completed_at"),
                    "summary": r.get("summary", {}),
                }
            )
        items.sort(key=lambda x: x["created_at"], reverse=True)
        return items

    def delete(self, analysis_id: str) -> bool:
        if analysis_id not in self.analyses:
            return False
        self.analyses.pop(analysis_id, None)
        self.graphs.pop(analysis_id, None)
        self.retrievers.pop(analysis_id, None)
        snap = self.snapshots_dir / f"{analysis_id}.json"
        if snap.exists():
            snap.unlink()
        shutil.rmtree(self.repos_dir / analysis_id, ignore_errors=True)
        return True

    def ask(self, analysis_id: str, question: str) -> dict[str, Any]:
        record = self.analyses[analysis_id]
        retriever = self.retrievers.get(analysis_id) or CodeRetriever(record.get("chunks", []))
        graph = self.graphs.get(analysis_id)
        chunks = retriever.retrieve(question, graph=graph, top_k=6)
        ans = answer_grounded_question(
            question=question,
            retrieved_chunks=chunks,
            graph_edges=record.get("graph", {}).get("edges", []),
            git_commits=record.get("history", {}).get("commits", []),
            file_contents=record.get("file_contents", {}),
            symbols=record.get("symbols", []),
        )
        record.setdefault("chat_history", []).append(ans)
        self.save_snapshot(analysis_id)
        return ans

    def impact(self, analysis_id: str, file_path: str) -> dict[str, Any]:
        record = self.analyses[analysis_id]
        graph = self.graphs.get(analysis_id)
        if graph is None:
            graph, _ = build_dependency_graph(record["files"], record["file_imports"])
            self.graphs[analysis_id] = graph
        return compute_change_impact(
            target_path=file_path,
            graph=graph,
            files=record["files"],
            routes=record["routes"],
        )

    def check_mission(self, analysis_id: str, mission_id: str, answer: str) -> dict[str, Any]:
        record = self.analyses[analysis_id]
        missions = record.get("autopilot", {}).get("missions", [])
        mission = next((m for m in missions if m["id"] == mission_id), None)
        if not mission:
            raise ValueError(f"Mission '{mission_id}' not found.")
        return evaluate_mission_submission(mission, answer)
