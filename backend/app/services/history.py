"""Git history extraction, contributor mapping and bus-factor concentration analysis."""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import networkx as nx

COMMIT_SEP = "@@REPOWISE_COMMIT@@"


def analyze_git_history(
    repo_root: Path,
    current_files: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    graph: nx.DiGraph,
) -> dict[str, Any]:
    """Parse git log without running hooks and compute bus-factor knowledge concentration."""
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return {
            "available": False,
            "commits": [],
            "contributors": [],
            "concentrated_files": [],
            "folder_risks": [],
            "handover_capsules": [],
            "note": "Git history unavailable (uploaded ZIP or missing .git metadata).",
        }

    cmd = [
        "git",
        "-C",
        str(repo_root),
        "-c",
        "core.hooksPath=/dev/null",
        "log",
        "-n",
        "500",
        f"--pretty=format:{COMMIT_SEP}%H|%an|%ae|%aI|%s",
        "--name-only",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if res.returncode != 0 or not res.stdout.strip():
        return {
            "available": False,
            "commits": [],
            "contributors": [],
            "concentrated_files": [],
            "folder_risks": [],
            "handover_capsules": [],
            "note": "Git log returned no commits.",
        }

    current_path_set = {f["path"] for f in current_files}
    commits: list[dict[str, Any]] = []
    file_author_counts: dict[str, Counter[str]] = defaultdict(Counter)
    file_commits: dict[str, list[dict[str, str]]] = defaultdict(list)
    overall_authors: Counter[str] = Counter()

    raw_blocks = [b.strip() for b in res.stdout.split(COMMIT_SEP) if b.strip()]
    for block in raw_blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        header = lines[0]
        parts = header.split("|", 4)
        if len(parts) < 5:
            continue
        sha, author, email, committed_at, subject = parts
        changed = [p.replace("\\", "/") for p in lines[1:] if p]
        commits.append(
            {
                "sha": sha[:12],
                "full_sha": sha,
                "author": author,
                "email": email,
                "committed_at": committed_at,
                "message": subject,
                "files": changed[:25],
            }
        )
        overall_authors[author] += 1
        for fpath in changed:
            if fpath in current_path_set:
                file_author_counts[fpath][author] += 1
                if len(file_commits[fpath]) < 8:
                    file_commits[fpath].append(
                        {"sha": sha[:8], "author": author, "date": committed_at[:10], "message": subject}
                    )

    # Identify concentrated files: single owner >= 70% of commits.
    # Standard threshold: >= 5 commits; if repo is small (<15 total commits), allow >= 2 commits and label it.
    min_commits_threshold = 5 if len(commits) >= 15 else 2
    concentrated_files: list[dict[str, Any]] = []
    folder_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for f in current_files:
        fpath = f["path"]
        counts = file_author_counts.get(fpath)
        if not counts:
            continue
        total_c = sum(counts.values())
        top_author, top_count = counts.most_common(1)[0]
        share = top_count / total_c if total_c else 0.0
        dependents = int(graph.in_degree(fpath)) if fpath in graph else 0

        item = {
            "path": fpath,
            "primary_owner": top_author,
            "owner_commits": top_count,
            "total_commits": total_c,
            "ownership_share": round(share, 2),
            "dependent_files": dependents,
            "is_concentrated": total_c >= min_commits_threshold and share >= 0.70,
            "recent_commits": file_commits.get(fpath, [])[:4],
        }
        folder = Path(fpath).parent.as_posix() if "/" in fpath else "(root)"
        folder_buckets[folder].append(item)
        if item["is_concentrated"]:
            concentrated_files.append(item)

    concentrated_files.sort(
        key=lambda x: (-(x["ownership_share"] * (1 + x["dependent_files"])), -x["total_commits"], x["path"])
    )

    # Roll up to folders and rank by risk = concentration * (1 + total dependents)
    folder_risks: list[dict[str, Any]] = []
    for folder, items in folder_buckets.items():
        folder_author_totals: Counter[str] = Counter()
        folder_dependents = 0
        flagged_in_folder = 0
        for it in items:
            for author, cnt in file_author_counts[it["path"]].items():
                folder_author_totals[author] += cnt
            folder_dependents += it["dependent_files"]
            if it["is_concentrated"]:
                flagged_in_folder += 1

        total_folder_touches = sum(folder_author_totals.values())
        if total_folder_touches == 0:
            continue
        lead_author, lead_touches = folder_author_totals.most_common(1)[0]
        concentration = round(lead_touches / total_folder_touches, 2)
        risk_score = round(concentration * (1 + folder_dependents + flagged_in_folder), 2)

        folder_risks.append(
            {
                "folder": folder,
                "primary_owner": lead_author,
                "concentration": concentration,
                "total_commits": total_folder_touches,
                "flagged_files_count": flagged_in_folder,
                "dependent_files_count": folder_dependents,
                "risk_score": risk_score,
                "files": sorted(items, key=lambda x: (-x["dependent_files"], -x["total_commits"]))[:6],
            }
        )

    folder_risks.sort(key=lambda r: (-r["risk_score"], -r["total_commits"], r["folder"]))

    # Build deterministic, cited handover capsules for top 3 risky folders/files
    symbols_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sym in symbols:
        symbols_by_path[sym["path"]].append(sym)

    handover_capsules: list[dict[str, Any]] = []
    for folder_item in folder_risks[:3]:
        target_files = folder_item["files"][:3]
        cited_symbols: list[dict[str, Any]] = []
        recent_changes: list[dict[str, str]] = []
        seen_shas: set[str] = set()

        for tf in target_files:
            for sym in symbols_by_path.get(tf["path"], [])[:4]:
                cited_symbols.append(
                    {
                        "name": sym["name"],
                        "kind": sym["kind"],
                        "signature": sym["signature"],
                        "citation": f"[{sym['path']}:{sym['start_line']}-{sym['end_line']}]",
                        "path": sym["path"],
                        "start_line": sym["start_line"],
                        "end_line": sym["end_line"],
                        "docstring": sym.get("docstring", ""),
                    }
                )
            for cm in tf["recent_commits"]:
                if cm["sha"] not in seen_shas:
                    seen_shas.add(cm["sha"])
                    recent_changes.append(cm)

        owner = folder_item["primary_owner"]
        pct = int(folder_item["concentration"] * 100)
        handover_capsules.append(
            {
                "folder": folder_item["folder"],
                "primary_owner": owner,
                "concentration_pct": pct,
                "risk_score": folder_item["risk_score"],
                "evidence_level": "observed",
                "summary": (
                    f"Observed: {owner} authored {pct}% of recorded file touches in '{folder_item['folder']}' "
                    f"across {folder_item['total_commits']} commit touches, with "
                    f"{folder_item['dependent_files_count']} incoming module import links."
                ),
                "key_symbols": cited_symbols[:6],
                "commit_evidence": recent_changes[:5],
                "open_questions_for_owner": [
                    f"Unknown from static source: Which runtime invariants or external configs in '{folder_item['folder']}' are not covered by unit tests?",
                    f"Unknown from commit history: Why were the latest changes ({recent_changes[0]['sha'] if recent_changes else 'n/a'}) structured this way, and what edge cases caused regressions previously?",
                ],
            }
        )

    contributors = [
        {"author": name, "commits": count, "share": round(count / max(1, len(commits)), 2)}
        for name, count in overall_authors.most_common(10)
    ]

    return {
        "available": True,
        "commits": commits[:60],
        "total_commits_scanned": len(commits),
        "min_commits_threshold": min_commits_threshold,
        "contributors": contributors,
        "concentrated_files": concentrated_files[:20],
        "folder_risks": folder_risks[:10],
        "handover_capsules": handover_capsules,
        "note": (
            f"Based on up to {len(commits)} commits in shallow history. "
            "Commit messages show observed change descriptions, not full author intent."
        ),
    }
