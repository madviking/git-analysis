from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import analyze
from .publish import upload_existing_report_dir


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "upload":
        p = argparse.ArgumentParser(prog="git-analysis upload", description="Upload an existing report folder.")
        p.add_argument("--report-dir", type=Path, required=True, help="Path to an existing reports/<run-type>/<timestamp> directory.")
        p.add_argument("--config", type=Path, default=Path("config.json"), help="Path to config.json.")
        p.add_argument("--upload-url", type=str, default="", help="Override `upload_config.api_url` (or provide full /api/v1/uploads URL).")
        p.add_argument("--ca-bundle", type=str, default="", help="Path to a CA bundle file/dir for HTTPS verification (overrides `upload_config.ca_bundle_path`).")
        p.add_argument("--yes", action="store_true", help="Skip confirmation and upload immediately.")
        args = p.parse_args(argv[1:])
        return upload_existing_report_dir(
            report_dir=args.report_dir,
            config_path=args.config,
            upload_url_override=str(args.upload_url or ""),
            ca_bundle_path_override=str(args.ca_bundle or ""),
            assume_yes=bool(args.yes),
        )
    return analyze.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
