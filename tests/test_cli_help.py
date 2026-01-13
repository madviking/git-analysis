from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_root_help_mentions_commands(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))
    cmd = [str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"), "-m", "git_analysis", "--help"]
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "upload" in out
    assert "display-name" in out
    assert "github-verify" in out
    assert "Aggregate yearly git stats" in out
