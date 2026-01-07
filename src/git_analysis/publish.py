from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from . import __version__
from .analysis_aggregate import aggregate_weekly
from .analysis_periods import Period
from .config import load_config, save_config
from .models import RepoResult
from .upload_package_v1 import build_upload_package_v1, canonical_json_bytes, ensure_publisher_token, upload_package_v1


def default_publisher_token_path() -> Path:
    return Path.home() / ".config" / "git-analysis" / "publisher_token"


def pseudonym_for_token(token: str) -> str:
    h = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"anon-{h[:12]}"


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


def _upload_url_from_api_url(api_url: str) -> str:
    u = (api_url or "").strip().rstrip("/")
    if not u:
        return ""
    if u.endswith("/api/v1/uploads"):
        return u
    return u + "/api/v1/uploads"


@dataclasses.dataclass(frozen=True)
class PublishInputs:
    publish: bool
    publisher: str
    repo_url_privacy: str
    publisher_token_path: Path


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
    repo_priv = str(upload_cfg.get("repo_url_privacy", "") or "").strip().lower()
    llm_coding = upload_cfg.get("llm_coding")
    if not token_path:
        return False
    if repo_priv not in ("none", "public_only", "all"):
        return False
    if not isinstance(llm_coding, dict):
        return False
    return True


def collect_publish_inputs(*, args: object, config_path: Path, config: dict) -> PublishInputs:
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
    print("- Placement on top lists / leaderboards (when opted in)")
    print("- Visualizations: graphs for commits and code-churn history over time")
    print("")

    publish = _prompt_bool("Publish results to the public site?", default=default_publish)
    upload_cfg["default_publish"] = bool(publish)

    if not publish:
        config["upload_config"] = upload_cfg
        save_config(config_path, config)
        return PublishInputs(publish=False, publisher="", repo_url_privacy="none", publisher_token_path=default_publisher_token_path())

    if _upload_config_is_setup(upload_cfg):
        print("Upload settings are already configured. Edit config.json (upload_config.*) to update them.")
        print("Continuing analysis. If publishing is enabled, the upload package is built after reports are generated.")

        publisher = str(getattr(args, "publisher", "") or "").strip()
        if not publisher:
            publisher = str(upload_cfg.get("publisher", "") or "").strip()

        repo_url_privacy = str(upload_cfg.get("repo_url_privacy", "none") or "none").strip().lower()

        arg_token_path = getattr(args, "publisher_token_path", None)
        token_path_s = str(upload_cfg.get("publisher_token_path", "") or "").strip()
        token_path = Path(token_path_s).expanduser() if token_path_s else default_publisher_token_path()
        if arg_token_path is not None:
            token_path = Path(arg_token_path).expanduser()
            upload_cfg["publisher_token_path"] = str(token_path)
        config["upload_config"] = upload_cfg
        save_config(config_path, config)

        return PublishInputs(publish=True, publisher=publisher, repo_url_privacy=repo_url_privacy, publisher_token_path=token_path)

    arg_publisher = str(getattr(args, "publisher", "") or "").strip()
    publisher_default = arg_publisher or str(upload_cfg.get("publisher", "") or "").strip()
    publisher = _prompt_str("Public identity (blank for pseudonym)", default=publisher_default).strip()

    arg_priv = str(getattr(args, "repo_url_privacy", "") or "").strip().lower()
    priv_default = arg_priv or str(upload_cfg.get("repo_url_privacy", "none") or "none").strip().lower()
    repo_url_privacy = _prompt_choice("Repo URL privacy mode", choices=("none", "public_only", "all"), default=priv_default)

    arg_token_path = getattr(args, "publisher_token_path", None)
    token_default = str(upload_cfg.get("publisher_token_path", "") or "").strip()
    if arg_token_path is not None:
        token_default = str(Path(arg_token_path).expanduser())
    if not token_default:
        token_default = str(default_publisher_token_path())
    token_path = Path(_prompt_str("Publisher token path", default=token_default)).expanduser()

    upload_cfg["publisher"] = publisher
    upload_cfg["repo_url_privacy"] = repo_url_privacy
    upload_cfg["publisher_token_path"] = str(token_path)
    upload_cfg["llm_coding"] = _prompt_llm_coding(upload_cfg)
    config["upload_config"] = upload_cfg
    save_config(config_path, config)

    return PublishInputs(publish=True, publisher=publisher, repo_url_privacy=repo_url_privacy, publisher_token_path=token_path)


