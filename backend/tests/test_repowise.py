"""End-to-end tests for RepoWise backend services and FastAPI endpoints."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, store
from app.services.graph import build_dependency_graph
from app.services.impact import compute_change_impact
from app.services.ingest import IngestError, extract_zip_safely, validate_git_url
from app.services.llm import validate_citations
from app.services.scanner import redact_secrets, scan_repository

client = TestClient(app)


def test_url_validation_blocks_unsafe_schemes_and_hosts() -> None:
    assert validate_git_url("https://github.com/pallets/click") == "https://github.com/pallets/click.git"
    with pytest.raises(IngestError):
        validate_git_url("http://github.com/pallets/click")
    with pytest.raises(IngestError):
        validate_git_url("file:///etc/passwd")
    with pytest.raises(IngestError):
        validate_git_url("https://127.0.0.1/admin/repo")
    with pytest.raises(IngestError):
        validate_git_url("https://user:pass@github.com/pallets/click")


def test_zip_traversal_rejected(tmp_path: Path) -> None:
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../../evil.py", "print('pwned')")
    with pytest.raises(IngestError):
        extract_zip_safely(bad_zip, tmp_path / "out")


def test_secret_redaction_replaces_tokens_and_keys() -> None:
    raw = 'API_KEY = "sk-1234567890abcdefghijklmnop"\nNORMAL = "replace_me"\n'
    redacted, count = redact_secrets(raw)
    assert count >= 1
    assert "sk-1234567890" not in redacted
    assert "[REDACTED_SECRET]" in redacted
    assert "replace_me" in redacted


def test_scanner_graph_impact_and_citation_validation(tmp_path: Path) -> None:
    # Build a synthetic Python repo with an excluded folder, malformed file, auth service, route and test
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=topsecret\n", encoding="utf-8")

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "auth.py").write_text(
        "def verify_token(token: str) -> bool:\n"
        "    \"\"\"Verify user JWT token.\"\"\"\n"
        "    return token.startswith('valid_')\n",
        encoding="utf-8",
    )
    (app_dir / "main.py").write_text(
        "from app.auth import verify_token\n\n"
        "def login_endpoint(token: str) -> dict:\n"
        "    ok = verify_token(token)\n"
        "    return {'ok': ok}\n",
        encoding="utf-8",
    )
    (app_dir / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_auth.py").write_text(
        "from app.auth import verify_token\n\n"
        "def test_verify_token():\n"
        "    assert verify_token('valid_123')\n",
        encoding="utf-8",
    )

    scan = scan_repository(tmp_path)
    indexed_paths = {f["path"] for f in scan["files"]}
    assert "app/auth.py" in indexed_paths
    assert "app/main.py" in indexed_paths
    assert "tests/test_auth.py" in indexed_paths
    assert "node_modules/ignored.py" not in indexed_paths
    assert ".env" not in indexed_paths
    assert len(scan["parse_errors"]) == 1

    g, graph_data = build_dependency_graph(scan["files"], scan["file_imports"])
    edge_pairs = {(e["source"], e["target"]) for e in graph_data["edges"]}
    assert ("app/main.py", "app/auth.py") in edge_pairs
    assert ("tests/test_auth.py", "app/auth.py") in edge_pairs

    impact = compute_change_impact("app/auth.py", g, scan["files"], scan["routes"])
    assert "app/main.py" in impact["direct_dependents"]
    assert any(t["path"] == "tests/test_auth.py" for t in impact["related_tests"])
    assert impact["impact_score"] > 0

    # Citation validation: keep valid line ranges, reject bogus paths and out-of-range lines
    valid, rejected = validate_citations(
        [
            {"path": "app/auth.py", "start_line": 1, "end_line": 3, "symbol": "verify_token"},
            {"path": "app/nonexistent.py", "start_line": 1, "end_line": 5},
            {"path": "app/auth.py", "start_line": 999, "end_line": 1005},
        ],
        "Check [app/main.py:1-5] and [app/ghost.py:10-20]",
        scan["file_contents"],
        scan["symbols"],
    )
    valid_paths = {v["path"] for v in valid}
    assert valid_paths == {"app/auth.py", "app/main.py"}
    assert len(rejected) >= 2


def test_self_analyze_and_grounded_qa_endpoints() -> None:
    res = client.post("/api/v1/repositories/self-analyze")
    assert res.status_code == 200
    data = res.json()
    aid = data["id"]
    assert data["status"] == "completed"
    assert data["summary"]["total_files"] >= 5

    # Ask an answerable question about validate_git_url
    q_res = client.post(
        f"/api/v1/analyses/{aid}/questions",
        json={"question": "Where is validate_git_url defined and how are URLs validated?"},
    )
    assert q_res.status_code == 200
    ans = q_res.json()
    assert ans["evidence_level"] in {"observed", "inferred"}
    assert any("ingest.py" in c["path"] for c in ans["citations"])

    # Ask an unanswerable question and verify abstention
    un_res = client.post(
        f"/api/v1/analyses/{aid}/questions",
        json={"question": "Where is the Kubernetes Solidity smart contract blockchain validator?"},
    )
    assert un_res.status_code == 200
    un_ans = un_res.json()
    assert un_ans["evidence_level"] == "unknown"
    assert un_ans["citations"] == []

    # Delete workspace cleanup
    del_res = client.delete(f"/api/v1/repositories/{aid}")
    assert del_res.status_code == 200
    assert aid not in store.analyses
