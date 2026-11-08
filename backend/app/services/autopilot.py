"""Onboarding Autopilot: 3-day cited onboarding plan, starter issue matching and verification missions."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import requests

from app.services.retrieval import CodeRetriever


def _fetch_github_starter_issues(source_url: str) -> list[dict[str, Any]]:
    """Fetch open issues from GitHub API (prefers 'good first issue' / 'help wanted' labels)."""
    parsed = urlparse(source_url or "")
    if (parsed.hostname or "").lower() != "github.com":
        return []
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return []
    owner, repo = parts[0], parts[1].removesuffix(".git")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "RepoWise-Analyzer/2.0"}

    try:
        # Try good first issue first, then general open issues
        for params in (
            {"state": "open", "labels": "good first issue", "per_page": 5},
            {"state": "open", "per_page": 5},
        ):
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/issues",
                params=params,
                headers=headers,
                timeout=4,
            )
            if resp.status_code == 200:
                items = [
                    it for it in resp.json() if isinstance(it, dict) and "pull_request" not in it
                ]
                if items:
                    return [
                        {
                            "number": it.get("number"),
                            "title": it.get("title", ""),
                            "url": it.get("html_url", ""),
                            "labels": [lb.get("name", "") for lb in it.get("labels", []) if isinstance(lb, dict)],
                            "body": (it.get("body") or "")[:400],
                        }
                        for it in items[:3]
                    ]
    except Exception:
        pass
    return []


def generate_onboarding_autopilot(
    source_url: str,
    scan_data: dict[str, Any],
    graph_data: dict[str, Any],
    history_data: dict[str, Any],
    retriever: CodeRetriever,
) -> dict[str, Any]:
    """Generate a 3-day onboarding plan and interactive missions grounded in real symbols and files."""
    files = scan_data["files"]
    symbols = scan_data["symbols"]
    routes = scan_data["routes"]
    entrypoints = scan_data["entrypoints"]
    hub_files = graph_data["hub_files"]

    # Map folder -> primary contributor from git history
    folder_experts: dict[str, str] = {}
    for fr in history_data.get("folder_risks", []):
        folder_experts[fr["folder"]] = fr["primary_owner"]
    default_expert = (
        history_data["contributors"][0]["author"]
        if history_data.get("contributors")
        else "Repository Maintainer (git history unavailable)"
    )

    def _expert_for_path(path: str) -> str:
        folder = "/".join(path.split("/")[:-1]) if "/" in path else "(root)"
        return folder_experts.get(folder, default_expert)

    def _cite_for_file(path: str) -> dict[str, Any]:
        for s in symbols:
            if s["path"] == path:
                return {
                    "path": path,
                    "start_line": s["start_line"],
                    "end_line": s["end_line"],
                    "symbol": s["name"],
                    "citation": f"[{path}:{s['start_line']}-{s['end_line']}]",
                }
        f_obj = next((f for f in files if f["path"] == path), None)
        end_ln = min(40, f_obj["line_count"]) if f_obj else 1
        return {
            "path": path,
            "start_line": 1,
            "end_line": max(1, end_ln),
            "symbol": path.split("/")[-1],
            "citation": f"[{path}:1-{max(1, end_ln)}]",
        }

    # Day 1: Entry points & architecture bootstrap
    day1_paths = (entrypoints + hub_files + [f["path"] for f in files if f["language"] == "python"])[:3]
    day1_cites = [_cite_for_file(p) for p in dict.fromkeys(day1_paths)]

    # Day 2: Core data/request flow & most-depended-on hub modules
    route_paths = [r["path"] for r in routes[:2]]
    day2_paths = (hub_files[:2] + route_paths + [f["path"] for f in files if not f["is_test"]])[:3]
    day2_cites = [_cite_for_file(p) for p in dict.fromkeys(day2_paths)]

    # Day 3: Starter issue or highest-leverage untested/test module
    issues = _fetch_github_starter_issues(source_url)
    test_files = [f["path"] for f in files if f.get("is_test")]
    starter_issue: dict[str, Any]
    if issues:
        chosen = issues[0]
        matched_chunks = retriever.retrieve(f"{chosen['title']} {chosen['body']}", top_k=3)
        matched_cites = [
            {
                "path": c["path"],
                "start_line": c["start_line"],
                "end_line": c["end_line"],
                "symbol": c["symbol"],
                "citation": f"[{c['path']}:{c['start_line']}-{c['end_line']}]",
            }
            for c in matched_chunks
        ] or day2_cites[:2]
        starter_issue = {
            "source": "github_open_issue",
            "number": chosen["number"],
            "title": chosen["title"],
            "url": chosen["url"],
            "labels": chosen["labels"],
            "matched_citations": matched_cites,
        }
        day3_cites = matched_cites
    else:
        target_cites = [_cite_for_file(p) for p in (test_files[:2] or day1_paths[:2])]
        starter_issue = {
            "source": "repository_evidence_task",
            "number": None,
            "title": (
                f"Add or expand test assertions around `{day2_cites[0]['symbol']}`"
                if day2_cites
                else "Document and verify primary entry point"
            ),
            "url": "",
            "labels": ["onboarding-task", "evidence-derived"],
            "matched_citations": target_cites,
        }
        day3_cites = target_cites

    days = [
        {
            "day": 1,
            "title": "Day 1 — Understand Entry Points & Module Layout",
            "goal": "Locate where execution starts, how configuration is loaded, and how top-level packages are organized.",
            "contact_expert": _expert_for_path(day1_cites[0]["path"]) if day1_cites else default_expert,
            "reading_list": day1_cites,
            "verification_step": (
                f"Inspect {day1_cites[0]['citation']} and trace its direct outgoing imports in the Architecture Map."
                if day1_cites
                else "Inspect the repository root files."
            ),
        },
        {
            "day": 2,
            "title": "Day 2 — Trace Core Flow & Shared Hub Modules",
            "goal": "Follow a request or core function call from the interface layer into the most depended-on internal module.",
            "contact_expert": _expert_for_path(day2_cites[0]["path"]) if day2_cites else default_expert,
            "reading_list": day2_cites,
            "verification_step": (
                f"Run Change Radar on `{day2_cites[0]['path']}` to see which modules and tests depend on `{day2_cites[0]['symbol']}`."
                if day2_cites
                else "Review module dependencies in the graph."
            ),
        },
        {
            "day": 3,
            "title": "Day 3 — First Contribution & Test Verification",
            "goal": f"Tackle starter target: {starter_issue['title']}",
            "contact_expert": _expert_for_path(day3_cites[0]["path"]) if day3_cites else default_expert,
            "reading_list": day3_cites,
            "verification_step": (
                f"Verify existing tests ({', '.join(test_files[:2]) or 'no test files detected — add unit test'}) before opening your first PR."
            ),
        },
    ]

    # Build 3 interactive onboarding missions with deterministic rubric keywords
    missions: list[dict[str, Any]] = []
    if day1_cites:
        c0 = day1_cites[0]
        missions.append(
            {
                "id": "mission-1",
                "order": 1,
                "title": f"Locate Entry Point & Bootstrap Symbol (`{c0['symbol']}`)",
                "objective": f"Open `{c0['path']}` and explain what `{c0['symbol']}` initializes or exposes.",
                "why_it_matters": "Every debugging session starts by knowing how the application boots and wires its modules.",
                "files_to_inspect": [c0],
                "hint": f"Look at lines {c0['start_line']}–{c0['end_line']} in `{c0['path']}`.",
                "expected_keywords": [
                    c0["symbol"].lower(),
                    c0["path"].split("/")[-1].removesuffix(".py").lower(),
                ],
            }
        )
    if day2_cites:
        c1 = day2_cites[0]
        missions.append(
            {
                "id": "mission-2",
                "order": 2,
                "title": f"Trace Core Dependency Hub (`{c1['path']}`)",
                "objective": f"Inspect `{c1['path']}` ({c1['citation']}) and name at least one module that imports it or one symbol it defines.",
                "why_it_matters": "High-in-degree modules carry the largest blast radius when modified.",
                "files_to_inspect": [c1],
                "hint": "Use the Architecture Map or Change Radar panel to see incoming edges.",
                "expected_keywords": [
                    c1["symbol"].lower(),
                    c1["path"].split("/")[-1].removesuffix(".py").lower(),
                ],
            }
        )
    if day3_cites:
        c2 = day3_cites[0]
        missions.append(
            {
                "id": "mission-3",
                "order": 3,
                "title": "Prepare Your First Safe Change",
                "objective": f"Review `{c2['path']}` ({c2['citation']}) and describe what test or dependent file must be checked if you edit `{c2['symbol']}`.",
                "why_it_matters": "Checking downstream dependents and tests before editing prevents regressions in unfamiliar code.",
                "files_to_inspect": [c2],
                "hint": f"Inspect `{c2['path']}` in Change Radar to see its direct dependents and related tests.",
                "expected_keywords": [
                    c2["symbol"].lower(),
                    "test",
                    c2["path"].split("/")[-1].removesuffix(".py").lower(),
                ],
            }
        )

    return {
        "days": days,
        "starter_issue": starter_issue,
        "missions": missions,
        "disclaimer": "Mission feedback checks whether your explanation references the observed source evidence; it is a learning aid, not a formal skill certification.",
    }


def evaluate_mission_submission(
    mission: dict[str, Any],
    user_answer: str,
) -> dict[str, Any]:
    """Evaluate a newcomer's mission explanation against observed repository evidence."""
    ans = (user_answer or "").strip()
    words = re.findall(r"[A-Za-z0-9_./\-]+", ans.lower())
    if len(words) < 6:
        return {
            "mission_id": mission["id"],
            "passed": False,
            "feedback": "Please write a slightly more detailed explanation (at least a full sentence referencing the file or symbol you inspected).",
            "matched_evidence": [],
        }

    expected = [kw.lower() for kw in mission.get("expected_keywords", []) if kw]
    matched = [kw for kw in expected if kw in ans.lower()]
    passed = len(matched) >= 1
    cites = [f["citation"] for f in mission.get("files_to_inspect", [])]
    if passed:
        feedback = (
            f"Verified against observed evidence ({', '.join(cites)}). "
            f"Your explanation references `{', '.join(matched)}`."
        )
    else:
        feedback = (
            f"Your answer did not mention the target symbol or module ({', '.join(expected)}). "
            f"Inspect {', '.join(cites)} and describe what that code does."
        )
    return {
        "mission_id": mission["id"],
        "passed": passed,
        "feedback": feedback,
        "matched_evidence": matched,
    }