def build_upload_payload_from_results(
    *,
    periods: list[Period],
    results: list[RepoResult],
    publisher_kind: str,
    publisher_value: str,
    privacy_mode: str,
    llm_coding: dict[str, object] | None = None,
) -> dict:
    generated_at = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    weekly_by_period: dict[str, dict[str, list[dict[str, int | str]]]] = {}
    for p in periods:
        label = p.label
        weekly_excl = aggregate_weekly(results, label, include_bootstraps=False)
        weekly_boot = aggregate_weekly(results, label, include_bootstraps=False, bootstraps_only=True)
        weekly_incl = aggregate_weekly(results, label, include_bootstraps=True)

        def rows(w: dict[str, dict[str, int]]) -> list[dict[str, int | str]]:
            out: list[dict[str, int | str]] = []
            for week_start, st in sorted(w.items(), key=lambda kv: kv[0]):
                out.append(
                    {
                        "week_start": week_start,
                        "commits": int(st.get("commits", 0)),
                        "insertions": int(st.get("insertions", 0)),
                        "deletions": int(st.get("deletions", 0)),
                        "changed": int(st.get("changed", 0)),
                    }
                )
            return out

        weekly_by_period[label] = {
            "excl_bootstraps": rows(weekly_excl),
            "bootstraps": rows(weekly_boot),
            "including_bootstraps": rows(weekly_incl),
        }

    base = {
        "schema_version": "upload_package_v1",
        "generated_at": generated_at,
        "toolkit_version": __version__,
        "publisher": {"kind": publisher_kind, "value": publisher_value},
        "periods": [{"label": p.label, "start": p.start_iso, "end": p.end_iso} for p in periods],
        "weekly": {
            "definition": {
                "bucket": "week_start_monday_00_00_00Z",
                "timestamp_source": "author_time_%aI_converted_to_utc",
            },
            "series_by_period": weekly_by_period,
        },
    }
    if isinstance(llm_coding, dict) and llm_coding:
        base["llm_coding"] = llm_coding
    repos = [{"repo_key": r.key, "remote_canonical": r.remote_canonical} for r in results]
    return build_upload_package_v1(base=base, repos=repos, privacy_mode=privacy_mode)


def publish_with_wizard(
    *,
    report_dir: Path,
    periods: list[Period],
    results: list[RepoResult],
    inputs: PublishInputs,
    config_path: Path,
    args: object | None = None,
) -> None:
    if not inputs.publish:
        return

    token = ensure_publisher_token(inputs.publisher_token_path)

    pub = (inputs.publisher or "").strip()
    publisher_kind = "pseudonym"
    publisher_value = pseudonym_for_token(token)
    if pub:
        publisher_kind = "user_provided"
        publisher_value = pub

    priv = (inputs.repo_url_privacy or "").strip().lower()
    if priv not in ("none", "public_only", "all"):
        priv = "none"

    upload_cfg = _load_upload_cfg(config_path)
    llm_coding = upload_cfg.get("llm_coding") if isinstance(upload_cfg.get("llm_coding"), dict) else None

    payload = build_upload_payload_from_results(
        periods=periods,
        results=results,
        publisher_kind=publisher_kind,
        publisher_value=publisher_value,
        privacy_mode=priv,
        llm_coding=llm_coding,
    )
    payload_bytes = canonical_json_bytes(payload)
    sha = hashlib.sha256(payload_bytes).hexdigest()

    preview = dict(payload)
    preview["publisher_token_hint"] = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    exposed = [r.get("remote_canonical") for r in (payload.get("repos") or []) if isinstance(r, dict) and r.get("remote_canonical")]
    print(json_preview(preview))
    print(f"\nPayload SHA-256: {sha}")

    out_path = report_dir / "json" / "upload_package_v1.json"
    out_path.write_bytes(payload_bytes)
    print(f"Full payload written to: {out_path}")

    if exposed:
        print("Exposed repo URLs:")
        for u in exposed:
            print(f"- {u}")

    mode = str(upload_cfg.get("automatic_upload", "confirm") or "confirm").strip().lower()
    if mode in ("no", "never", "false", "0"):
        return
    if mode not in ("yes", "always", "true", "1"):
        if not _prompt_bool("Upload now?", default=False):
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

    upload_package_v1(
        upload_url=upload_url,
        publisher_token=token,
        payload_bytes=payload_bytes,
        payload_sha256=sha,
        timeout_s=30,
    )


def json_preview(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def upload_existing_report_dir(
    *,
    report_dir: Path,
    config_path: Path,
    upload_url_override: str = "",
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

    payload_bytes = canonical_json_bytes(payload_obj)
    sha = hashlib.sha256(payload_bytes).hexdigest()

    upload_cfg = _load_upload_cfg(config_path)
    token_path_s = str(upload_cfg.get("publisher_token_path", "") or "").strip()
    token_path = Path(token_path_s).expanduser() if token_path_s else default_publisher_token_path()
    token = ensure_publisher_token(token_path)

    preview = dict(payload_obj) if isinstance(payload_obj, dict) else {"payload": payload_obj}
    preview["publisher_token_hint"] = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    print(json_preview(preview))
    print(f"\nPayload SHA-256: {sha}")
    print(f"Full payload read from: {payload_path}")

    exposed = []
    if isinstance(payload_obj, dict):
        exposed = [
            r.get("remote_canonical")
            for r in (payload_obj.get("repos") or [])
            if isinstance(r, dict) and r.get("remote_canonical")
        ]
    if exposed:
        print("Exposed repo URLs:")
        for u in exposed:
            print(f"- {u}")

    mode = str(upload_cfg.get("automatic_upload", "confirm") or "confirm").strip().lower()
    if assume_yes:
        mode = "always"
    if mode in ("no", "never", "false", "0"):
        return 0
    if mode not in ("yes", "always", "true", "1"):
        if not _prompt_bool("Upload now?", default=False):
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

    upload_package_v1(
        upload_url=upload_url,
        publisher_token=token,
        payload_bytes=payload_bytes,
        payload_sha256=sha,
        timeout_s=30,
    )
    return 0
