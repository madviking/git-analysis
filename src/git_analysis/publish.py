from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path

from . import __version__
from .analysis_aggregate import aggregate_weekly
from .analysis_periods import Period
from .config import save_config
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


def _server_json_path(config_path: Path) -> Path:
    candidate = config_path.resolve().parent / "server.json"
    if candidate.exists():
        return candidate
    return Path("server.json").resolve()


def _load_server_api_url(server_path: Path) -> str:
    if not server_path.exists():
        return ""
    try:
        data = json.loads(server_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    api_url = str((data or {}).get("api_url", "")).strip()
    return api_url


def _save_server_api_url(server_path: Path, api_url: str) -> None:
    server_path.parent.mkdir(parents=True, exist_ok=True)
    server_path.write_text(json.dumps({"api_url": api_url.strip()}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def collect_publish_inputs(*, args: object, config_path: Path, config: dict) -> PublishInputs:
    publish_cfg = dict((config.get("publish") or {}) if isinstance(config.get("publish"), dict) else {})

    default_publish = bool(publish_cfg.get("default_publish", False))
    arg_publish = getattr(args, "publish", None)
    if arg_publish == "yes":
        default_publish = True
    elif arg_publish == "no":
        default_publish = False

    publish = _prompt_bool("Publish results to the public site?", default=default_publish)
    publish_cfg["default_publish"] = bool(publish)

    if not publish:
        config["publish"] = publish_cfg
        save_config(config_path, config)
        return PublishInputs(publish=False, publisher="", repo_url_privacy="none", publisher_token_path=default_publisher_token_path())

    arg_publisher = str(getattr(args, "publisher", "") or "").strip()
    publisher_default = arg_publisher or str(publish_cfg.get("publisher", "") or "").strip()
    publisher = _prompt_str("Public identity (blank for pseudonym)", default=publisher_default).strip()

    arg_priv = str(getattr(args, "repo_url_privacy", "") or "").strip().lower()
    priv_default = arg_priv or str(publish_cfg.get("repo_url_privacy", "none") or "none").strip().lower()
    repo_url_privacy = _prompt_choice("Repo URL privacy mode", choices=("none", "public_only", "all"), default=priv_default)

    arg_token_path = getattr(args, "publisher_token_path", None)
    token_default = str(publish_cfg.get("publisher_token_path", "") or "").strip()
    if arg_token_path is not None:
        token_default = str(Path(arg_token_path).expanduser())
    if not token_default:
        token_default = str(default_publisher_token_path())
    token_path = Path(_prompt_str("Publisher token path", default=token_default)).expanduser()

    publish_cfg["publisher"] = publisher
    publish_cfg["repo_url_privacy"] = repo_url_privacy
    publish_cfg["publisher_token_path"] = str(token_path)
    config["publish"] = publish_cfg
    save_config(config_path, config)

    return PublishInputs(publish=True, publisher=publisher, repo_url_privacy=repo_url_privacy, publisher_token_path=token_path)


def build_upload_payload_from_results(
    *,
    periods: list[Period],
    results: list[RepoResult],
    publisher_kind: str,
    publisher_value: str,
    privacy_mode: str,
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

    payload = build_upload_payload_from_results(
        periods=periods,
        results=results,
        publisher_kind=publisher_kind,
        publisher_value=publisher_value,
        privacy_mode=priv,
    )
    payload_bytes = canonical_json_bytes(payload)
    sha = hashlib.sha256(payload_bytes).hexdigest()

    preview = dict(payload)
    preview["publisher_token_hint"] = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    exposed = [r.get("remote_canonical") for r in (payload.get("repos") or []) if isinstance(r, dict) and r.get("remote_canonical")]
    print(json_preview(preview))
    print(f"\nPayload SHA-256: {sha}")
    if exposed:
        print("Exposed repo URLs:")
        for u in exposed:
            print(f"- {u}")

    if not _prompt_bool("Upload now?", default=False):
        return

    server_path = _server_json_path(config_path)
    override = str(getattr(args, "upload_url", "") or "").strip() if args is not None else ""
    if override:
        if override.rstrip("/").endswith("/api/v1/uploads"):
            upload_url = override.rstrip("/")
            api_url = upload_url[: -len("/api/v1/uploads")]
        else:
            api_url = override
            upload_url = _upload_url_from_api_url(api_url)
        if api_url:
            _save_server_api_url(server_path, api_url)
    else:
        api_url = _load_server_api_url(server_path)
        if not api_url:
            api_url = _prompt_str("Server api_url (stored in server.json)", default="http://localhost:3220").strip()
            if not api_url:
                raise RuntimeError("server api_url is required for publishing")
            _save_server_api_url(server_path, api_url)
        upload_url = _upload_url_from_api_url(api_url)
    if not upload_url:
        raise RuntimeError("upload_url is required for publishing")

    out_path = report_dir / "json" / "upload_package_v1.json"
    out_path.write_bytes(payload_bytes)
    upload_package_v1(
        upload_url=upload_url,
        publisher_token=token,
        payload_bytes=payload_bytes,
        payload_sha256=sha,
        timeout_s=30,
    )


def json_preview(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
