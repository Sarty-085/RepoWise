"""Static file scanner, secret redactor, Python AST extractor and code chunker.

Never imports or executes repository files; reads bytes as data only.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
from pathlib import Path
from typing import Any

MAX_FILE_KB = int(os.getenv("MAX_FILE_KB", "500"))

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    "coverage",
    "htmlcov",
    ".tox",
    "eggs",
    ".eggs",
    "vendor",
}

DEFAULT_EXCLUDED_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "credentials.json",
    "service-account.json",
}

EXCLUDED_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".keystore",
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".bin",
    ".min.js",
    ".min.css",
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
}

EXT_LANGUAGE = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".sh": "shell",
    ".html": "html",
    ".css": "css",
}

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PRIVATE )?PRIVATE KEY-----[\s\S]*?-----END [^\n]+-----"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,255}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\bAQ\.[A-Za-z0-9_\-]{25,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b"),
    re.compile(
        r"""(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|client[_-]?secret)\s*[:=]\s*(['"])([^'"\n]{8,})\2"""
    ),
]

ROUTE_DECORATOR_METHODS = {"get", "post", "put", "delete", "patch", "route", "api_route", "websocket"}
ENTRYPOINT_FILENAMES = {
    "main.py",
    "app.py",
    "server.py",
    "wsgi.py",
    "asgi.py",
    "manage.py",
    "cli.py",
    "__main__.py",
}


def redact_secrets(text: str) -> tuple[str, int]:
    """Replace likely secret literals with [REDACTED_SECRET] and return (redacted_text, count)."""
    count = 0
    out = text
    for pattern in SECRET_PATTERNS[:-1]:
        out, n = pattern.subn("[REDACTED_SECRET]", out)
        count += n
    # Key-value assignment pattern preserves the variable name
    kv_pat = SECRET_PATTERNS[-1]

    def _kv_repl(match: re.Match[str]) -> str:
        nonlocal count
        val = match.group(3)
        if val.lower() in {"replace_me", "changeme", "your_api_key", "none", "null", "REDACTED"}:
            return match.group(0)
        count += 1
        return f"{match.group(1)} = {match.group(2)}[REDACTED_SECRET]{match.group(2)}"

    out = kv_pat.sub(_kv_repl, out)
    return out, count


def is_binary_bytes(sample: bytes) -> bool:
    return b"\x00" in sample


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [a.arg for a in node.args.posonlyargs + node.args.args]
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    args.extend(f"{a.arg}=..." for a in node.args.kwonlyargs)
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(args)})"


def _extract_route_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            attr = dec.func.attr.lower()
            if attr in ROUTE_DECORATOR_METHODS:
                path_arg = ""
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    path_arg = dec.args[0].value
                return f"{attr.upper()} {path_arg}".strip()
    return None


def _has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.If):
            try:
                src = ast.unparse(node.test)
                if "__name__" in src and "__main__" in src:
                    return True
            except Exception:
                pass
    return False


