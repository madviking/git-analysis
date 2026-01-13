from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import secrets
import shutil
import ssl
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def canonical_json_bytes(data: object) -> bytes:
    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def ensure_publisher_token(path: Path) -> str:
    p = Path(path).expanduser()
    if p.exists():
        token = p.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(f"publisher token file is empty: {p}")
        return token

    p.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    p.write_text(token + "\n", encoding="utf-8")
    if os.name == "posix":
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
    return token


def ensure_publisher_ed25519_keypair(private_key_path: Path) -> str:
    """
    Ensure an unencrypted OpenSSH Ed25519 keypair exists at:
      - private: `private_key_path`
      - public:  `private_key_path + ".pub"`

    Returns the public key line in `authorized_keys` format without comment:
      `ssh-ed25519 <base64>`
    """
    if shutil.which("ssh-keygen") is None:
        raise RuntimeError("ssh-keygen is required to generate publisher Ed25519 keys")

    priv = Path(private_key_path).expanduser()
    pub = Path(str(priv) + ".pub")
    if priv.exists():
        if not pub.exists():
            pub.parent.mkdir(parents=True, exist_ok=True)
            out = subprocess.run(
                ["ssh-keygen", "-y", "-f", str(priv)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            pub.write_text(out + "\n", encoding="utf-8")
        return _normalize_ed25519_public_key_line(pub.read_text(encoding="utf-8", errors="replace"))

    priv.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(priv), "-q"],
        check=True,
        capture_output=True,
        text=True,
    )
    if not pub.exists():
        raise RuntimeError(f"ssh-keygen did not create expected public key file: {pub}")
    return _normalize_ed25519_public_key_line(pub.read_text(encoding="utf-8", errors="replace"))


def _normalize_ed25519_public_key_line(s: str) -> str:
    parts = (s or "").strip().split()
    if len(parts) < 2:
        raise RuntimeError("invalid ed25519 public key file (expected OpenSSH public key line)")
    if parts[0] != "ssh-ed25519":
        raise RuntimeError(f"invalid public key type (expected ssh-ed25519): {parts[0]!r}")
    return f"{parts[0]} {parts[1]}"


def sign_publisher_ed25519_message_base64(*, private_key_path: Path, message_to_sign: str) -> str:
    """
    Returns a standard-base64 Ed25519 signature over the exact UTF-8 bytes of `message_to_sign`.
    """
    if shutil.which("openssl") is None:
        raise RuntimeError("openssl is required to sign GitHub verification challenges")
    seed = _openssh_ed25519_seed_from_private_key(Path(private_key_path).expanduser())
    pem = _ed25519_pkcs8_pem_from_seed(seed)
    msg = (message_to_sign or "").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="git-analysis-ed25519-") as td:
        td_path = Path(td)
        key_pem_path = td_path / "key.pem"
        msg_path = td_path / "message.bin"
        sig_path = td_path / "sig.bin"
        key_pem_path.write_bytes(pem)
        msg_path.write_bytes(msg)
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(key_pem_path), "-in", str(msg_path), "-out", str(sig_path)],
            check=True,
            capture_output=True,
        )
        sig = sig_path.read_bytes()
    if len(sig) != 64:
        raise RuntimeError(f"unexpected Ed25519 signature length: {len(sig)}")
    return base64.b64encode(sig).decode("ascii")


def _ed25519_pkcs8_pem_from_seed(seed32: bytes) -> bytes:
    if len(seed32) != 32:
        raise ValueError("expected 32-byte Ed25519 seed")
    # PrivateKeyInfo (RFC 8410) for Ed25519:
    # 30 2e 02 01 00 30 05 06 03 2b 65 70 04 22 04 20 <seed>
    der = b"\x30\x2e\x02\x01\x00\x30\x05\x06\x03\x2b\x65\x70\x04\x22\x04\x20" + seed32
    b64 = base64.b64encode(der).decode("ascii")
    lines = [b64[i : i + 64] for i in range(0, len(b64), 64)]
    pem = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END PRIVATE KEY-----\n"
    return pem.encode("ascii")


