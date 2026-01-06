from __future__ import annotations

import datetime as dt

from git_analysis.analysis_periods import parse_period


def test_parse_period_accepts_h1yyyy_format() -> None:
    p = parse_period("H12025")
    assert p.label == "2025H1"
    assert p.start == dt.date(2025, 1, 1)
    assert p.end == dt.date(2025, 7, 1)

