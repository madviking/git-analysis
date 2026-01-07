from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from git_analysis.config import ensure_config_file


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return proc.stdout


def _init_repo(*, repo: Path, remote: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Repo User"], cwd=repo)
    _run(["git", "config", "user.email", "repo@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", remote], cwd=repo)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _run(["git", "add", "a.txt"], cwd=repo)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = "2025-01-01T00:00:00Z"
    env["GIT_COMMITTER_DATE"] = "2025-01-01T00:00:00Z"
    _run(["git", "commit", "-m", "init"], cwd=repo, env=env)


def test_ensure_config_file_creates_from_template_and_infers(tmp_path: Path, monkeypatch) -> None:
    scan_root = tmp_path / "scan"
    _init_repo(repo=scan_root / "r1", remote="git@github.com:org1/repo1.git")
    _init_repo(repo=scan_root / "r2", remote="git@github.com:org2/repo2.git")

    template_path = tmp_path / "config-template.json"
    template_path.write_text(
        json.dumps(
            {
                "me_emails": [],
                "me_names": [],
                "me_github_usernames": [],
                "include_remote_prefixes": [],
                "remote_name_priority": ["origin", "upstream"],
                "upload_config": {
                    "automatic_upload": "confirm",
                    "api_url": "",
                    "publisher": "",
                    "upload_years": [2024, 2025],
                    "publisher_token_path": "",
                    "llm_coding": {},
                },
                "excluded_repos": [],
                "remote_filter_mode": "any",
                "exclude_forks": True,
                "fork_remote_names": ["upstream"],
                "exclude_dirnames": [".git", ".venv", "node_modules"],
                "exclude_path_prefixes": [],
                "exclude_path_globs": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    global_cfg = tmp_path / "global.gitconfig"
    global_cfg.write_text("[user]\n\temail = you@example.com\n\tname = Your Name\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_cfg))

    config_path = tmp_path / "config.json"
    cfg = ensure_config_file(config_path=config_path, template_path=template_path, scan_root=scan_root, interactive=False)

    assert config_path.exists()
    assert cfg["me_emails"] == ["you@example.com"]
    assert cfg["me_names"] == ["Your Name"]
    assert cfg["include_remote_prefixes"] == ["github.com/org1", "github.com/org2"]
