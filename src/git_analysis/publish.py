from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from . import __version__
from .analysis_aggregate import aggregate_weekly_me, aggregate_weekly_me_tech
from .analysis_render import fmt_int
from .analysis_periods import Period
from .config import load_config, save_config
from .identity import normalize_github_username
from .models import RepoResult
from .upload_package_v1 import (
    canonical_json_bytes,
    ensure_publisher_ed25519_keypair,
    ensure_publisher_token,
    github_verify_challenge_v1,
    github_verify_confirm_v1,
    sign_publisher_ed25519_message_base64,
    update_display_name_v1,
    upload_package_v1,
)


def default_publisher_token_path() -> Path:
    return Path.home() / ".config" / "git-analysis" / "publisher_token"


def default_publisher_key_path(*, token_path: Path) -> Path:
    """
    Default publisher key path is colocated with the publisher token for a shared lifecycle.
    """
    tp = Path(token_path).expanduser()
    return tp.parent / "publisher_ed25519"


def pseudonym_for_token(token: str) -> str:
    h = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"anon-{h[:12]}"


def _publisher_key_path_from_upload_cfg(*, upload_cfg: dict[str, object], token_path: Path) -> Path:
    key_path_s = str(upload_cfg.get("publisher_key_path", "") or "").strip()
    if key_path_s:
        return Path(key_path_s).expanduser()
    return default_publisher_key_path(token_path=token_path)


def _prompt_bool(prompt: str, *, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
    except EOFError:
        return default
    if not ans:
        return default
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return default


def _prompt_str(prompt: str, *, default: str | None = None) -> str:
    if default is None or default == "":
        suffix = ""
    else:
        suffix = f" [{default}]"
    try:
        ans = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default or ""
    if ans:
        return ans
    return default or ""


def _prompt_choice(prompt: str, *, choices: tuple[str, ...], default: str) -> str:
    d = default if default in choices else choices[0]
    ans = _prompt_str(f"{prompt} ({'/'.join(choices)})", default=d).strip().lower()
    return ans if ans in choices else d


_LLM_TOOL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("none", "None / not using LLM coding tools"),

    # Major copilots / IDE assistants
    ("github_copilot", "GitHub Copilot"),
    ("amazon_q", "Amazon Q Developer"),
    ("jetbrains_ai", "JetBrains AI Assistant"),
    ("tabnine", "TabNine"),
    ("codeium", "Codeium"),
    ("sourcegraph_cody", "Sourcegraph Cody"),

    # AI-native editors / environments
    ("cursor", "Cursor"),
    ("windsurf", "Windsurf"),
    ("zed_ai", "Zed (AI features)"),
    ("replit_ghostwriter", "Replit Ghostwriter"),

    # General LLM chat used for coding
    ("chatgpt", "ChatGPT"),
    ("openai_codex", "OpenAI Codex"),
    ("claude", "Claude"),
    ("gemini", "Google Gemini"),

    # Agentic / task-based coding tools
    ("devin", "Devin"),
    ("bolt_new", "Bolt.new (StackBlitz)"),
    ("v0", "v0 (Vercel)"),
    ("sweep", "Sweep"),
    ("factory_ai", "Factory AI"),

    # Code review / quality / security
    ("qodo", "Qodo (CodiumAI)"),
    ("snyk_code", "Snyk Code"),

    # OSS / terminal / power-user tools
    ("continue", "Continue"),
    ("aider", "Aider"),
    ("cline", "Cline"),

    # Search / reverse-engineering
    ("phind", "Phind"),
    ("blackbox", "Blackbox AI"),

    ("other", "Other"),
)


def _prompt_enum(prompt: str, *, options: tuple[tuple[str, str], ...], default: str) -> str:
    ids = [k for k, _label in options]
    labels = {k: label for k, label in options}
    d = default if default in labels else options[0][0]
    print(prompt)
    for i, (k, label) in enumerate(options, start=1):
        suffix = " (default)" if k == d else ""
        print(f"  {i}) {label} [{k}]{suffix}")
    ans = _prompt_str("Select", default=d).strip()
    if not ans:
        return d
    if ans.isdigit():
        idx = int(ans)
        if 1 <= idx <= len(ids):
            return ids[idx - 1]
        return d
    ans_norm = ans.strip().lower()
    return ans_norm if ans_norm in labels else d


_DATE_RE = re.compile(r"^\d{4}(-\d{2})?(-\d{2})?$")


def _parse_date_precision(value: str) -> dict[str, str] | None:
    s = (value or "").strip()
    if not s:
        return None
    if s.lower() in ("unknown", "n/a", "na", "none", "-"):
        return None
    if not _DATE_RE.match(s):
        return None
    if len(s) == 4:
        return {"value": s, "precision": "year"}
    if len(s) == 7:
        return {"value": s, "precision": "month"}
    if len(s) == 10:
        return {"value": s, "precision": "day"}
    return None