def parse_python_source(rel_path: str, text: str) -> dict[str, Any]:
    """Parse Python source into imports, symbols, routes, entrypoint flags and chunks."""
    lines = text.splitlines()
    total_lines = max(1, len(lines))
    result: dict[str, Any] = {
        "imports": [],
        "symbols": [],
        "routes": [],
        "chunks": [],
        "is_entrypoint": Path(rel_path).name in ENTRYPOINT_FILENAMES,
        "parse_error": None,
    }

    try:
        tree = ast.parse(text, filename=rel_path)
    except SyntaxError as exc:
        result["parse_error"] = f"SyntaxError at line {exc.lineno}: {exc.msg}"
        # Still provide a bounded file chunk so search works on partially broken repos
        snippet = "\n".join(lines[: min(120, total_lines)])
        result["chunks"].append(
            {
                "id": f"{rel_path}:1-{min(120, total_lines)}",
                "path": rel_path,
                "symbol": Path(rel_path).stem,
                "kind": "module",
                "start_line": 1,
                "end_line": min(120, total_lines),
                "text": snippet,
            }
        )
        return result

    if _has_main_guard(tree):
        result["is_entrypoint"] = True

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(
                    {
                        "module": alias.name,
                        "names": [alias.asname or alias.name],
                        "level": 0,
                        "line": getattr(node, "lineno", 1),
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            result["imports"].append(
                {
                    "module": node.module or "",
                    "names": [a.name for a in node.names],
                    "level": node.level or 0,
                    "line": getattr(node, "lineno", 1),
                }
            )

    header_end = 0
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom, ast.Expr)):
            header_end = max(header_end, getattr(stmt, "end_lineno", getattr(stmt, "lineno", 1)))
        else:
            break
    header_context = "\n".join(lines[: min(header_end, 25)]).strip()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = getattr(node, "lineno", 1)
            if node.decorator_list:
                start = min(start, *(getattr(d, "lineno", start) for d in node.decorator_list))
            end = getattr(node, "end_lineno", start)
            sig = _format_signature(node)
            doc = (ast.get_docstring(node) or "").splitlines()[0] if ast.get_docstring(node) else ""
            route = _extract_route_decorator(node)
            if route:
                result["routes"].append(
                    {
                        "route": route,
                        "handler": node.name,
                        "path": rel_path,
                        "start_line": start,
                        "end_line": end,
                    }
                )
            result["symbols"].append(
                {
                    "name": node.name,
                    "qualified_name": f"{rel_path}:{node.name}",
                    "kind": "route" if route else "function",
                    "path": rel_path,
                    "start_line": start,
                    "end_line": end,
                    "signature": sig,
                    "docstring": doc,
                }
            )
            body_text = "\n".join(lines[start - 1 : end])
            result["chunks"].append(
                {
                    "id": f"{rel_path}:{start}-{end}",
                    "path": rel_path,
                    "symbol": node.name,
                    "kind": "route" if route else "function",
                    "start_line": start,
                    "end_line": end,
                    "text": body_text,
                    "header_context": header_context,
                }
            )
        elif isinstance(node, ast.ClassDef):
            start = getattr(node, "lineno", 1)
            if node.decorator_list:
                start = min(start, *(getattr(d, "lineno", start) for d in node.decorator_list))
            end = getattr(node, "end_lineno", start)
            bases = [ast.unparse(b) for b in node.bases] if node.bases else []
            sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
            doc = (ast.get_docstring(node) or "").splitlines()[0] if ast.get_docstring(node) else ""
            methods = [
                n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            result["symbols"].append(
                {
                    "name": node.name,
                    "qualified_name": f"{rel_path}:{node.name}",
                    "kind": "class",
                    "path": rel_path,
                    "start_line": start,
                    "end_line": end,
                    "signature": sig,
                    "docstring": doc,
                    "methods": methods,
                }
            )
            # If class is very large (>120 lines), chunk per method; else chunk whole class
            if end - start > 120 and methods:
                class_header = "\n".join(lines[start - 1 : min(start + 15, end)])
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_start = getattr(sub, "lineno", start)
                        m_end = getattr(sub, "end_lineno", m_start)
                        result["symbols"].append(
                            {
                                "name": f"{node.name}.{sub.name}",
                                "qualified_name": f"{rel_path}:{node.name}.{sub.name}",
                                "kind": "method",
                                "path": rel_path,
                                "start_line": m_start,
                                "end_line": m_end,
                                "signature": _format_signature(sub),
                                "docstring": (ast.get_docstring(sub) or "").splitlines()[0]
                                if ast.get_docstring(sub)
                                else "",
                            }
                        )
                        result["chunks"].append(
                            {
                                "id": f"{rel_path}:{m_start}-{m_end}",
                                "path": rel_path,
                                "symbol": f"{node.name}.{sub.name}",
                                "kind": "method",
                                "start_line": m_start,
                                "end_line": m_end,
                                "text": "\n".join(lines[m_start - 1 : m_end]),
                                "header_context": class_header,
                            }
                        )
            else:
                result["chunks"].append(
                    {
                        "id": f"{rel_path}:{start}-{end}",
                        "path": rel_path,
                        "symbol": node.name,
                        "kind": "class",
                        "start_line": start,
                        "end_line": end,
                        "text": "\n".join(lines[start - 1 : end]),
                        "header_context": header_context,
                    }
                )

    # Always add a module-level chunk when a file has no functions/classes or has top-level script code
    if not result["chunks"]:
        end_line = min(total_lines, 120)
        result["chunks"].append(
            {
                "id": f"{rel_path}:1-{end_line}",
                "path": rel_path,
                "symbol": Path(rel_path).stem,
                "kind": "module",
                "start_line": 1,
                "end_line": end_line,
                "text": "\n".join(lines[:end_line]),
                "header_context": "",
            }
        )

    return result


def detect_frameworks(repo_root: Path, all_imports: set[str]) -> list[str]:
    """Identify frameworks from observed manifest files and imports."""
    detected: list[str] = []
    manifests = ""
    for fname in ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "package.json"):
        fpath = repo_root / fname
        if fpath.is_file() and fpath.stat().st_size < 200_000:
            try:
                manifests += "\n" + fpath.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                pass
    lower_imports = {imp.split(".")[0].lower() for imp in all_imports}
    candidates = [
        ("FastAPI", "fastapi"),
        ("Flask", "flask"),
        ("Django", "django"),
        ("SQLAlchemy", "sqlalchemy"),
        ("Pydantic", "pydantic"),
        ("Celery", "celery"),
        ("Pytest", "pytest"),
        ("Click", "click"),
        ("Typer", "typer"),
        ("Tornado", "tornado"),
        ("Starlette", "starlette"),
        ("AIOHTTP", "aiohttp"),
        ("NumPy", "numpy"),
        ("Pandas", "pandas"),
        ("React", "react"),
    ]
    for label, token in candidates:
        if token in lower_imports or re.search(rf"\b{re.escape(token)}\b", manifests):
            detected.append(label)
    return detected


