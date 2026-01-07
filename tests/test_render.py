from __future__ import annotations

from git_analysis.analysis_render import pct_change


def test_pct_change() -> None:
    assert pct_change(0, 0) == "n/a"
    assert pct_change(0, 1) == "+inf"
    assert pct_change(10, 15) == "+50%"
    assert pct_change(10, 5) == "-50%"
    assert pct_change(3, 4) == "+33%"
    assert pct_change(3, 5) == "+67%"
    assert pct_change(3, 2) == "-33%"
