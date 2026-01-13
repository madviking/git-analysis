from __future__ import annotations

import argparse
import dataclasses
import datetime as dt


@dataclasses.dataclass(frozen=True)
class Period:
    label: str
    start: dt.date  # inclusive
    end: dt.date  # exclusive

    @property
    def start_iso(self) -> str:
        return self.start.isoformat()

    @property
    def end_iso(self) -> str:
        return self.end.isoformat()


def parse_period(spec: str) -> Period:
    s = (spec or "").strip()
    if len(s) == 4 and s.isdigit():
        year = int(s)
        return Period(label=s, start=dt.date(year, 1, 1), end=dt.date(year + 1, 1, 1))
    if len(s) == 6 and s[:4].isdigit() and s[4:].upper() in ("H1", "H2"):
        year = int(s[:4])
        half = s[4:].upper()
        if half == "H1":
            return Period(label=f"{year}H1", start=dt.date(year, 1, 1), end=dt.date(year, 7, 1))
        return Period(label=f"{year}H2", start=dt.date(year, 7, 1), end=dt.date(year + 1, 1, 1))
    if len(s) == 6 and s[:2].upper() in ("H1", "H2") and s[2:].isdigit():
        half = s[:2].upper()
        year = int(s[2:])
        return parse_period(f"{year}{half}")
    raise ValueError(f"Invalid period: {spec!r} (expected YYYY, YYYYH1, or YYYYH2)")


def slugify(s: str) -> str:
    s = (s or "").strip()
    out: list[str] = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        elif ch in (" ", ".", ":", "/", "\\"):
            out.append("-")
        else:
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "run"


def run_type_from_args(args: argparse.Namespace, periods: list[Period]) -> str:
    labels = [p.label for p in periods]
    halves = getattr(args, "halves", "") or ""
    if str(halves).strip():
        return "halves_" + slugify(str(halves))
    if getattr(args, "periods", None):
        if len(labels) == 2:
            return f"compare_{labels[0]}_vs_{labels[1]}"
        return "periods_" + "_".join(labels)
    # default: years
    if len(labels) == 2:
        return f"compare_{labels[0]}_vs_{labels[1]}"
    return "years_" + "_".join(labels)


def month_labels_for_period(period: Period) -> list[str]:
    cur = dt.date(period.start.year, period.start.month, 1)
    out: list[str] = []
    while cur < period.end:
        out.append(f"{cur.year:04d}-{cur.month:02d}")
        if cur.month == 12:
            cur = dt.date(cur.year + 1, 1, 1)
        else:
            cur = dt.date(cur.year, cur.month + 1, 1)
    return out


def parse_date_precision_to_date(value: dict[str, str] | None) -> dt.date | None:
    if not isinstance(value, dict):
        return None
    v = str(value.get("value", "") or "").strip()
    p = str(value.get("precision", "") or "").strip().lower()
    if not v or p not in ("year", "month", "day"):
        return None
    try:
        if p == "day":
            return dt.date.fromisoformat(v)
        if p == "month":
            y, m = v.split("-", 1)
            return dt.date(int(y), int(m), 1)
        if p == "year":
            return dt.date(int(v), 1, 1)
    except Exception:
        return None
    return None


def llm_inflection_periods(*, dominant_at: dt.date, today: dt.date | None = None) -> tuple[Period, Period]:
    if today is None:
        today = dt.date.today()
    end_after = today + dt.timedelta(days=1)
    delta = end_after - dominant_at
    if delta.days <= 0:
        raise ValueError("dominant_at must be before today")
    start_before = dominant_at - delta
    before = Period(label="pre_dominant", start=start_before, end=dominant_at)
    after = Period(label="post_dominant", start=dominant_at, end=end_after)
    return before, after
