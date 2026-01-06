from __future__ import annotations

import hashlib
from pathlib import Path

from .git import (
    canonicalize_remote,
    detect_fork,
    discover_git_roots,
    get_last_commit,
    get_remote_urls,
    get_repo_toplevel,
    remote_included,
    remotes_included,
    select_remote,
)


def _repo_key_for(dedupe_key: str) -> str:
    s = (dedupe_key or "").strip()
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def discover_and_select_repos(
    scan_root: Path,
    exclude_dirnames: set[str],
    *,
    include_remote_prefixes: list[str],
    remote_name_priority: list[str],
    remote_filter_mode: str,
    exclude_forks: bool,
    fork_remote_names: list[str],
    dedupe: str,
) -> tuple[
    list[Path],
    list[tuple[str, Path, str, str, str, list[str]]],
    list[dict[str, str]],
]:
    candidates = discover_git_roots(scan_root, exclude_dirnames)

    # Canonicalize and dedupe
    by_key: dict[str, dict] = {}
    selection_rows: list[dict[str, str]] = []
    for cand in candidates:
        top = get_repo_toplevel(cand)
        if top is None:
            selection_rows.append({"candidate_path": str(cand), "status": "skipped", "reason": "not_a_git_repo_after_rev_parse"})
            continue
        remotes = get_remote_urls(top)
        if not remotes:
            selection_rows.append({"candidate_path": str(cand), "repo_path": str(top), "status": "skipped", "reason": "no_remotes"})
            continue
        if exclude_forks:
            is_fork, fork_parent = detect_fork(remotes, fork_remote_names=fork_remote_names)
            if is_fork:
                selection_rows.append(
                    {
                        "candidate_path": str(cand),
                        "repo_path": str(top),
                        "status": "skipped",
                        "reason": "excluded_fork",
                        "fork_parent": fork_parent,
                        "remotes": ";".join(sorted(f"{k}={canonicalize_remote(v)}" for k, v in remotes.items())),
                    }
                )
                continue
        if not remotes_included(remotes, include_remote_prefixes, remote_filter_mode):
            selection_rows.append(
                {
                    "candidate_path": str(cand),
                    "repo_path": str(top),
                    "status": "skipped",
                    "reason": "remote_filter_no_match",
                    "remotes": ";".join(sorted(f"{k}={canonicalize_remote(v)}" for k, v in remotes.items())),
                }
            )
            continue
        remote_name, remote, remote_canonical = select_remote(remotes, include_prefixes=include_remote_prefixes, priority=remote_name_priority)
        if include_remote_prefixes and remote_filter_mode == "primary" and not remote_included(remote, include_remote_prefixes):
            selection_rows.append(
                {
                    "candidate_path": str(cand),
                    "repo_path": str(top),
                    "status": "skipped",
                    "reason": "primary_remote_not_included",
                    "remote_name": remote_name,
                    "remote_canonical": remote_canonical,
                }
            )
            continue

        if dedupe == "remote" and remote_canonical:
            dedupe_key = remote_canonical
        else:
            dedupe_key = str(top)
        repo_key = _repo_key_for(dedupe_key)

        entry = by_key.get(dedupe_key)
        if entry is None:
            last_iso, last_ts = get_last_commit(top)
            by_key[dedupe_key] = {
                "repo": top,
                "repo_key": repo_key,
                "remote_name": remote_name,
                "remote": remote,
                "remote_canonical": remote_canonical,
                "dups": [],
                "last_ts": last_ts,
                "last_iso": last_iso,
            }
            selection_rows.append(
                {
                    "candidate_path": str(cand),
                    "repo_path": str(top),
                    "status": "included",
                    "dedupe_key": dedupe_key,
                    "repo_key": repo_key,
                    "remote_name": remote_name,
                    "remote_canonical": remote_canonical,
                }
            )
        else:
            dup_path = str(top)
            # Prefer the freshest clone for a deduped remote to avoid undercounting due to stale clones.
            _, cand_ts = get_last_commit(top)
            entry_ts = entry.get("last_ts")
            if entry_ts is None:
                _, entry_ts = get_last_commit(entry["repo"])
                entry["last_ts"] = entry_ts
            prefer_new = cand_ts is not None and (entry_ts is None or cand_ts > entry_ts)
            if prefer_new:
                prev_path = str(entry["repo"])
                if prev_path != dup_path and prev_path not in entry["dups"]:
                    entry["dups"].append(prev_path)
                entry["repo"] = top
                entry["repo_key"] = repo_key
                entry["remote_name"] = remote_name
                entry["remote"] = remote
                entry["remote_canonical"] = remote_canonical
                entry["last_ts"] = cand_ts
                selection_rows.append(
                    {
                        "candidate_path": str(cand),
                        "repo_path": str(top),
                        "status": "included",
                        "dedupe_key": dedupe_key,
                        "repo_key": repo_key,
                        "remote_name": remote_name,
                        "remote_canonical": remote_canonical,
                        "note": f"replaced_clone:{prev_path}",
                    }
                )
            else:
                if dup_path != str(entry["repo"]) and dup_path not in entry["dups"]:
                    entry["dups"].append(dup_path)
                selection_rows.append(
                    {
                        "candidate_path": str(cand),
                        "repo_path": str(top),
                        "status": "duplicate",
                        "dedupe_key": dedupe_key,
                        "repo_key": repo_key,
                        "remote_name": remote_name,
                        "remote_canonical": remote_canonical,
                        "note": f"kept_clone:{entry['repo']}",
                    }
                )

    repos_to_analyze = [
        (v.get("repo_key", _repo_key_for(k)), v["repo"], v.get("remote_name", ""), v["remote"], v.get("remote_canonical", ""), v["dups"])
        for k, v in by_key.items()
    ]
    repos_to_analyze.sort(key=lambda x: x[1].as_posix())

    return candidates, repos_to_analyze, selection_rows
