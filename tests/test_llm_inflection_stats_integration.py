from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return proc.stdout


def _commit_file(*, repo: Path, filename: str, content: str, author_date: str) -> None:
    p = repo / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _run(["git", "add", filename], cwd=repo)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = author_date
    env["GIT_COMMITTER_DATE"] = author_date
    _run(["git", "commit", "-m", f"update {filename}"], cwd=repo, env=env)


def test_llm_inflection_stats_written_when_dominant_at_configured(tmp_path: Path) -> None:
    today = dt.date.today()
    dominant = today - dt.timedelta(days=2)

    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)

    before = (dominant - dt.timedelta(days=1)).strftime("%Y-%m-%dT12:00:00Z")
    after = (dominant + dt.timedelta(days=1)).strftime("%Y-%m-%dT12:00:00Z")
    _commit_file(repo=repo, filename="before.txt", content="a\n", author_date=before)
    _commit_file(repo=repo, filename="after.txt", content="b\n", author_date=after)

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "upload_config": {
                    "llm_coding": {"dominant_at": {"value": dominant.isoformat(), "precision": "day"}},
                }
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))

    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        str(today.year),
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    # Decline publishing; the inflection report should still be written from config.json.
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input="n\n", text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr

    latest = (tmp_path / "reports" / "latest.txt").read_text(encoding="utf-8").strip()
    report_dir = tmp_path / "reports" / latest
    assert (report_dir / "llm_inflection_stats.txt").exists()
    md = report_dir / "markup" / "llm_inflection_stats.md"
    assert md.exists()
    assert md.read_text(encoding="utf-8").startswith("# Git comparison:")

