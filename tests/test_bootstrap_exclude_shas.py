from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from git_analysis.analysis_periods import Period
from git_analysis.analysis_repo import parse_numstat_stream
from git_analysis.identity import MeMatcher
from git_analysis.models import BootstrapConfig


def test_bootstrap_exclude_sha_forces_non_bootstrap(tmp_path: Path, monkeypatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    fake_git_dir = tmp_path / "bin"
    fake_git_dir.mkdir()
    fake_git = fake_git_dir / "git"
    sha = "deadbeef"
    fake_git.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import sys",
                "def main() -> int:",
                "    if len(sys.argv) > 1 and sys.argv[1] == 'log':",
                f"        sys.stdout.write('@@@{sha}\\tA\\ta@e\\t2025-01-01T00:00:00Z\\tsub\\n')",
                "        sys.stdout.write('10\\t0\\tfile.py\\n')",
                "        sys.stdout.flush()",
                "        return 0",
                "    return 2",
                "if __name__ == '__main__':",
                "    raise SystemExit(main())",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_git_dir) + os.pathsep + os.environ.get("PATH", ""))

    period = Period(label="2025", start=dt.date(2025, 1, 1), end=dt.date(2026, 1, 1))
    me = MeMatcher(frozenset(), frozenset())
    bootstrap = BootstrapConfig(changed_threshold=1, files_threshold=1, addition_ratio=0.0)

    stats_excl, stats_boot, *_rest, boot_commits, errors = parse_numstat_stream(
        repo=repo_dir,
        period=period,
        include_merges=False,
        me=me,
        bootstrap=bootstrap,
        exclude_path_prefixes=[],
        exclude_path_globs=[],
        bootstrap_exclude_shas={sha},
    )

    assert errors == []
    assert boot_commits == []
    assert stats_boot.commits_total == 0
    assert stats_excl.commits_total == 1