def _prompt_date(prompt: str, *, default: dict[str, str] | None) -> dict[str, str] | None:
    default_s = ""
    if isinstance(default, dict) and default.get("value") and default.get("precision"):
        default_s = str(default.get("value", "")).strip()
    for _attempt in range(3):
        ans = _prompt_str(f"{prompt} (YYYY or YYYY-MM or YYYY-MM-DD; blank/unknown to skip)", default=default_s).strip()
        parsed = _parse_date_precision(ans)
        if parsed is not None:
            return parsed
        if not ans or ans.lower() in ("unknown", "n/a", "na", "none", "-"):
            return None
        print("Invalid date format; try YYYY, YYYY-MM, or YYYY-MM-DD.")
    return default


def _prompt_llm_coding(upload_cfg: dict[str, object]) -> dict[str, object]:
    existing = dict((upload_cfg.get("llm_coding") or {}) if isinstance(upload_cfg.get("llm_coding"), dict) else {})
    started_at = _prompt_date(
        "When did you start using LLM coding tools?",
        default=existing.get("started_at") if isinstance(existing.get("started_at"), dict) else None,
    )
    dominant_at = _prompt_date(
        "When would you say >90% of your code was written by LLMs?",
        default=existing.get("dominant_at") if isinstance(existing.get("dominant_at"), dict) else None,
    )
    initial_default = str(existing.get("primary_tool_initial", "") or "").strip().lower()
    current_default = str(existing.get("primary_tool_current", "") or "").strip().lower()
    primary_tool_initial = _prompt_enum(
        "Primary LLM coding tool when you started:",
        options=_LLM_TOOL_OPTIONS,
        default=initial_default or "none",
    )
    primary_tool_current = _prompt_enum(
        "Primary LLM coding tool now:",
        options=_LLM_TOOL_OPTIONS,
        default=current_default or primary_tool_initial,
    )
    return {
        "started_at": started_at,
        "dominant_at": dominant_at,
        "primary_tool_initial": primary_tool_initial,
        "primary_tool_current": primary_tool_current,
    }


def _week_start_iso_from_commit_iso(commit_iso: str) -> str:
    s = (commit_iso or "").strip()
    if not s:
        return ""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    d_utc = d.astimezone(dt.timezone.utc)
    date_utc = d_utc.date()
    week_start = date_utc - dt.timedelta(days=date_utc.weekday())
    return f"{week_start.isoformat()}T00:00:00Z"


def _upload_url_from_api_url(api_url: str) -> str:
    u = (api_url or "").strip().rstrip("/")
    if not u:
        return ""
    if u.endswith("/api/v1/uploads"):
        return u
    return u + "/api/v1/uploads"


def _display_name_url_from_api_url(api_url: str) -> str:
    u = (api_url or "").strip().rstrip("/")
    if not u:
        return ""
    if u.endswith("/api/v1/me/display-name"):
        return u
    if u.endswith("/api/v1/uploads"):
        u = u[: -len("/api/v1/uploads")].rstrip("/")
    return u + "/api/v1/me/display-name"


@dataclasses.dataclass(frozen=True)
class PublishInputs:
    publish: bool
    display_name: str
    publisher_token_path: Path
    upload_years: list[int]


def _is_valid_github_username(username: str) -> bool:
    s = normalize_github_username(username)
    if not s:
        return False
    if len(s) > 39:
        return False
    if not s[0].isalnum() or not s[-1].isalnum():
        return False
    for ch in s:
        if ch.isalnum() or ch == "-":
            continue
        return False
    return True


def _display_name_from_upload_cfg(upload_cfg: dict[str, object]) -> str:
    name = str(upload_cfg.get("display_name", "") or "").strip()
    if name:
        return name
    return str(upload_cfg.get("publisher", "") or "").strip()


def _prompt_display_name(*, upload_cfg: dict[str, object], config: dict[str, object]) -> str:
    existing = _display_name_from_upload_cfg(upload_cfg)
    mode_default = "custom" if existing else "pseudonym"
    mode = _prompt_choice("Public display name mode", choices=("pseudonym", "github", "custom"), default=mode_default)
    if mode == "pseudonym":
        return ""
    if mode == "github":
        me_gh = config.get("me_github_usernames")
        default_gh = ""
        if isinstance(me_gh, list) and me_gh:
            default_gh = str(me_gh[0] or "").strip()
        for _attempt in range(3):
            ans = _prompt_str("GitHub username (public)", default=default_gh).strip()
            if _is_valid_github_username(ans):
                return normalize_github_username(ans)
            print("Invalid GitHub username; try again.")
        return ""
    name = _prompt_str("Public display name (custom; blank for pseudonym)", default=existing).strip()
    return name


def _load_upload_cfg(config_path: Path) -> dict[str, object]:
    cfg = load_config(config_path)
    upload_cfg = dict((cfg.get("upload_config") or {}) if isinstance(cfg.get("upload_config"), dict) else {})
    if not upload_cfg and isinstance(cfg.get("publish"), dict):
        upload_cfg = dict(cfg.get("publish") or {})
    return upload_cfg


