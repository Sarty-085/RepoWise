"""Safe repository ingestion and ZIP extraction."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import shutil
import socket
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
MAX_REPO_MB = int(os.getenv("MAX_REPO_MB", "100"))
GIT_CLONE_DEPTH = int(os.getenv("GIT_CLONE_DEPTH", "500"))


class IngestError(ValueError):
    """Raised when a repository URL or archive violates safety rules."""


def validate_git_url(url: str) -> str:
    """Allow only HTTPS URLs on public Git hosts; block localhost and private IPs."""
    raw = (url or "").strip()
    if not raw or any(ch.isspace() or ord(ch) < 32 for ch in raw):
        raise IngestError("Repository URL cannot be empty or contain whitespace.")

    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise IngestError("Only https:// Git URLs are allowed.")
    if parsed.username or parsed.password:
        raise IngestError("Credentials in repository URLs are not allowed.")

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise IngestError(f"Host '{host}' is not in the allowed list ({', '.join(sorted(ALLOWED_HOSTS))}).")

    segments = [seg for seg in parsed.path.strip("/").split("/") if seg]
    if len(segments) < 2 or ".." in segments:
        raise IngestError("URL must be a repository path like https://github.com/owner/repo.")

    # Resolve DNS to verify the host does not map to private/loopback/link-local addresses.
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        # Offline tests still enforce hostname allowlist above.
        infos = []
    for info in infos:
        ip_obj = ipaddress.ip_address(info[4][0])
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
            raise IngestError("Repository host resolves to a restricted address.")

    owner, repo = segments[0], segments[1].removesuffix(".git")
    if not owner or not repo:
        raise IngestError("Invalid owner or repository name.")
    return f"https://{host}/{owner}/{repo}.git"


def dir_size_bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            fpath = Path(root) / fname
            if not fpath.is_symlink():
                try:
                    total += fpath.stat().st_size
                except OSError:
                    pass
    return total


def clone_repository(url: str, dest: Path, depth: int = GIT_CLONE_DEPTH) -> tuple[str, str]:
    """Shallow-clone a validated URL without running hooks or LFS smudges. Returns (commit_sha, repo_name)."""
    clean_url = validate_git_url(url)
    repo_name = clean_url.rstrip("/").split("/")[-1].removesuffix(".git")

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_LFS_SKIP_SMUDGE": "1",
    }
    cmd = [
        "git",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "-c",
        "core.symlinks=false",
        "-c",
        "core.hooksPath=/dev/null",
        "clone",
        "--no-checkout",
        "--depth",
        str(max(1, depth)),
        "--single-branch",
        clean_url,
        str(dest),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env, check=False)
    if res.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestError(f"git clone failed: {res.stderr.strip() or 'unknown error'}")

    checkout = subprocess.run(
        ["git", "-C", str(dest), "-c", "core.symlinks=false", "checkout", "-f", "HEAD"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    if checkout.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestError(f"git checkout failed: {checkout.stderr.strip()}")

    max_bytes = MAX_REPO_MB * 1024 * 1024
    if dir_size_bytes(dest) > max_bytes:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestError(f"Repository exceeds {MAX_REPO_MB} MB limit.")

    sha_res = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
        check=False,
    )
    commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "unknown"
    return commit_sha, repo_name


def extract_zip_safely(zip_path: Path, dest: Path) -> tuple[str, str]:
    """Extract a ZIP archive while rejecting path traversal, symlinks and zip bombs."""
    max_bytes = MAX_REPO_MB * 1024 * 1024
    if not zip_path.exists() or zip_path.stat().st_size > max_bytes:
        raise IngestError("Archive is missing or exceeds size limit.")

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()[:12]
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    resolved_root = dest.resolve()

    total_uncompressed = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                shutil.rmtree(dest, ignore_errors=True)
                raise IngestError(f"Unsafe path in archive: {member.filename}")
            # Reject POSIX symlinks encoded in external_attr
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                shutil.rmtree(dest, ignore_errors=True)
                raise IngestError(f"Symlinks in archives are not allowed: {member.filename}")
            total_uncompressed += member.file_size
            if total_uncompressed > max_bytes:
                shutil.rmtree(dest, ignore_errors=True)
                raise IngestError(f"Extracted archive exceeds {MAX_REPO_MB} MB limit.")

            target = (resolved_root / member_path).resolve()
            if resolved_root not in target.parents and target != resolved_root:
                shutil.rmtree(dest, ignore_errors=True)
                raise IngestError(f"Path traversal blocked: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    # Unwrap single top-level directory if present
    children = [p for p in dest.iterdir() if p.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        inner = children[0]
        for item in inner.iterdir():
            shutil.move(str(item), str(dest / item.name))
        inner.rmdir()

    return f"zip-{digest}", zip_path.stem