def _openssh_ed25519_seed_from_private_key(private_key_path: Path) -> bytes:
    """
    Extract the 32-byte Ed25519 seed from an unencrypted OpenSSH private key file.
    """
    raw = Path(private_key_path).read_text(encoding="utf-8", errors="replace")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    try:
        i0 = lines.index("-----BEGIN OPENSSH PRIVATE KEY-----")
        i1 = lines.index("-----END OPENSSH PRIVATE KEY-----")
    except ValueError as e:
        raise RuntimeError("invalid OpenSSH private key file (missing header/footer)") from e
    blob = base64.b64decode("".join(lines[i0 + 1 : i1]).encode("ascii"))
    if not blob.startswith(b"openssh-key-v1\0"):
        raise RuntimeError("invalid OpenSSH private key magic")
    off = len(b"openssh-key-v1\0")

    def read_u32(buf: bytes, o: int) -> tuple[int, int]:
        if o + 4 > len(buf):
            raise RuntimeError("truncated OpenSSH private key")
        return struct.unpack(">I", buf[o : o + 4])[0], o + 4

    def read_str(buf: bytes, o: int) -> tuple[bytes, int]:
        n, o = read_u32(buf, o)
        if o + n > len(buf):
            raise RuntimeError("truncated OpenSSH private key")
        return buf[o : o + n], o + n

    ciphername_b, off = read_str(blob, off)
    kdfname_b, off = read_str(blob, off)
    _kdfopts_b, off = read_str(blob, off)
    nkeys, off = read_u32(blob, off)
    _pubkeys: list[bytes] = []
    for _i in range(int(nkeys)):
        pk, off = read_str(blob, off)
        _pubkeys.append(pk)
    priv_blob, off = read_str(blob, off)
    _ = off

    ciphername = ciphername_b.decode("utf-8", errors="replace")
    kdfname = kdfname_b.decode("utf-8", errors="replace")
    if ciphername != "none" or kdfname != "none":
        raise RuntimeError("encrypted OpenSSH keys are not supported (expected ciphername/kdfname 'none')")

    o2 = 0
    _check1, o2 = read_u32(priv_blob, o2)
    _check2, o2 = read_u32(priv_blob, o2)
    ktype, o2 = read_str(priv_blob, o2)
    if ktype != b"ssh-ed25519":
        raise RuntimeError(f"unsupported OpenSSH key type: {ktype!r}")
    pub, o2 = read_str(priv_blob, o2)
    priv, o2 = read_str(priv_blob, o2)
    if len(pub) != 32 or len(priv) != 64:
        raise RuntimeError("invalid ed25519 key lengths in OpenSSH private key")
    if priv[32:] != pub:
        raise RuntimeError("ed25519 private key does not match public key")
    return priv[:32]


def _host_for_remote_canonical(remote_canonical: str) -> str:
    s = (remote_canonical or "").strip().lower()
    if not s:
        return ""
    return s.split("/", 1)[0]


def build_upload_package_v1(*, base: dict, repos: list[dict], privacy_mode: str) -> dict:
    mode = (privacy_mode or "").strip().lower()
    if mode not in ("none", "public_only", "all"):
        raise ValueError(f"invalid privacy_mode: {privacy_mode!r}")

    allowed_public_hosts = {"github.com", "gitlab.com", "bitbucket.org"}
    out_repos: list[dict] = []
    for r in repos:
        repo_key = str(r.get("repo_key", "")).strip()
        if not repo_key:
            raise ValueError("repo missing repo_key")
        row: dict[str, object] = {"repo_key": repo_key}
        remote_canonical = str(r.get("remote_canonical", "")).strip()
        if mode == "all" and remote_canonical:
            row["remote_canonical"] = remote_canonical
        elif mode == "public_only" and remote_canonical:
            host = _host_for_remote_canonical(remote_canonical)
            if host in allowed_public_hosts:
                row["remote_canonical"] = remote_canonical
        out_repos.append(row)

    out_repos.sort(key=lambda d: str(d.get("repo_key", "")))

    out = dict(base)
    out["privacy"] = {"mode": mode, "verification_opt_in": mode in ("public_only", "all")}
    out["repos"] = out_repos
    return out