def _save_upload_api_url(config_path: Path, api_url: str) -> None:
    cfg = load_config(config_path)
    upload_cfg = dict((cfg.get("upload_config") or {}) if isinstance(cfg.get("upload_config"), dict) else {})
    upload_cfg["api_url"] = api_url.strip()
    cfg["upload_config"] = upload_cfg
    save_config(config_path, cfg)


def _upload_config_is_setup(upload_cfg: dict[str, object]) -> bool:
    token_path = str(upload_cfg.get("publisher_token_path", "") or "").strip()
    llm_coding = upload_cfg.get("llm_coding")
    if not token_path:
        return False
    if not isinstance(llm_coding, dict):
        return False
    return True


def _years_from_periods(periods: list[Period]) -> list[int]:
    years: set[int] = set()
    for p in periods:
        label = str(p.label or "").strip()
        if len(label) >= 4 and label[:4].isdigit():
            years.add(int(label[:4]))
    return sorted(years)


def _prompt_upload_years(*, upload_cfg: dict[str, object], report_periods: list[Period]) -> list[int]:
    existing = upload_cfg.get("upload_years")
    default_years: list[int] = []
    if isinstance(existing, list) and all(isinstance(y, int) or (isinstance(y, str) and str(y).isdigit()) for y in existing):
        default_years = sorted({int(y) for y in existing})
    if not default_years:
        default_years = _years_from_periods(report_periods)
    if 2025 not in default_years:
        default_years.append(2025)
        default_years = sorted(set(default_years))

    print("Upload data is always sent as full calendar years (Jan 1 .. Jan 1).")
    print("Reports may use different periods, so the uploaded dataset can differ from the generated report.")
    print("Note: 2025 is always included.")
    default_s = ",".join(str(y) for y in default_years)
    ans = _prompt_str("Years to include in upload (comma-separated YYYY)", default=default_s).strip()
    if not ans:
        years = default_years
    else:
        toks: list[str] = []
        for part in ans.replace(",", " ").split():
            part = part.strip()
            if part:
                toks.append(part)
        parsed: list[int] = []
        for t in toks:
            if not t.isdigit():
                parsed = []
                break
            y = int(t)
            if y < 1970 or y > 2100:
                parsed = []
                break
            parsed.append(y)
        years = sorted(set(parsed)) if parsed else default_years
    if 2025 not in years:
        years = sorted(set(years + [2025]))
    upload_cfg["upload_years"] = years
    return years


def collect_publish_inputs(*, args: object, config_path: Path, config: dict, report_periods: list[Period]) -> PublishInputs:
    upload_cfg = dict((config.get("upload_config") or {}) if isinstance(config.get("upload_config"), dict) else {})
    if not upload_cfg and isinstance(config.get("publish"), dict):
        upload_cfg = dict(config.get("publish") or {})

    default_publish = bool(upload_cfg.get("default_publish", False))
    arg_publish = getattr(args, "publish", None)
    if arg_publish == "yes":
        default_publish = True
    elif arg_publish == "no":
        default_publish = False

    print("What you get by publishing:")
    print("- Public profile: LLM tools proficiency summary (from your provided LLM coding info)")
    print("- Placement on top lists / leaderboards")
    print("- Visualizations: graphs for activity and LLM inflection score")
    print("")

    publish = _prompt_bool("Publish results to the public site?", default=default_publish)
    upload_cfg["default_publish"] = bool(publish)

    if not publish:
        config["upload_config"] = upload_cfg
        save_config(config_path, config)
        return PublishInputs(
            publish=False,
            display_name="",
            publisher_token_path=default_publisher_token_path(),
            upload_years=[],
        )

    upload_years = _prompt_upload_years(upload_cfg=upload_cfg, report_periods=report_periods)
    upload_cfg["upload_years"] = upload_years

    if _upload_config_is_setup(upload_cfg):
        print("Upload settings are already configured. Edit config.json (upload_config.*) to update them.")
        print("Continuing analysis. If publishing is enabled, the upload package is built after reports are generated.")

        display_name = str(getattr(args, "publisher", "") or "").strip() or _display_name_from_upload_cfg(upload_cfg)
        upload_cfg["display_name"] = display_name
        if "publisher" in upload_cfg and "display_name" in upload_cfg:
            upload_cfg["publisher"] = str(upload_cfg.get("display_name") or "")

        arg_token_path = getattr(args, "publisher_token_path", None)
        token_path_s = str(upload_cfg.get("publisher_token_path", "") or "").strip()
        token_path = Path(token_path_s).expanduser() if token_path_s else default_publisher_token_path()
        if arg_token_path is not None:
            token_path = Path(arg_token_path).expanduser()
            upload_cfg["publisher_token_path"] = str(token_path)
        if not str(upload_cfg.get("publisher_key_path", "") or "").strip():
            upload_cfg["publisher_key_path"] = str(default_publisher_key_path(token_path=token_path))
        config["upload_config"] = upload_cfg
        save_config(config_path, config)

        return PublishInputs(
            publish=True,
            display_name=display_name,
            publisher_token_path=token_path,
            upload_years=upload_years,
        )

    display_name = _prompt_display_name(upload_cfg=upload_cfg, config=config)

    arg_token_path = getattr(args, "publisher_token_path", None)
    token_default = str(upload_cfg.get("publisher_token_path", "") or "").strip()
    if arg_token_path is not None:
        token_default = str(Path(arg_token_path).expanduser())
    if not token_default:
        token_default = str(default_publisher_token_path())
    token_path = Path(_prompt_str("Publisher token path", default=token_default)).expanduser()

    upload_cfg["display_name"] = display_name
    upload_cfg["publisher"] = display_name
    upload_cfg["publisher_token_path"] = str(token_path)
    upload_cfg["publisher_key_path"] = str(default_publisher_key_path(token_path=token_path))
    upload_cfg["llm_coding"] = _prompt_llm_coding(upload_cfg)
    config["upload_config"] = upload_cfg
    save_config(config_path, config)

    return PublishInputs(
        publish=True,
        display_name=display_name,
        publisher_token_path=token_path,
        upload_years=upload_years,
    )


