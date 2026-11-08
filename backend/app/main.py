"""FastAPI entrypoint and v1 endpoints for RepoWise."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.services.ingest import IngestError, validate_git_url
from app.services.store import WorkspaceStore

load_dotenv()

app = FastAPI(
    title="RepoWise API",
    version="2.0.0",
    description="Evidence-backed codebase onboarding, bus-factor continuity and static change-impact radar.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = WorkspaceStore()


class CreateRepoRequest(BaseModel):
    url: str = Field(..., description="Public HTTPS Git repository URL (GitHub/GitLab/Bitbucket)")
    run_async: bool = Field(default=False, description="Run scan in background task")


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=600)


class MissionCheckRequest(BaseModel):
    mission_id: str
    answer: str = Field(..., min_length=2, max_length=2000)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "analyses_count": len(store.analyses)}


@app.get("/api/v1/repositories")
def list_repositories() -> list[dict[str, Any]]:
    return store.list_summaries()


@app.post("/api/v1/repositories")
def create_repository(req: CreateRepoRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        clean_url = validate_git_url(req.url)
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo_name = clean_url.rstrip("/").split("/")[-1].removesuffix(".git")
    record = store.create_analysis_record(
        name=repo_name,
        source_type="git_url",
        source_url=clean_url,
    )
    if req.run_async:
        background_tasks.add_task(store.run_pipeline, record["id"])
        return record

    try:
        return store.run_pipeline(record["id"])
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/repositories/self-analyze")
def analyze_repowise_itself() -> dict[str, Any]:
    """Instant zero-network demo: analyze RepoWise's own repository with real git history."""
    repo_root = Path(__file__).resolve().parents[2]
    # Check if already analyzed and completed
    for existing in store.analyses.values():
        if existing.get("source_type") == "self" and existing.get("status") == "completed":
            return existing

    record = store.create_analysis_record(
        name="RepoWise",
        source_type="self",
        source_url="https://github.com/Sarty-085/RepoWise.git",
    )
    return store.run_pipeline(record["id"], local_source_dir=repo_root)


@app.get("/api/v1/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict[str, Any]:
    record = store.analyses.get(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    return {
        "id": record["id"],
        "name": record["name"],
        "source_type": record["source_type"],
        "source_url": record["source_url"],
        "commit_sha": record["commit_sha"],
        "status": record["status"],
        "progress": record["progress"],
        "error": record.get("error"),
        "created_at": record["created_at"],
        "completed_at": record.get("completed_at"),
        "summary": record.get("summary", {}),
        "routes": record.get("routes", []),
        "excluded": record.get("excluded", [])[:40],
    }


@app.get("/api/v1/analyses/{analysis_id}/files")
def get_files(analysis_id: str) -> dict[str, Any]:
    record = store.analyses.get(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    return {
        "files": record.get("files", []),
        "excluded": record.get("excluded", []),
    }


@app.get("/api/v1/analyses/{analysis_id}/file-content")
def get_file_content(
    analysis_id: str,
    path: str = Query(..., description="Relative file path inside the repository"),
) -> dict[str, Any]:
    record = store.analyses.get(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    clean_path = path.strip().lstrip("/")
    lines = record.get("file_contents", {}).get(clean_path)
    if lines is None:
        raise HTTPException(status_code=404, detail=f"File '{clean_path}' not found in indexed snapshot.")
    file_syms = [s for s in record.get("symbols", []) if s["path"] == clean_path]
    return {
        "path": clean_path,
        "line_count": len(lines),
        "lines": lines,
        "symbols": file_syms,
    }


@app.get("/api/v1/analyses/{analysis_id}/symbols")
def get_symbols(
    analysis_id: str,
    q: str = Query(default="", description="Optional symbol filter"),
) -> list[dict[str, Any]]:
    record = store.analyses.get(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    syms = record.get("symbols", [])
    if q.strip():
        ql = q.strip().lower()
        syms = [s for s in syms if ql in s["name"].lower() or ql in s["path"].lower()]
    return syms


@app.get("/api/v1/analyses/{analysis_id}/graph")
def get_graph(analysis_id: str) -> dict[str, Any]:
    record = store.analyses.get(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    return record.get("graph", {"nodes": [], "edges": [], "hub_files": []})


@app.get("/api/v1/analyses/{analysis_id}/history")
def get_history(analysis_id: str) -> dict[str, Any]:
    record = store.analyses.get(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    return record.get("history", {})


@app.get("/api/v1/analyses/{analysis_id}/impact")
def get_impact(
    analysis_id: str,
    path: str = Query(..., description="Target file path to evaluate"),
) -> dict[str, Any]:
    if analysis_id not in store.analyses:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    try:
        return store.impact(analysis_id, path.strip().lstrip("/"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/analyses/{analysis_id}/autopilot")
def get_autopilot(analysis_id: str) -> dict[str, Any]:
    record = store.analyses.get(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    return record.get("autopilot", {})


@app.post("/api/v1/analyses/{analysis_id}/missions/check")
def check_mission(analysis_id: str, req: MissionCheckRequest) -> dict[str, Any]:
    if analysis_id not in store.analyses:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    try:
        return store.check_mission(analysis_id, req.mission_id, req.answer)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/analyses/{analysis_id}/questions")
def ask_question(analysis_id: str, req: QuestionRequest) -> dict[str, Any]:
    if analysis_id not in store.analyses:
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    return store.ask(analysis_id, req.question)


@app.delete("/api/v1/repositories/{analysis_id}")
def delete_repository(analysis_id: str) -> dict[str, Any]:
    if not store.delete(analysis_id):
        raise HTTPException(status_code=404, detail="Analysis workspace not found.")
    return {"deleted": True, "id": analysis_id}


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.get("/", include_in_schema=False)
def serve_spa_index() -> Any:
    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return {"status": "ok", "message": "RepoWise API running. Run npm run build in frontend/ to serve UI."}

