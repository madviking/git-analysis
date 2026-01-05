from __future__ import annotations

import sys

from . import analyze


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    return analyze.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

