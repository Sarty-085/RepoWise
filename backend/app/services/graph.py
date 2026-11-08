"""File-level dependency graph construction and import resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx


def _build_module_index(py_paths: list[str]) -> dict[str, str]:
    """Map dotted Python module names (with and without top-level src/backend prefix) to file paths."""
    index: dict[str, str] = {}
    for rel_path in py_paths:
        p = Path(rel_path)
        parts = list(p.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        full_mod = ".".join(parts)
        index[full_mod] = rel_path
        # Also index stripped of common source roots like src/, app/, backend/, lib/
        if len(parts) > 1 and parts[0] in {"src", "backend", "lib"}:
            index[".".join(parts[1:])] = rel_path
        if len(parts) > 2 and parts[0] == "backend" and parts[1] == "app":
            index[".".join(parts[1:])] = rel_path
    return index


def resolve_import_target(
    importer_path: str,
    imp: dict[str, Any],
    module_index: dict[str, str],
    py_set: set[str],
) -> list[str]:
    """Resolve an AST import record to one or more repository file paths."""
    targets: list[str] = []
    level = int(imp.get("level", 0) or 0)
    mod = imp.get("module") or ""
    names: list[str] = imp.get("names") or []

    importer_dir = Path(importer_path).parent
    if level > 0:
        base_dir = importer_dir
        for _ in range(level - 1):
            base_dir = base_dir.parent
        rel_parts = [p for p in base_dir.parts if p not in ("", ".")]
        if mod:
            rel_parts.extend(mod.split("."))
        candidate_prefix = "/".join(rel_parts)
        for cand in (f"{candidate_prefix}.py", f"{candidate_prefix}/__init__.py"):
            if cand in py_set:
                targets.append(cand)
        for name in names:
            sub_prefix = f"{candidate_prefix}/{name}".lstrip("/")
            for cand in (f"{sub_prefix}.py", f"{sub_prefix}/__init__.py"):
                if cand in py_set and cand not in targets:
                    targets.append(cand)
        return targets

    if mod in module_index:
        targets.append(module_index[mod])

    for name in names:
        qualified = f"{mod}.{name}" if mod else name
        if qualified in module_index and module_index[qualified] not in targets:
            targets.append(module_index[qualified])

    # Check sibling import in same directory
    if not targets and mod and "." not in mod:
        sibling = (importer_dir / f"{mod}.py").as_posix()
        if sibling in py_set:
            targets.append(sibling)

    return [t for t in targets if t != importer_path]


def build_dependency_graph(
    files: list[dict[str, Any]],
    file_imports: dict[str, list[dict[str, Any]]],
) -> tuple[nx.DiGraph, dict[str, Any]]:
    """Build a directed graph where edge A -> B means file A imports file B."""
    g = nx.DiGraph()
    py_files = [f for f in files if f["language"] == "python"]
    py_paths = [f["path"] for f in py_files]
    py_set = set(py_paths)
    module_index = _build_module_index(py_paths)

    for f in files:
        g.add_node(
            f["path"],
            id=f["path"],
            label=Path(f["path"]).name,
            folder=Path(f["path"]).parent.as_posix() if "/" in f["path"] else "(root)",
            type="test" if f["is_test"] else ("entrypoint" if f["is_entrypoint"] else "file"),
            language=f["language"],
            size_bytes=f["size_bytes"],
            line_count=f["line_count"],
            symbol_count=f["symbol_count"],
        )

    edges_out: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str]] = set()

    for src_path, imports in file_imports.items():
        for imp in imports:
            resolved = resolve_import_target(src_path, imp, module_index, py_set)
            for tgt_path in resolved:
                key = (src_path, tgt_path)
                line = int(imp.get("line", 1))
                if key not in seen_edges:
                    seen_edges.add(key)
                    edge_record = {
                        "source": src_path,
                        "target": tgt_path,
                        "kind": "imports",
                        "evidence_level": "observed",
                        "evidence": {
                            "file": src_path,
                            "start_line": line,
                            "end_line": line,
                        },
                    }
                    g.add_edge(src_path, tgt_path, **edge_record)
                    edges_out.append(edge_record)

    nodes_out: list[dict[str, Any]] = []
    for node_id, attrs in g.nodes(data=True):
        in_deg = g.in_degree(node_id)
        out_deg = g.out_degree(node_id)
        nodes_out.append(
            {
                **attrs,
                "imported_by_count": in_deg,
                "imports_count": out_deg,
            }
        )

    nodes_out.sort(key=lambda n: (-n["imported_by_count"], n["id"]))
    hub_files = [n["id"] for n in nodes_out[:8] if n["imported_by_count"] > 0]

    return g, {
        "nodes": nodes_out,
        "edges": edges_out,
        "hub_files": hub_files,
    }