def upload_package_v1(
    *,
    upload_url: str,
    publisher_token: str,
    payload_bytes: bytes,
    payload_sha256: str,
    timeout_s: int = 30,
    ca_bundle_path: str = "",
) -> None:
    if not upload_url.strip():
        raise ValueError("upload_url is required")
    if not publisher_token.strip():
        raise ValueError("publisher_token is required")
    if not payload_sha256.strip():
        raise ValueError("payload_sha256 is required")
    if hashlib.sha256(payload_bytes).hexdigest() != payload_sha256:
        raise ValueError("payload_sha256 does not match payload_bytes")

    body = gzip.compress(payload_bytes)
    req = urllib.request.Request(
        upload_url,
        method="POST",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "X-Publisher-Token": publisher_token,
            "X-Payload-SHA256": payload_sha256,
        },
    )
    ctx = _ssl_context(ca_bundle_path=ca_bundle_path)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            if 200 <= code < 300:
                return
            payload = resp.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"upload failed: HTTP {code}: {payload[:500]}")
    except urllib.error.HTTPError as e:
        payload = ""
        try:
            payload = e.read().decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        if _is_duplicate_payload_error(code=int(getattr(e, "code", 0) or 0), payload=payload):
            return
        raise RuntimeError(f"upload failed: HTTP {e.code}: {payload[:500]}") from e
    except urllib.error.URLError as e:
        msg = f"upload failed: {e}"
        if _is_cert_verify_error(e):
            msg = msg + "\n" + _cert_verify_hint(ca_bundle_path=ca_bundle_path)
        raise RuntimeError(msg) from e


def _is_duplicate_payload_error(*, code: int, payload: str) -> bool:
    if int(code or 0) != 409:
        return False
    s = (payload or "").strip()
    if not s:
        return False
    try:
        obj = json.loads(s)
    except Exception:
        obj = None
    if isinstance(obj, dict):
        err = str(obj.get("error", "") or "").strip().lower()
        msg = str(obj.get("message", "") or "").strip().lower()
        if err == "duplicate":
            return True
        if "duplicate payload" in msg:
            return True
    sl = s.lower()
    return "duplicate payload" in sl


def _display_name_url_from_api_url(api_url: str) -> str:
    u = (api_url or "").strip().rstrip("/")
    if not u:
        return ""
    if u.endswith("/api/v1/me/display-name"):
        return u
    if u.endswith("/api/v1/uploads"):
        u = u[: -len("/api/v1/uploads")].rstrip("/")
    return u + "/api/v1/me/display-name"


def update_display_name_v1(
    *,
    api_url: str,
    publisher_token: str,
    display_name: str,
    timeout_s: int = 30,
    ca_bundle_path: str = "",
) -> dict[str, object]:
    if not publisher_token.strip():
        raise ValueError("publisher_token is required")
    name = (display_name or "").strip()
    if not name:
        raise ValueError("display_name is required")
    if len(name) > 80:
        raise ValueError("display_name is too long (max 80 chars)")

    url = _display_name_url_from_api_url(api_url)
    if not url:
        raise ValueError("api_url is required")

    payload = json.dumps({"display_name": name}, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        method="POST",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Publisher-Token": publisher_token,
        },
    )
    ctx = _ssl_context(ca_bundle_path=ca_bundle_path)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            body = resp.read().decode("utf-8", errors="replace")
            if 200 <= code < 300:
                try:
                    obj = json.loads(body) if body else {}
                except Exception:
                    obj = {}
                return obj if isinstance(obj, dict) else {}
            raise RuntimeError(f"display-name update failed: HTTP {code}: {body[:500]}")
    except urllib.error.HTTPError as e:
        payload_s = ""
        try:
            payload_s = e.read().decode("utf-8", errors="replace")
        except Exception:
            payload_s = ""
        raise RuntimeError(f"display-name update failed: HTTP {e.code}: {payload_s[:500]}") from e
    except urllib.error.URLError as e:
        msg = f"display-name update failed: {e}"
        if _is_cert_verify_error(e):
            msg = msg + "\n" + _cert_verify_hint(ca_bundle_path=ca_bundle_path)
        raise RuntimeError(msg) from e


def _github_verify_challenge_url_from_api_url(api_url: str) -> str:
    u = (api_url or "").strip().rstrip("/")
    if not u:
        return ""
    suffix = "/api/v1/me/github/verify/challenge"
    if u.endswith(suffix):
        return u
    if u.endswith("/api/v1/uploads"):
        u = u[: -len("/api/v1/uploads")].rstrip("/")
    return u + suffix


