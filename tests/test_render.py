from __future__ import annotations

from git_analysis.analysis_render import fmt_int, pct_change


def test_pct_change() -> None:
    assert pct_change(0, 0) == "n/a"
    assert pct_change(0, 1) == "+inf"
    assert pct_change(10, 15) == "+50%"
    assert pct_change(10, 5) == "-50%"
    assert pct_change(3, 4) == "+33%"
    assert pct_change(3, 5) == "+67%"
    assert pct_change(3, 2) == "-33%"


def test_fmt_int_human_readable() -> None:
    assert fmt_int(0) == "0"
    assert fmt_int(999) == "999"
    assert fmt_int(1000) == "1K"
    assert fmt_int(1500) == "1.5K"
    assert fmt_int(12_345) == "12.3K"
    assert fmt_int(999_499) == "999K"
    assert fmt_int(1_000_000) == "1M"
    assert fmt_int(2_500_000) == "2.5M"
    assert fmt_int(-1000) == "-1K"


def test_pct_change_human_readable_for_large_values() -> None:
    assert pct_change(1, 11) == "+1K%"
