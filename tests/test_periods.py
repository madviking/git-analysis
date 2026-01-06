from __future__ import annotations

import datetime as dt

import pytest

from git_analysis.analysis_periods import Period, month_labels_for_period, parse_period, slugify


def test_parse_period_year() -> None:
    p = parse_period("2025")
    assert p.label == "2025"
    assert p.start == dt.date(2025, 1, 1)
    assert p.end == dt.date(2026, 1, 1)


def test_parse_period_halves() -> None:
    p1 = parse_period("2025H1")
    p2 = parse_period("2025H2")
    assert p1.start == dt.date(2025, 1, 1)
    assert p1.end == dt.date(2025, 7, 1)
    assert p2.start == dt.date(2025, 7, 1)
    assert p2.end == dt.date(2026, 1, 1)


def test_parse_period_invalid() -> None:
    with pytest.raises(ValueError):
        parse_period("H12025")


def test_month_labels_for_period() -> None:
    p = Period(label="custom", start=dt.date(2025, 11, 1), end=dt.date(2026, 2, 1))
    assert month_labels_for_period(p) == ["2025-11", "2025-12", "2026-01"]


def test_slugify() -> None:
    assert slugify("compare 2025H1 vs 2025H2") == "compare-2025H1-vs-2025H2"
    assert slugify("") == "run"