def build_upload_payload_from_results(
    *,
    periods: list[Period],
    results: list[RepoResult],
    publisher_kind: str,
    publisher_value: str,
    publisher_public_key: str,
    llm_coding: dict[str, object] | None = None,
) -> dict:
    generated_at = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    weekly_by_period: dict[str, list[dict[str, int | str]]] = {}
    year_totals: list[dict[str, object]] = []
    for p in periods:
        label = p.label
        weekly_excl = aggregate_weekly_me(results, label, include_bootstraps=False)
        weekly_tech_excl = aggregate_weekly_me_tech(results, label, include_bootstraps=False)

        active_repos_by_week: dict[str, int] = {}
        new_repos_by_week: dict[str, int] = {}
        for r in results:
            wmap = r.me_weekly_by_period_excl_bootstraps.get(label, {})
            for wk, st in wmap.items():
                if int(st.get("commits", 0)) <= 0:
                    continue
                active_repos_by_week[wk] = int(active_repos_by_week.get(wk, 0)) + 1

            if r.first_commit_iso:
                try:
                    first_date = dt.date.fromisoformat(r.first_commit_iso[:10])
                except ValueError:
                    first_date = None
                if first_date is not None and (p.start <= first_date < p.end):
                    wk0 = _week_start_iso_from_commit_iso(r.first_commit_iso)
                    if wk0:
                        new_repos_by_week[wk0] = int(new_repos_by_week.get(wk0, 0)) + 1

        def rows(w: dict[str, dict[str, int]], tech: dict[str, dict[str, dict[str, int]]]) -> list[dict[str, object]]:
            out: list[dict[str, int | str]] = []
            keys = sorted(set(w.keys()) | set(tech.keys()) | set(active_repos_by_week.keys()) | set(new_repos_by_week.keys()))
            for week_start in keys:
                st = w.get(week_start, {})
                techs = tech.get(week_start, {})
                tech_rows: list[dict[str, int | str]] = []
                for tname, tst in techs.items():
                    changed = int(tst.get("changed", 0))
                    commits = int(tst.get("commits", 0))
                    if changed <= 0 and commits <= 0:
                        continue
                    tech_rows.append(
                        {
                            "technology": tname,
                            "commits": commits,
                            "insertions": int(tst.get("insertions", 0)),
                            "deletions": int(tst.get("deletions", 0)),
                            "changed": changed,
                        }
                    )
                tech_rows.sort(key=lambda r: (-int(r.get("changed", 0)), str(r.get("technology", "")).lower()))
                out.append(
                    {
                        "week_start": week_start,
                        "commits": int(st.get("commits", 0)),
                        "insertions": int(st.get("insertions", 0)),
                        "deletions": int(st.get("deletions", 0)),
                        "changed": int(st.get("changed", 0)),
                        "repos_active": int(active_repos_by_week.get(week_start, 0)),
                        "repos_new": int(new_repos_by_week.get(week_start, 0)),
                        "technologies": tech_rows,
                    }
                )
            return out

        weekly_by_period[label] = rows(weekly_excl, weekly_tech_excl)

        year = int(label) if str(label).isdigit() else label
        commits = 0
        insertions = 0
        deletions = 0
        repos_total = len(results)
        repos_active = 0
        repos_new = 0
        for r in results:
            st = r.period_stats_excl_bootstraps.get(label)
            if st is None:
                continue
            commits += int(st.commits_me)
            insertions += int(st.insertions_me)
            deletions += int(st.deletions_me)
            if int(st.commits_me) > 0:
                repos_active += 1
            if r.first_commit_iso:
                try:
                    first_date = dt.date.fromisoformat(r.first_commit_iso[:10])
                except ValueError:
                    first_date = None
                if first_date is not None and (p.start <= first_date < p.end):
                    repos_new += 1
        year_totals.append(
            {
                "year": year,
                "repos_total": repos_total,
                "repos_active": repos_active,
                "repos_new": repos_new,
                "totals": {
                    "commits": commits,
                    "insertions": insertions,
                    "deletions": deletions,
                    "changed": insertions + deletions,
                },
            }
        )

    base = {
        "schema_version": "upload_package_v1",
        "generated_at": generated_at,
        "toolkit_version": __version__,
        "data_scope": "me",
        "repos_total": len(results),
        "publisher": {"kind": publisher_kind, "value": publisher_value, "public_key": str(publisher_public_key or "")},
        "periods": [{"label": p.label, "start": p.start_iso, "end": p.end_iso} for p in periods],
        "year_totals": year_totals,
        "weekly": {
            "definition": {
                "bucket": "week_start_monday_00_00_00Z",
                "timestamp_source": "author_time_%aI_converted_to_utc",
                "technology_kind": "language_for_path",
            },
            "series_by_period": weekly_by_period,
        },
    }
    if isinstance(llm_coding, dict) and llm_coding:
        base["llm_coding"] = llm_coding
    return base


