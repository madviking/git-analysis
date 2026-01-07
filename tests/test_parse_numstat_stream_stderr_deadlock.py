from __future__ import annotations

import datetime as dt
import multiprocessing as mp
import os
from pathlib import Path

from git_analysis.analysis_periods import Period
from git_analysis.analysis_repo import parse_numstat_stream
from git_analysis.identity import MeMatcher
from git_analysis.models import BootstrapConfig


def _run_parse_numstat_stream_in_subprocess(
    queue: "mp.Queue[object]",
    *,
    repo_dir: str,
    fake_git_dir: str,
) -> None:
    os.environ["PATH"] = str(fake_git_dir) + os.pathsep + os.environ.get("PATH", "")

    period = Period(label="2025", start=dt.date(2025, 1, 1), end=dt.date(2026, 1, 1))
    me = MeMatcher(frozenset(), frozenset())
    bootstrap = BootstrapConfig(changed_threshold=50_000, files_threshold=200, addition_ratio=0.90)

    result = parse_numstat_stream(
        repo=Path(repo_dir),
        period=period,
        include_merges=False,
        me=me,
        bootstrap=bootstrap,
        exclude_path_prefixes=[],
        exclude_path_globs=[],
    )
    queue.put(result[-1])


def test_parse_numstat_stream_does_not_deadlock_on_stderr(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    fake_git_dir = tmp_path / "bin"
    fake_git_dir.mkdir()
    fake_git = fake_git_dir / "git"
    fake_git.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import sys",
                "",
                "def main() -> int:",
                "    if len(sys.argv) > 1 and sys.argv[1] == 'log':",
                "        sys.stdout.write('@@@a\\tA\\ta@e\\t2025-01-01T00:00:00Z\\tsub\\n')",
                "        sys.stdout.write('1\\t0\\tfile.py\\n')",
                "        sys.stdout.flush()",
                "        sys.stderr.write('E' * (2 * 1024 * 1024))",
                "        sys.stderr.flush()",
                "        sys.stdout.write('@@@b\\tB\\tb@e\\t2025-01-02T00:00:00Z\\tsub2\\n')",
                "        sys.stdout.write('2\\t0\\tfile2.py\\n')",
                "        sys.stdout.flush()",
                "        return 0",
                "    sys.stderr.write('unexpected args: ' + ' '.join(sys.argv) + '\\n')",
                "    return 2",
                "",
                "if __name__ == '__main__':",
                "    raise SystemExit(main())",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    queue: mp.Queue[object] = mp.Queue()
    proc = mp.Process(
        target=_run_parse_numstat_stream_in_subprocess,
        args=(queue,),
        kwargs={"repo_dir": str(repo_dir), "fake_git_dir": str(fake_git_dir)},
    )
    proc.start()
    proc.join(timeout=10)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=3)
        raise AssertionError("parse_numstat_stream hung when git produced large stderr output")

    assert proc.exitcode == 0
    errors = queue.get(timeout=3)
    assert errors == []