def _github_verify_confirm_url_from_api_url(api_url: str) -> str:
    u = (api_url or "").strip().rstrip("/")
    if not u:
        return ""
    suffix = "/api/v1/me/github/verify/confirm"
    if u.endswith(suffix):
        return u
    if u.endswith("/api/v1/uploads"):
        u = u[: -len("/api/v1/uploads")].rstrip("/")
    return u + suffix


def github_verify_challenge_v1(
    *,
    api_url: str,
    publisher_token: str,
    github_username: str,
    timeout_s: int = 30,
    ca_bundle_path: str = "",
) -> dict[str, object]:
    if not publisher_token.strip():
        raise ValueError("publisher_token is required")
    username = (github_username or "").strip()
    if not username:
        raise ValueError("github_username is required")

    url = _github_verify_challenge_url_from_api_url(api_url)
    if not url:
        raise ValueError("api_url is required")

    payload = json.dumps({"github_username": username}, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        method="POST",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Publisher-Token": publisher_token,
        },
    )
    ctx = _ssl_context(ca_bundle_path=ca_bundle_path)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            body = resp.read().decode("utf-8", errors="replace")
            if 200 <= code < 300:
                try:
                    obj = json.loads(body) if body else {}
                except Exception:
                    obj = {}
                return obj if isinstance(obj, dict) else {}
            raise RuntimeError(f"github-verify challenge failed: HTTP {code}: {body[:500]}")
    except urllib.error.HTTPError as e:
        payload_s = ""
        try:
            payload_s = e.read().decode("utf-8", errors="replace")
        except Exception:
            payload_s = ""
        raise RuntimeError(f"github-verify challenge failed: HTTP {e.code}: {payload_s[:500]}") from e
    except urllib.error.URLError as e:
        msg = f"github-verify challenge failed: {e}"
        if _is_cert_verify_error(e):
            msg = msg + "\n" + _cert_verify_hint(ca_bundle_path=ca_bundle_path)
        raise RuntimeError(msg) from e