def publish_with_wizard(
    *,
    report_dir: Path,
    upload_periods: list[Period],
    results: list[RepoResult],
    inputs: PublishInputs,
    config_path: Path,
    args: object | None = None,
) -> None:
    if not inputs.publish:
        return

    token = _ensure_publisher_token_with_ui(inputs.publisher_token_path)
    upload_cfg = _load_upload_cfg(config_path)
    key_path = _publisher_key_path_from_upload_cfg(upload_cfg=upload_cfg, token_path=inputs.publisher_token_path)
    public_key = _ensure_publisher_keypair_with_ui(key_path)

    publisher_kind = "pseudonym"
    publisher_value = pseudonym_for_token(token)

    llm_coding = upload_cfg.get("llm_coding") if isinstance(upload_cfg.get("llm_coding"), dict) else None
    ca_bundle_path = str(upload_cfg.get("ca_bundle_path", "") or "").strip()
    override_ca_bundle = str(getattr(args, "ca_bundle", "") or "").strip() if args is not None else ""
    if override_ca_bundle:
        ca_bundle_path = override_ca_bundle

    payload = build_upload_payload_from_results(
        periods=upload_periods,
        results=results,
        publisher_kind=publisher_kind,
        publisher_value=publisher_value,
        publisher_public_key=public_key,
        llm_coding=llm_coding,
    )
    payload_bytes = canonical_json_bytes(payload)
    sha = hashlib.sha256(payload_bytes).hexdigest()

    out_path = report_dir / "json" / "upload_package_v1.json"
    out_path.write_bytes(payload_bytes)
    _print_upload_summary(payload=payload, payload_path=out_path, payload_sha256=sha)

    mode = str(upload_cfg.get("automatic_upload", "confirm") or "confirm").strip().lower()
    if mode in ("no", "never", "false", "0"):
        return
    default_upload = mode in ("yes", "always", "true", "1")
    if not _prompt_bool(f"Upload {out_path.name} now?", default=default_upload):
        return

    override = str(getattr(args, "upload_url", "") or "").strip() if args is not None else ""
    if override:
        if override.rstrip("/").endswith("/api/v1/uploads"):
            upload_url = override.rstrip("/")
            api_url = upload_url[: -len("/api/v1/uploads")]
        else:
            api_url = override
            upload_url = _upload_url_from_api_url(api_url)
        if api_url:
            _save_upload_api_url(config_path, api_url)
    else:
        api_url = str(upload_cfg.get("api_url", "") or "").strip()
        if not api_url:
            api_url = _prompt_str("Upload server api_url", default="http://localhost:3220").strip()
            if not api_url:
                raise RuntimeError("server api_url is required for publishing")
            _save_upload_api_url(config_path, api_url)
        upload_url = _upload_url_from_api_url(api_url)
    if not upload_url:
        raise RuntimeError("upload_url is required for publishing")

    _print_api_call(method="POST", url=upload_url, payload_path=out_path)
    print("Uploading...")
    upload_package_v1(
        upload_url=upload_url,
        publisher_token=token,
        payload_bytes=payload_bytes,
        payload_sha256=sha,
        timeout_s=30,
        ca_bundle_path=ca_bundle_path,
    )
    print("Upload complete.")

    display_name = (inputs.display_name or "").strip()
    if not display_name:
        display_name = pseudonym_for_token(token)
    _print_api_call(
        method="POST",
        url=_display_name_url_from_api_url(api_url),
        payload={"display_name": display_name},
    )
    update_display_name_v1(
        api_url=api_url,
        publisher_token=token,
        display_name=display_name,
        timeout_s=30,
        ca_bundle_path=ca_bundle_path,
    )
    print(f"Display name updated: {display_name}")


