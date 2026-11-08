"""Change Radar: static dependency blast-radius and transparent heuristic scoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx

CRITICAL_KEYWORDS = {
    "auth",
    "login",
    "token",
    "jwt",
    "security",
    "permission",
    "payment",
    "billing",
    "db",
    "database",
    "session",
    "core",
    "config",
    "main",
}


def compute_change_impact(
    target_path: str,
    graph: nx.DiGraph,
    files: list[dict[str, Any]],
    routes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute direct/indirect dependents, related tests, routes and explainable heuristic score."""
    if target_path not in graph:
        raise ValueError(f"File '{target_path}' is not in the indexed dependency graph.")

    # Edge A -> B means A imports B. So files that depend on target_path are predecessors (ancestors).
    direct_dependents = sorted(
        [src for src in graph.predecessors(target_path) if src != target_path]
    )
    all_ancestors = sorted(
        [anc for anc in nx.ancestors(graph, target_path) if anc != target_path]
    )
    indirect_dependents = [p for p in all_ancestors if p not in direct_dependents]
    outgoing_imports = sorted(
        [dst for dst in graph.successors(target_path) if dst != target_path]
    )

    #Shortest dependency chains from each dependent to target_path
    dependency_paths: list[dict[str, Any]] = []
    for dep in all_ancestors[:25]:
        try:
            chain = nx.shortest_path(graph, source=dep, target=target_path)
            first_edge = graph.edges[chain[0], chain[1]] if len(chain) > 1 else {}
            dependency_paths.append(
                {
                    "dependent": dep,
                    "hops": len(chain) - 1,
                    "chain": chain,
                    "evidence": first_edge.get("evidence"),
                }
            )
        except nx.NetworkXNoPath:
            pass

    # Related tests: tests in ancestors OR tests matching stem name
    target_stem = Path(target_path).stem.lower()
    related_tests: list[dict[str, str]] = []
    seen_tests: set[str] = set()

    for f in files:
        if not f.get("is_test"):
            continue
        fpath = f["path"]
        if fpath in all_ancestors:
            seen_tests.add(fpath)
            related_tests.append(
                {
                    "path": fpath,
                    "reason": "Observed: imports target module directly or transitively",
                    "evidence_level": "observed",
                }
            )
        elif target_stem and target_stem not in {"__init__", "main", "utils"} and target_stem in Path(fpath).stem.lower():
            seen_tests.add(fpath)
            related_tests.append(
                {
                    "path": fpath,
                    "reason": f"Inferred: filename matches '{target_stem}' naming convention",
                    "evidence_level": "inferred",
                }
            )

    # Affected routes: routes defined in target_path or in any ancestor
    reachable_set = {target_path, *all_ancestors}
    affected_routes = [
        r for r in routes if r["path"] in reachable_set
    ]

    # Transparent heuristic formula from blueprint Section 12.3:
    # impact_score = 0.35 * normalized_dependent_count + 0.30 * critical_module_flag
    #                + 0.20 * normalized_indirect_reach + 0.15 * test_gap_flag
    total_non_test_files = max(1, sum(1 for f in files if not f.get("is_test")))
    normalized_dependent_count = min(1.0, len(direct_dependents) / max(1, min(10, total_non_test_files)))
    normalized_indirect_reach = min(1.0, len(indirect_dependents) / max(1, min(20, total_non_test_files)))

    lower_target = target_path.lower()
    is_critical = any(kw in lower_target for kw in CRITICAL_KEYWORDS) or bool(affected_routes)
    critical_module_flag = 1.0 if is_critical else 0.0
    test_gap_flag = 1.0 if len(related_tests) == 0 else (0.4 if all(t["evidence_level"] == "inferred" for t in related_tests) else 0.0)

    raw_score = (
        0.35 * normalized_dependent_count
        + 0.30 * critical_module_flag
        + 0.20 * normalized_indirect_reach
        + 0.15 * test_gap_flag
    )
    impact_score = round(raw_score, 2)
    priority_label = "High" if impact_score >= 0.65 else ("Medium" if impact_score >= 0.35 else "Low")

    return {
        "target_path": target_path,
        "impact_score": impact_score,
        "priority_label": priority_label,
        "formula": "0.35 * direct_dependents + 0.30 * critical_or_route_flag + 0.20 * indirect_reach + 0.15 * test_gap",
        "factors": {
            "normalized_dependent_count": round(normalized_dependent_count, 2),
            "critical_module_flag": round(critical_module_flag, 2),
            "normalized_indirect_reach": round(normalized_indirect_reach, 2),
            "test_gap_flag": round(test_gap_flag, 2),
        },
        "direct_dependents": direct_dependents,
        "indirect_dependents": indirect_dependents,
        "outgoing_imports": outgoing_imports,
        "dependency_paths": dependency_paths,
        "related_tests": related_tests,
        "affected_routes": affected_routes[:15],
        "limitations": [
            "Static import graph only: dynamic imports (importlib), reflection, dependency injection containers and runtime environment wiring are not visible.",
            "Heuristic score is a review prioritization aid, not a calibrated probability of failure.",
        ],
    }