def github_verify_confirm_v1(
    *,
    api_url: str,
    publisher_token: str,
    github_username: str,
    challenge: str,
    signature: str,
    timeout_s: int = 30,
    ca_bundle_path: str = "",
) -> dict[str, object]:
    if not publisher_token.strip():
        raise ValueError("publisher_token is required")
    username = (github_username or "").strip()
    if not username:
        raise ValueError("github_username is required")
    ch = (challenge or "").strip()
    if not ch:
        raise ValueError("challenge is required")
    sig = (signature or "").strip()
    if not sig:
        raise ValueError("signature is required")

    url = _github_verify_confirm_url_from_api_url(api_url)
    if not url:
        raise ValueError("api_url is required")

    payload = (
        json.dumps(
            {"github_username": username, "challenge": ch, "signature": sig},
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    req = urllib.request.Request(
        url,
        method="POST",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Publisher-Token": publisher_token,
        },
    )
    ctx = _ssl_context(ca_bundle_path=ca_bundle_path)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            body = resp.read().decode("utf-8", errors="replace")
            if 200 <= code < 300:
                try:
                    obj = json.loads(body) if body else {}
                except Exception:
                    obj = {}
                return obj if isinstance(obj, dict) else {}
            raise RuntimeError(f"github-verify confirm failed: HTTP {code}: {body[:500]}")
    except urllib.error.HTTPError as e:
        payload_s = ""
        try:
            payload_s = e.read().decode("utf-8", errors="replace")
        except Exception:
            payload_s = ""
        raise RuntimeError(f"github-verify confirm failed: HTTP {e.code}: {payload_s[:500]}") from e
    except urllib.error.URLError as e:
        msg = f"github-verify confirm failed: {e}"
        if _is_cert_verify_error(e):
            msg = msg + "\n" + _cert_verify_hint(ca_bundle_path=ca_bundle_path)
        raise RuntimeError(msg) from e


def _ssl_context(*, ca_bundle_path: str) -> ssl.SSLContext:
    cafile, capath = _resolve_ca_paths(ca_bundle_path)
    if cafile or capath:
        return ssl.create_default_context(cafile=cafile, capath=capath)
    return ssl.create_default_context()


def _resolve_ca_paths(explicit: str) -> tuple[str | None, str | None]:
    p = (explicit or "").strip()
    if p:
        path = Path(p).expanduser()
        if path.is_dir():
            return None, str(path)
        return str(path), None

    # Prefer explicit env vars (common in tooling ecosystems).
    for k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        v = (os.environ.get(k) or "").strip()
        if not v:
            continue
        path = Path(v).expanduser()
        if path.is_dir():
            return None, str(path)
        return str(path), None

    vp = ssl.get_default_verify_paths()
    candidates_file = [vp.cafile, vp.openssl_cafile]
    for cand in candidates_file:
        if cand and Path(cand).exists():
            return cand, None
    candidates_dir = [vp.capath, vp.openssl_capath]
    for cand in candidates_dir:
        if cand and Path(cand).is_dir():
            return None, cand

    # Common CA bundle locations for minimal environments / CI.
    for cand in (
        "/etc/ssl/cert.pem",  # macOS/Homebrew Python
        "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
        "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL/CentOS/Fedora
        "/etc/ssl/ca-bundle.pem",  # SUSE
    ):
        if Path(cand).exists():
            return cand, None

    cafile = _certifi_cafile()
    if cafile is not None:
        return cafile, None

    cafile_path = _ensure_macos_ca_bundle()
    if cafile_path is not None:
        return str(cafile_path), None

    return None, None


def _is_cert_verify_error(e: urllib.error.URLError) -> bool:
    reason = getattr(e, "reason", None)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    s = str(e)
    return "CERTIFICATE_VERIFY_FAILED" in s or "certificate verify failed" in s.lower()


def _cert_verify_hint(*, ca_bundle_path: str) -> str:
    parts: list[str] = []
    parts.append("Hint: HTTPS certificate verification failed (client does not trust the issuer).")
    parts.append("If this is a private CA, pass `--ca-bundle /path/to/ca.pem` or set `upload_config.ca_bundle_path` in config.json.")

    vp = ssl.get_default_verify_paths()
    parts.append(
        "Python SSL default verify paths: "
        + f"cafile={vp.cafile!r}, capath={vp.capath!r}, openssl_cafile={vp.openssl_cafile!r}, openssl_capath={vp.openssl_capath!r}."
    )
    if sys.platform == "darwin" and (vp.cafile is None and vp.capath is None):
        parts.append(
            "On macOS with python.org Python, the tool will try to build a CA bundle from the system Keychain; "
            "alternatively, run the bundled `Install Certificates.command` for that Python."
        )
    if (ca_bundle_path or "").strip():
        parts.append(f"Using ca_bundle_path={str(Path(ca_bundle_path).expanduser())!r}.")
    return " ".join(parts)


def _certifi_cafile() -> str | None:
    try:
        import certifi  # type: ignore[import-not-found]
    except Exception:
        return None
    path = str(getattr(certifi, "where", lambda: "")() or "").strip()
    if not path:
        return None
    if Path(path).exists():
        return path
    return None


def _default_cache_dir() -> Path:
    xdg = str(os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "git-analysis"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "git-analysis"
    return Path.home() / ".cache" / "git-analysis"


def _ensure_macos_ca_bundle(*, cache_dir: Path | None = None, max_age_days: int = 30) -> Path | None:
    if sys.platform != "darwin":
        return None
    if shutil.which("security") is None:
        return None

    out_dir = cache_dir if cache_dir is not None else _default_cache_dir()
    out_path = out_dir / "macos-system-ca-bundle.pem"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None

    try:
        if out_path.exists() and max_age_days > 0:
            age_s = time.time() - out_path.stat().st_mtime
            if age_s < max_age_days * 86400:
                return out_path
    except Exception:
        pass

    keychains: list[str] = []
    for kc in (
        "/System/Library/Keychains/SystemRootCertificates.keychain",
        "/Library/Keychains/System.keychain",
    ):
        if Path(kc).exists():
            keychains.append(kc)
    if not keychains:
        return None

    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    try:
        with tmp.open("wb") as f:
            wrote_any = False
            for kc in keychains:
                try:
                    subprocess.run(
                        ["security", "find-certificate", "-a", "-p", kc],
                        check=True,
                        stdout=f,
                        stderr=subprocess.DEVNULL,
                    )
                    wrote_any = True
                except Exception:
                    continue
        if not wrote_any:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        try:
            head = tmp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            head = ""
        if "BEGIN CERTIFICATE" not in head:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        tmp.replace(out_path)
        return out_path
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None
