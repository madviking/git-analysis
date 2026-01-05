from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


def run_git(args: list[str], cwd: Path, timeout_s: int = 300) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return proc.returncode, proc.stdout, proc.stderr


def discover_git_roots(root: Path, exclude_dirnames: set[str]) -> list[Path]:
    roots: list[Path] = []

    def onerror(err: OSError) -> None:
        _ = err

    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        has_git = ".git" in dirnames or ".git" in filenames
        if has_git:
            roots.append(Path(dirpath))
        dirnames[:] = [d for d in dirnames if d not in exclude_dirnames and d != ".git"]
    return roots


def get_repo_toplevel(candidate: Path) -> Optional[Path]:
    code, out, _ = run_git(["rev-parse", "--show-toplevel"], cwd=candidate)
    if code != 0:
        return None
    try:
        return Path(out.strip()).resolve()
    except Exception:
        return None


def get_remote_origin(repo: Path) -> str:
    code, out, _ = run_git(["config", "--get", "remote.origin.url"], cwd=repo)
    if code == 0:
        return out.strip()
    return ""


def canonicalize_remote(remote: str) -> str:
    r = (remote or "").strip()
    if not r:
        return ""

    if "://" not in r and ":" in r and "@" in r.split(":", 1)[0]:
        left, path = r.split(":", 1)
        host = left.split("@", 1)[1]
        canon = f"{host}/{path}"
    else:
        parsed = urlparse(r)
        if parsed.scheme and parsed.netloc:
            host = parsed.netloc
            if "@" in host:
                host = host.split("@", 1)[1]
            canon = f"{host}/{parsed.path.lstrip('/')}"
        else:
            canon = r

    canon = canon.rstrip("/")
    if canon.endswith(".git"):
        canon = canon[:-4]
    return canon.lower()


def remote_included(remote: str, include_prefixes: list[str]) -> bool:
    if not include_prefixes:
        return True
    canon = canonicalize_remote(remote)
    if not canon:
        return False
    for prefix in include_prefixes:
        p = canonicalize_remote(prefix)
        if not p:
            continue
        if canon == p or canon.startswith(p + "/"):
            return True
    return False


def get_remote_urls(repo: Path) -> dict[str, str]:
    code, out, _ = run_git(["config", "--get-regexp", r"^remote\..*\.url$"], cwd=repo)
    if code != 0:
        return {}
    remotes: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            key, url = line.split(None, 1)
        except ValueError:
            continue
        if not key.startswith("remote.") or not key.endswith(".url"):
            continue
        name = key[len("remote.") : -len(".url")]
        url = url.strip()
        if name and url:
            remotes[name] = url
    return remotes


def select_remote(
    remotes: dict[str, str],
    *,
    include_prefixes: list[str],
    priority: list[str],
) -> tuple[str, str, str]:
    if not remotes:
        return "", "", ""

    def matches(url: str) -> bool:
        return remote_included(url, include_prefixes) if include_prefixes else True

    items = [(name, url, canonicalize_remote(url)) for name, url in remotes.items()]
    matching = [t for t in items if matches(t[1])]
    pool = matching if matching else items

    prio_index = {name: i for i, name in enumerate(priority)}

    def sort_key(t: tuple[str, str, str]) -> tuple[int, str]:
        name = t[0]
        return (prio_index.get(name, 10_000), name.lower())

    name, url, canon = sorted(pool, key=sort_key)[0]
    return name, url, canon


def remotes_included(remotes: dict[str, str], include_prefixes: list[str], mode: str) -> bool:
    if not include_prefixes:
        return True
    if not remotes:
        return False
    if mode == "primary":
        return True
    return any(remote_included(url, include_prefixes) for url in remotes.values())


def detect_fork(
    remotes: dict[str, str],
    *,
    fork_remote_names: list[str],
) -> tuple[bool, str]:
    if not remotes:
        return False, ""

    parent_url = ""
    for name in fork_remote_names:
        if name in remotes and remotes[name].strip():
            parent_url = remotes[name].strip()
            break
    if not parent_url:
        return False, ""

    parent_canon = canonicalize_remote(parent_url)
    origin_canon = canonicalize_remote(remotes.get("origin", "")) if remotes.get("origin") else ""
    if origin_canon and parent_canon and origin_canon != parent_canon:
        return True, parent_canon

    for name, url in remotes.items():
        if name in fork_remote_names:
            continue
        c = canonicalize_remote(url)
        if c and parent_canon and c != parent_canon:
            return True, parent_canon

    return False, parent_canon


def get_last_commit(repo: Path) -> tuple[str | None, int | None]:
    code, out, _ = run_git(["log", "-n", "1", "--format=%aI\t%ct", "--all"], cwd=repo)
    if code != 0:
        return None, None
    line = out.strip()
    if not line:
        return None, None
    parts = line.split("\t", 1)
    if len(parts) != 2:
        return None, None
    iso = parts[0].strip() or None
    try:
        ts = int(parts[1].strip())
    except ValueError:
        ts = None
    return iso, ts


def get_first_commit(repo: Path) -> tuple[str | None, str | None, str | None]:
    code, out, _ = run_git(["log", "--reverse", "--format=%aI\t%an\t%ae", "-n", "1", "--all"], cwd=repo)
    if code != 0:
        return None, None, None
    line = out.strip()
    if not line:
        return None, None, None
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None, None, None
    return parts[0], parts[1], parts[2]
