from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from .git import canonicalize_remote, discover_git_roots, get_remote_urls, get_repo_toplevel, select_remote
from .git import run_git


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def save_config(config_path: Path, config: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def infer_me() -> tuple[list[str], list[str]]:
    emails: list[str] = []
    names: list[str] = []

    code, out, _ = run_git(["config", "--global", "--get", "user.email"], cwd=Path.cwd())
    if code == 0 and out.strip():
        emails.append(out.strip())

    code, out, _ = run_git(["config", "--global", "--get", "user.name"], cwd=Path.cwd())
    if code == 0 and out.strip():
        names.append(out.strip())

    return emails, names


def _infer_github_usernames(emails: list[str]) -> list[str]:
    out: list[str] = []
    for e in emails:
        e = (e or "").strip().lower()
        if not e:
            continue
        if e.endswith("@users.noreply.github.com"):
            local = e.split("@", 1)[0]
            if "+" in local:
                local = local.rsplit("+", 1)[-1]
            local = local.lstrip("@").strip()
            if local:
                out.append(local)
    return out


def _remote_prefix(remote_canonical: str) -> str:
    canon = canonicalize_remote(remote_canonical)
    if not canon:
        return ""
    parts = [p for p in canon.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if parts else ""


def _suggest_include_remote_prefixes(*, scan_root: Path, exclude_dirnames: set[str], remote_name_priority: list[str]) -> list[str]:
    roots = discover_git_roots(scan_root, exclude_dirnames)
    counter: Counter[str] = Counter()
    for cand in roots:
        top = get_repo_toplevel(cand)
        if top is None:
            continue
        remotes = get_remote_urls(top)
        if not remotes:
            continue
        _, url, canon = select_remote(remotes, include_prefixes=[], priority=remote_name_priority)
        pref = _remote_prefix(canon or url)
        if pref:
            counter[pref] += 1
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _v in items]


def _prompt_str(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _prompt_bool(prompt: str, *, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    ans = _prompt_str(f"{prompt} {suffix} ").lower()
    if not ans:
        return default
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return default


def ensure_config_file(*, config_path: Path, template_path: Path, scan_root: Path, interactive: bool | None = None) -> dict:
    """
    If `config_path` does not exist, create it from `template_path`, fill in obvious
    blanks using local git config + scanned repo remotes, optionally prompt the user,
    then re-load and return the config dict.
    """
    if config_path.exists():
        return load_config(config_path)

    template: dict
    if template_path.exists():
        template = json.loads(template_path.read_text(encoding="utf-8"))
    else:
        template = {}

    config = json.loads(json.dumps(template)) if template else {}

    inferred_emails, inferred_names = infer_me()
    if isinstance(config.get("me_emails"), list) and not config.get("me_emails") and inferred_emails:
        config["me_emails"] = inferred_emails
    if isinstance(config.get("me_names"), list) and not config.get("me_names") and inferred_names:
        config["me_names"] = inferred_names
    if isinstance(config.get("me_github_usernames"), list) and not config.get("me_github_usernames"):
        gh = _infer_github_usernames(list(config.get("me_emails") or []))
        if gh:
            config["me_github_usernames"] = gh

    exclude_dirnames = set(config.get("exclude_dirnames") or [])
    exclude_dirnames.add(".git")
    remote_name_priority = list(config.get("remote_name_priority") or ["origin", "upstream"])

    if isinstance(config.get("include_remote_prefixes"), list) and not config.get("include_remote_prefixes"):
        prefixes = _suggest_include_remote_prefixes(
            scan_root=scan_root,
            exclude_dirnames=exclude_dirnames,
            remote_name_priority=remote_name_priority,
        )
        if prefixes:
            config["include_remote_prefixes"] = prefixes

    save_config(config_path, config)

    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if interactive:
        me_emails = list(config.get("me_emails") or [])
        me_names = list(config.get("me_names") or [])
        gh = list(config.get("me_github_usernames") or [])
        prefixes = list(config.get("include_remote_prefixes") or [])
        upload_cfg2 = dict((config.get("upload_config") or {}) if isinstance(config.get("upload_config"), dict) else {})

        print(f"\nWrote new config: {config_path}")
        print("Proposed values to review:")
        print(f"- me_emails: {me_emails!r}")
        print(f"- me_names: {me_names!r}")
        print(f"- me_github_usernames: {gh!r}")
        if prefixes:
            head = prefixes[:10]
            tail = "" if len(prefixes) <= 10 else f" (+{len(prefixes) - 10} more)"
            print(f"- include_remote_prefixes: {head!r}{tail}")
            print("  (clear this list to include all remotes without filtering)")
        api_url2 = str(upload_cfg2.get("api_url", "") or "").strip()
        if api_url2:
            print(f"- upload_config.api_url: {api_url2}")

        print("\nEdit the file now if needed, then press Enter to continue.")
        _ = _prompt_str("")
        if not _prompt_bool("Continue with analysis?", default=True):
            raise SystemExit(1)

    return load_config(config_path)
