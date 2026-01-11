from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import analyze
from .publish import set_profile_display_name, upload_existing_report_dir, verify_github_username


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        from .analysis_cli import _build_parser

        p = _build_parser()
        p.prog = "git-analysis"
        p.print_help()
        print("")
        print("commands:")
        print("  upload         Upload an existing report folder.")
        print("  display-name   Update your public display name on the upload server.")
        print("  github-verify  Verify a GitHub username by SSH key ownership (no OAuth).")
        print("")
        print("Run `git-analysis <command> --help` for command-specific options.")
        return 0
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
    if argv and argv[0] == "display-name":
        p = argparse.ArgumentParser(prog="git-analysis display-name", description="Update your public display name on the upload server.")
        p.add_argument("--config", type=Path, default=Path("config.json"), help="Path to config.json.")
        p.add_argument("--api-url", type=str, default="", help="Override `upload_config.api_url`.")
        p.add_argument("--ca-bundle", type=str, default="", help="Path to a CA bundle file/dir for HTTPS verification (overrides `upload_config.ca_bundle_path`).")
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--name", type=str, default="", help="New display name (max 80 chars).")
        g.add_argument("--github", type=str, default="", help="Set display name to a GitHub username.")
        g.add_argument("--pseudonym", action="store_true", help="Reset display name to the derived pseudonym for this token.")
        args = p.parse_args(argv[1:])
        return set_profile_display_name(
            config_path=args.config,
            display_name=str(args.name or ""),
            github_username=str(args.github or ""),
            use_pseudonym=bool(args.pseudonym),
            api_url_override=str(args.api_url or ""),
            ca_bundle_path_override=str(args.ca_bundle or ""),
        )
    if argv and argv[0] == "github-verify":
        p = argparse.ArgumentParser(prog="git-analysis github-verify", description="Verify a GitHub username by SSH key ownership (no OAuth).")
        p.add_argument("--config", type=Path, default=Path("config.json"), help="Path to config.json.")
        p.add_argument("--api-url", type=str, default="", help="Override `upload_config.api_url`.")
        p.add_argument("--ca-bundle", type=str, default="", help="Path to a CA bundle file/dir for HTTPS verification (overrides `upload_config.ca_bundle_path`).")
        p.add_argument("--username", type=str, required=True, help="GitHub username to verify.")
        args = p.parse_args(argv[1:])
        return verify_github_username(
            config_path=args.config,
            github_username=str(args.username or ""),
            api_url_override=str(args.api_url or ""),
            ca_bundle_path_override=str(args.ca_bundle or ""),
        )
    return analyze.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
