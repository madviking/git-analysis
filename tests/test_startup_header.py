from __future__ import annotations

from pathlib import Path

from git_analysis.analysis_periods import parse_period
from git_analysis.analysis_run import format_startup_header


def test_format_startup_header_explains_run_plan() -> None:
    out = format_startup_header(
        root=Path("/tmp/root"),
        periods=[parse_period("2025")],
        config_path=Path("config.json"),
        config_missing=False,
        jobs=4,
        dedupe="remote",
        max_repos=0,
        include_merges=False,
        include_bootstraps=False,
        top_authors=25,
        detailed=False,
        publish="no",
        publish_block_reasons=[],
    )

    assert "git-analysis" in out
    assert "Run plan:" in out
    assert "1) Config:" in out
    assert "2) Discover repos:" in out
    assert "3) Analyze git history:" in out
    assert "4) Write reports:" in out
    assert "5) Publish prompt:" in out
    assert "read-only" in out.lower()
    assert "default: no" in out.lower()


def test_format_startup_header_mentions_publish_block_reasons() -> None:
    out = format_startup_header(
        root=Path("/tmp/root"),
        periods=[parse_period("2025")],
        config_path=Path("config.json"),
        config_missing=False,
        jobs=4,
        dedupe="path",
        max_repos=10,
        include_merges=True,
        include_bootstraps=True,
        top_authors=25,
        detailed=True,
        publish="yes",
        publish_block_reasons=["--include-merges", "--include-bootstraps", "--dedupe path"],
    )

    assert "Publish prompt: disabled" in out
    assert "--include-merges" in out
