from __future__ import annotations

import json
from pathlib import Path

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