def json_preview(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def json_compact(data: object) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _print_api_call(*, method: str, url: str, payload: object | None = None, payload_path: Path | None = None) -> None:
    m = (method or "").strip().upper() or "GET"
    u = str(url or "").strip()
    if not u:
        return
    print(f"API {m} {u}")
    if payload_path is not None:
        print(f"Payload: {payload_path}")
        return
    if payload is not None:
        s = json_compact(payload)
        if len(s) <= 800:
            print(f"Payload: {s}")
        else:
            print(f"Payload: {s[:797]}...")

def _ensure_publisher_token_with_ui(path: Path) -> str:
    p = Path(path).expanduser()
    existed = p.exists()
    print(f"Publisher token (local secret): {p}")
    if existed:
        print("Using existing token file (not derived from SSH keys or other private keys).")
    else:
        print("Generating a new random token locally (not derived from SSH keys or other private keys).")
    print("The token is sent only as X-Publisher-Token; delete the file to regenerate.")
    return ensure_publisher_token(p)


def _ensure_publisher_keypair_with_ui(private_key_path: Path) -> str:
    p = Path(private_key_path).expanduser()
    existed = p.exists()
    print(f"Publisher key (Ed25519): {p}")
    if existed:
        print("Using existing keypair; the public key is included in uploads.")
    else:
        print("Generating a new Ed25519 keypair locally; only the public key is uploaded.")
    pub_line = ensure_publisher_ed25519_keypair(p)
    print(pub_line)
    return pub_line


def _upload_summary_lines(*, payload: dict, payload_path: Path, payload_sha256: str) -> list[str]:
    repos_total = int(payload.get("repos_total", 0) or 0)
    periods = payload.get("periods") if isinstance(payload.get("periods"), list) else []
    year_labels = [str(p.get("label")) for p in periods if isinstance(p, dict) and p.get("label")]
    year_totals = payload.get("year_totals") if isinstance(payload.get("year_totals"), list) else []

    weekly_counts: dict[str, int] = {}
    weekly_min: dict[str, str] = {}
    weekly_max: dict[str, str] = {}
    weekly = payload.get("weekly") if isinstance(payload.get("weekly"), dict) else {}
    series_by_period = weekly.get("series_by_period") if isinstance(weekly.get("series_by_period"), dict) else {}
    for label, rows in series_by_period.items():
        if not isinstance(label, str) or not isinstance(rows, list):
            continue
        weekly_counts[label] = len(rows)
        starts = [r.get("week_start") for r in rows if isinstance(r, dict) and isinstance(r.get("week_start"), str)]
        if starts:
            weekly_min[label] = min(starts)
            weekly_max[label] = max(starts)

    lines: list[str] = []
    lines.append("Upload package saved at:")
    lines.append(str(payload_path))
    lines.append(f"Payload SHA-256: {payload_sha256}")
    lines.append("")
    lines.append("This will upload:")
    lines.append("- Your own activity only (data_scope=me)")
    lines.append("- No repo identifiers/URLs")
    lines.append("- Bootstrap commits excluded")
    if year_labels:
        lines.append(f"- Years: {', '.join(year_labels)} (uploads are full calendar years)")
    lines.append(f"- Repos analyzed: {repos_total}")

    if year_totals:
        lines.append("")
        lines.append("Per-year summary:")
        for row in year_totals:
            if not isinstance(row, dict):
                continue
            year = row.get("year")
            totals = row.get("totals") if isinstance(row.get("totals"), dict) else {}
            commits = int(totals.get("commits", 0) or 0)
            changed = int(totals.get("changed", 0) or 0)
            repos_active = int(row.get("repos_active", 0) or 0)
            repos_new = int(row.get("repos_new", 0) or 0)
            label = str(year)
            wk_n = weekly_counts.get(label, 0)
            wk_range = ""
            if label in weekly_min and label in weekly_max:
                wk_range = f" ({weekly_min[label]}..{weekly_max[label]})"
            lines.append(f"- {label}: commits {fmt_int(commits)}, changed {fmt_int(changed)}, repos_active {repos_active}, repos_new {repos_new}, weeks {wk_n}{wk_range}")

    return lines


def _print_upload_summary(*, payload: dict, payload_path: Path, payload_sha256: str) -> None:
    print("")
    print("┌──────────────────────── Upload Preview ────────────────────────┐")
    for line in _upload_summary_lines(payload=payload, payload_path=payload_path, payload_sha256=payload_sha256):
        print(line)
    print("└─────────────────────────────────────────────────────────────────┘")


def set_profile_display_name(
    *,
    config_path: Path,
    display_name: str = "",
    github_username: str = "",
    use_pseudonym: bool = False,
    api_url_override: str = "",
    ca_bundle_path_override: str = "",
) -> int:
    upload_cfg = _load_upload_cfg(config_path)
    api_url = str(api_url_override or upload_cfg.get("api_url", "") or "").strip()
    if not api_url:
        print("Error: upload_config.api_url is required")
        return 2

    token_path_s = str(upload_cfg.get("publisher_token_path", "") or "").strip()
    token_path = Path(token_path_s).expanduser() if token_path_s else default_publisher_token_path()
    token = _ensure_publisher_token_with_ui(token_path)

    ca_bundle_path = str(upload_cfg.get("ca_bundle_path", "") or "").strip()
    if str(ca_bundle_path_override or "").strip():
        ca_bundle_path = str(ca_bundle_path_override or "").strip()

    if use_pseudonym:
        name = pseudonym_for_token(token)
    elif github_username.strip():
        if not _is_valid_github_username(github_username):
            print("Error: invalid GitHub username")
            return 2
        name = normalize_github_username(github_username)
    else:
        name = (display_name or "").strip()
        if not name:
            print("Error: display_name is required (or use --pseudonym)")
            return 2

    try:
        _print_api_call(
            method="POST",
            url=_display_name_url_from_api_url(api_url),
            payload={"display_name": name},
        )
        resp = update_display_name_v1(
            api_url=api_url,
            publisher_token=token,
            display_name=name,
            timeout_s=30,
            ca_bundle_path=ca_bundle_path,
        )
    except RuntimeError as e:
        msg = str(e).strip()
        print(msg or "Error: display-name update failed")
        return 2

    out_name = str(resp.get("display_name", "") or "").strip() or name
    slug = str(resp.get("slug", "") or "").strip()
    if slug:
        print(f"Display name updated: {out_name} (slug={slug})")
    else:
        print(f"Display name updated: {out_name}")
    return 0


def upload_existing_report_dir(
    *,
    report_dir: Path,
    config_path: Path,
    upload_url_override: str = "",
    ca_bundle_path_override: str = "",
    assume_yes: bool = False,
) -> int:
    report_dir = report_dir.resolve()
    payload_path = report_dir / "json" / "upload_package_v1.json"
    if not payload_path.exists():
        print(f"Error: missing payload file: {payload_path}")
        return 2

    meta_path = report_dir / "json" / "run_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        include_merges = bool(meta.get("include_merges", False))
        include_bootstraps = bool(meta.get("include_bootstraps", False))
        dedupe = str(meta.get("dedupe", "remote") or "remote")
        blocked: list[str] = []
        if include_merges:
            blocked.append("--include-merges")
        if include_bootstraps:
            blocked.append("--include-bootstraps")
        if dedupe != "remote":
            blocked.append(f"--dedupe {dedupe}")
        if blocked:
            print("Upload disabled for this report (unsupported flags: " + ", ".join(blocked) + ").")
            return 2

    try:
        payload_obj = json.loads(payload_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error: failed to parse payload JSON: {e}")
        return 2

    if not isinstance(payload_obj, dict):
        print("Error: upload payload must be a JSON object")
        return 2
    if "repos" in payload_obj or "privacy" in payload_obj:
        print("Error: upload payload includes repo/privacy fields; refusing to upload")
        return 2
    if str(payload_obj.get("data_scope", "") or "").strip().lower() != "me":
        print("Error: upload payload must declare data_scope='me'; refusing to upload")
        return 2
    if not isinstance(payload_obj.get("year_totals"), list):
        print("Error: upload payload missing year_totals; refusing to upload")
        return 2
    weekly = payload_obj.get("weekly")
    if not isinstance(weekly, dict):
        print("Error: upload payload missing weekly; refusing to upload")
        return 2
    series_by_period = weekly.get("series_by_period")
    if not isinstance(series_by_period, dict):
        print("Error: upload payload missing weekly.series_by_period; refusing to upload")
        return 2
    for k, v in series_by_period.items():
        if not isinstance(k, str) or not isinstance(v, list):
            print("Error: upload payload weekly.series_by_period must map period label -> list; refusing to upload")
            return 2

    upload_cfg = _load_upload_cfg(config_path)
    token_path_s = str(upload_cfg.get("publisher_token_path", "") or "").strip()
    token_path = Path(token_path_s).expanduser() if token_path_s else default_publisher_token_path()
    token = _ensure_publisher_token_with_ui(token_path)
    key_path = _publisher_key_path_from_upload_cfg(upload_cfg=upload_cfg, token_path=token_path)
    public_key = _ensure_publisher_keypair_with_ui(key_path)
    ca_bundle_path = str(upload_cfg.get("ca_bundle_path", "") or "").strip()
    if str(ca_bundle_path_override or "").strip():
        ca_bundle_path = str(ca_bundle_path_override or "").strip()

    publisher = payload_obj.get("publisher")
    if not isinstance(publisher, dict):
        print("Error: upload payload missing publisher object; refusing to upload")
        return 2
    if not str(publisher.get("public_key", "") or "").strip():
        publisher["public_key"] = public_key
        payload_obj["publisher"] = publisher
        try:
            payload_path.write_bytes(canonical_json_bytes(payload_obj))
        except Exception:
            pass

    payload_bytes = canonical_json_bytes(payload_obj)
    sha = hashlib.sha256(payload_bytes).hexdigest()

    _print_upload_summary(payload=payload_obj, payload_path=payload_path, payload_sha256=sha)

    mode = str(upload_cfg.get("automatic_upload", "confirm") or "confirm").strip().lower()
    if assume_yes:
        mode = "always"
    if mode in ("no", "never", "false", "0"):
        return 0
    default_upload = mode in ("yes", "always", "true", "1")
    if not assume_yes:
        if not _prompt_bool(f"Upload {payload_path.name} now?", default=default_upload):
            return 0

    override = str(upload_url_override or "").strip()
    if override:
        if override.rstrip("/").endswith("/api/v1/uploads"):
            upload_url = override.rstrip("/")
            api_url = upload_url[: -len("/api/v1/uploads")]
        else:
            api_url = override
            upload_url = _upload_url_from_api_url(api_url)
        if api_url:
            _save_upload_api_url(config_path, api_url)
    else:
        api_url = str(upload_cfg.get("api_url", "") or "").strip()
        if not api_url:
            api_url = _prompt_str("Upload server api_url", default="http://localhost:3220").strip()
            if not api_url:
                print("Error: upload_config.api_url is required for uploading")
                return 2
            _save_upload_api_url(config_path, api_url)
        upload_url = _upload_url_from_api_url(api_url)

    if not upload_url:
        print("Error: upload_url is required for uploading")
        return 2

    try:
        _print_api_call(method="POST", url=upload_url, payload_path=payload_path)
        print("Uploading...")
        upload_package_v1(
            upload_url=upload_url,
            publisher_token=token,
            payload_bytes=payload_bytes,
            payload_sha256=sha,
            timeout_s=30,
            ca_bundle_path=ca_bundle_path,
        )
        print("Upload complete.")
    except RuntimeError as e:
        msg = str(e).strip()
        print("")
        print("Upload failed.")
        if msg:
            print(msg)
        if "privacy.mode" in msg:
            print("Hint: your server appears to expect an older upload schema; update the backend to accept the current payload format.")
        return 2
    return 0


def verify_github_username(
    *,
    config_path: Path,
    github_username: str,
    api_url_override: str = "",
    ca_bundle_path_override: str = "",
) -> int:
    upload_cfg = _load_upload_cfg(config_path)
    api_url = str(api_url_override or upload_cfg.get("api_url", "") or "").strip()
    if not api_url:
        print("Error: upload_config.api_url is required")
        return 2

    token_path_s = str(upload_cfg.get("publisher_token_path", "") or "").strip()
    token_path = Path(token_path_s).expanduser() if token_path_s else default_publisher_token_path()
    token = _ensure_publisher_token_with_ui(token_path)

    key_path = _publisher_key_path_from_upload_cfg(upload_cfg=upload_cfg, token_path=token_path)
    public_key = _ensure_publisher_keypair_with_ui(key_path)

    ca_bundle_path = str(upload_cfg.get("ca_bundle_path", "") or "").strip()
    if str(ca_bundle_path_override or "").strip():
        ca_bundle_path = str(ca_bundle_path_override or "").strip()

    username = normalize_github_username(github_username)
    if not _is_valid_github_username(username):
        print("Error: invalid GitHub username")
        return 2

    print("")
    print("We verify by checking that your toolkit key is listed on your GitHub account (no OAuth, no repo access).")
    print("Add this key at: GitHub → Settings → SSH and GPG keys → New SSH key:")
    print(public_key)
    print("")

    try:
        _print_api_call(
            method="POST",
            url=str(api_url).rstrip("/") + "/api/v1/me/github/verify/challenge",
            payload={"github_username": username},
        )
        ch = github_verify_challenge_v1(
            api_url=api_url,
            publisher_token=token,
            github_username=username,
            timeout_s=30,
            ca_bundle_path=ca_bundle_path,
        )
        challenge = str(ch.get("challenge", "") or "").strip()
        message_to_sign = str(ch.get("message_to_sign", "") or "")
        if not challenge or not message_to_sign:
            raise RuntimeError("github-verify challenge response missing fields")

        sig_b64 = sign_publisher_ed25519_message_base64(private_key_path=key_path, message_to_sign=message_to_sign)
        _print_api_call(
            method="POST",
            url=str(api_url).rstrip("/") + "/api/v1/me/github/verify/confirm",
            payload={"github_username": username, "challenge": challenge, "signature": sig_b64},
        )
        resp = github_verify_confirm_v1(
            api_url=api_url,
            publisher_token=token,
            github_username=username,
            challenge=challenge,
            signature=sig_b64,
            timeout_s=30,
            ca_bundle_path=ca_bundle_path,
        )
    except RuntimeError as e:
        msg = str(e).strip()
        print(msg or "Error: GitHub verification failed")
        if "HTTP 404" in msg:
            print("Hint: upload once first to create a profile, then retry verification.")
        return 2

    if bool(resp.get("verified", False)):
        verified_at = str(resp.get("verified_at", "") or "").strip()
        if verified_at:
            print(f"GitHub username verified: {username} (verified_at={verified_at})")
        else:
            print(f"GitHub username verified: {username}")
        return 0

    print("GitHub verification not confirmed; retry after adding the SSH key to GitHub.")
    return 2