def scan_repository(repo_root: Path) -> dict[str, Any]:
    """Walk repo_root safely and extract files, symbols, imports, routes and chunks."""
    max_file_bytes = MAX_FILE_KB * 1024
    files: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    symbols: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    file_imports: dict[str, list[dict[str, Any]]] = {}
    file_contents: dict[str, list[str]] = {}
    language_counts: dict[str, int] = {}
    entrypoints: list[str] = []
    all_import_roots: set[str] = set()
    redacted_secrets_total = 0
    parse_errors: list[dict[str, str]] = []

    for current_root, dirs, filenames in os.walk(repo_root, followlinks=False):
        rel_dir = Path(current_root).relative_to(repo_root)
        # Filter excluded directories in-place
        kept_dirs = []
        for d in sorted(dirs):
            if d in DEFAULT_EXCLUDED_DIRS or d.startswith(".git"):
                excluded.append({"path": (rel_dir / d).as_posix(), "reason": "excluded_directory"})
            else:
                kept_dirs.append(d)
        dirs[:] = kept_dirs

        for fname in sorted(filenames):
            fpath = Path(current_root) / fname
            rel_path = fpath.relative_to(repo_root).as_posix()

            if fpath.is_symlink():
                excluded.append({"path": rel_path, "reason": "symlink"})
                continue
            if fname in DEFAULT_EXCLUDED_FILES or fname.startswith(".env."):
                excluded.append({"path": rel_path, "reason": "sensitive_file"})
                continue
            lower_name = fname.lower()
            if any(lower_name.endswith(suf) for suf in EXCLUDED_SUFFIXES):
                excluded.append({"path": rel_path, "reason": "binary_or_generated_suffix"})
                continue

            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > max_file_bytes:
                excluded.append({"path": rel_path, "reason": f"exceeds_{MAX_FILE_KB}kb_limit"})
                continue
            if size == 0:
                continue

            try:
                raw_bytes = fpath.read_bytes()
            except OSError:
                continue
            if is_binary_bytes(raw_bytes[:4096]):
                excluded.append({"path": rel_path, "reason": "binary_content"})
                continue

            text = raw_bytes.decode("utf-8", errors="replace")
            redacted_text, secret_hits = redact_secrets(text)
            redacted_secrets_total += secret_hits
            lines = redacted_text.splitlines()

            ext = fpath.suffix.lower()
            lang = EXT_LANGUAGE.get(ext, "other")
            language_counts[lang] = language_counts.get(lang, 0) + 1
            content_hash = hashlib.sha256(raw_bytes).hexdigest()[:12]

            is_test = (
                "test" in Path(rel_path).parts
                or "tests" in Path(rel_path).parts
                or fname.startswith("test_")
                or fname.endswith("_test.py")
            )

            file_record: dict[str, Any] = {
                "path": rel_path,
                "language": lang,
                "size_bytes": size,
                "line_count": len(lines),
                "content_hash": content_hash,
                "is_test": is_test,
                "is_entrypoint": False,
                "symbol_count": 0,
                "redacted_secrets": secret_hits,
            }

            if lang == "python":
                parsed = parse_python_source(rel_path, redacted_text)
                file_imports[rel_path] = parsed["imports"]
                for imp in parsed["imports"]:
                    if imp["module"]:
                        all_import_roots.add(imp["module"])
                symbols.extend(parsed["symbols"])
                routes.extend(parsed["routes"])
                chunks.extend(parsed["chunks"])
                file_record["symbol_count"] = len(parsed["symbols"])
                file_record["is_entrypoint"] = parsed["is_entrypoint"]
                if parsed["is_entrypoint"]:
                    entrypoints.append(rel_path)
                if parsed["parse_error"]:
                    parse_errors.append({"path": rel_path, "error": parsed["parse_error"]})
            elif lang in {"markdown", "toml", "yaml", "json"} and fname.lower() in {
                "readme.md",
                "pyproject.toml",
                "requirements.txt",
                "package.json",
            }:
                end_line = min(len(lines), 100)
                chunks.append(
                    {
                        "id": f"{rel_path}:1-{end_line}",
                        "path": rel_path,
                        "symbol": fname,
                        "kind": "doc",
                        "start_line": 1,
                        "end_line": end_line,
                        "text": "\n".join(lines[:end_line]),
                        "header_context": "",
                    }
                )

            files.append(file_record)
            file_contents[rel_path] = lines

    frameworks = detect_frameworks(repo_root, all_import_roots)
    top_folders: dict[str, int] = {}
    for f in files:
        parts = f["path"].split("/")
        folder = parts[0] if len(parts) > 1 else "(root)"
        top_folders[folder] = top_folders.get(folder, 0) + 1

    return {
        "files": files,
        "excluded": excluded[:200],
        "symbols": symbols,
        "routes": routes,
        "chunks": chunks,
        "file_imports": file_imports,
        "file_contents": file_contents,
        "language_counts": language_counts,
        "frameworks": frameworks,
        "entrypoints": entrypoints,
        "top_folders": top_folders,
        "redacted_secrets_total": redacted_secrets_total,
        "parse_errors": parse_errors,
    }
