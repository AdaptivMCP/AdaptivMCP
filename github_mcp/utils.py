"""Utility helpers shared by GitHub MCP tools."""

from __future__ import annotations

import io
import json
import os  # noqa: E402  pylint: disable=wrong-import-position
import re
import subprocess  # nosec B404
import sys
import zipfile
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse

from .exceptions import GitHubAPIError


def _get_main_module():
    """Return the active main module when running under different entrypoints.

    In some environments the entrypoint is loaded as `__main__` instead of `main`.
    Helpers use this for optional monkeypatch overrides without importing the
    top-level entry module directly.
    """

    return sys.modules.get("main") or sys.modules.get("__main__") or SimpleNamespace()


def _env_flag(name: str, default: bool = False) -> bool:
    """Return True when an environment variable is set to a truthy value."""

    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes", "y", "on"}


def _normalize_timeout_seconds(value: object, default: int) -> int:
    """Normalize a timeout value to an integer number of seconds.

    Accepts ints/floats/strings (including float-like strings).

    Semantics:
    - A value of ``0`` (or any negative value) means "no timeout".
    - ``None`` (or invalid inputs) fall back to ``default``.
    """

    def _coerce(v: object) -> int:
        if v is None or isinstance(v, bool):
            return int(default)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return int(default)
            try:
                return int(float(s))
            except Exception:
                return int(default)
        return int(default)

    try:
        coerced = _coerce(value)
    except Exception:
        coerced = int(default)

    # 0 (or negative) disables timeouts.
    return max(0, coerced)


def _extract_hostname(value: str | None) -> str | None:
    """Extract a hostname from an env-var style value.

    Supports values that may be:
    - raw hostnames ("example.com")
    - full URLs ("https://example.com/sse")
    - whitespace-padded strings
    """

    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if "://" in cleaned:
        parsed = urlparse(cleaned)
    else:
        parsed = urlparse(f"http://{cleaned}")
    host = parsed.hostname or parsed.netloc
    return host or None


def _render_external_hosts() -> list[str]:
    """Return Render external hostnames derived from standard env vars."""

    hostnames: list[str] = []
    for env_name in ("RENDER_EXTERNAL_HOSTNAME", "RENDER_EXTERNAL_URL"):
        hostname = _extract_hostname(os.getenv(env_name))
        if hostname:
            hostnames.append(hostname)
    return hostnames


def _effective_ref_for_repo(full_name: str, ref: str | None) -> str:
    # Allow tests (and callers) to override controller settings by monkeypatching
    # the main module without needing to import this helper directly.
    main_module = _get_main_module()
    controller_repo_main = getattr(main_module, "CONTROLLER_REPO", CONTROLLER_REPO)
    controller_default_branch_main = getattr(
        main_module, "CONTROLLER_DEFAULT_BRANCH", CONTROLLER_DEFAULT_BRANCH
    )

    if full_name in {controller_repo_main, CONTROLLER_REPO}:
        if not ref or ref == "main":
            if full_name == controller_repo_main:
                return controller_default_branch_main
            return CONTROLLER_DEFAULT_BRANCH
        return ref

    if ref:
        return ref
    repo_defaults = REPO_DEFAULTS.get(full_name)
    if repo_defaults and repo_defaults.get("default_branch"):
        return repo_defaults["default_branch"]
    return "main"


def _default_branch_for_repo(full_name: str) -> str:
    """Return the default branch name for a repository."""

    if full_name == CONTROLLER_REPO:
        return CONTROLLER_DEFAULT_BRANCH

    repo_defaults = REPO_DEFAULTS.get(full_name)
    if repo_defaults and repo_defaults.get("default_branch"):
        return repo_defaults["default_branch"]

    return "main"


def _normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative path and enforce basic safety invariants."""

    if not isinstance(path, str):
        # Best-effort stringification.
        try:
            path = str(path)
        except Exception:
            path = ""

    normalized = path.strip().replace("\\", "/").lstrip("/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")

    # Normalize segments.
    #
    # Keep path segments as-is (including "..") to avoid clamping.
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        parts.append(part)

    normalized = "/".join(parts)
    if not normalized:
        # Permissive mode: allow empty/root path and let higher-level tools
        # decide whether that is meaningful for the specific operation.
        return ""

    return normalized


def _normalize_repo_path_for_repo(full_name: str, path: str) -> str:
    """Normalize a repo-relative path while forgiving common URL prefixes."""

    if not isinstance(path, str):
        try:
            path = str(path)
        except Exception:
            path = ""

    normalized = path.strip().replace("\\", "/")
    # Accept common GitHub URL forms (html, raw, api) and extract the repo-relative
    # path portion.
    if normalized:
        url_candidate = normalized
        if url_candidate.startswith(
            (
                "github.com/",
                "www.github.com/",
                "raw.githubusercontent.com/",
                "api.github.com/",
            )
        ):
            url_candidate = f"https://{url_candidate}"

        if "://" in url_candidate:
            parsed = urlparse(url_candidate)
            host = (parsed.hostname or parsed.netloc or "").lower()
            parsed_path = unquote(parsed.path or "")
            parsed_path = parsed_path.replace("\\", "/")
            parsed_path = parsed_path.lstrip("/")

            if host in {"github.com", "www.github.com"}:
                parts = [p for p in parsed_path.split("/") if p]
                if len(parts) >= 2:
                    remainder = parts[2:]
                    # Handle common GitHub UI URL shapes:
                    # - /<owner>/<repo>/blob/<ref>/<path>
                    # - /<owner>/<repo>/tree/<ref>/<path>
                    # - /<owner>/<repo>/raw/<ref>/<path>
                    if len(remainder) >= 2 and remainder[0] in {"blob", "tree", "raw"}:
                        remainder = remainder[2:]

                    # If this URL points at a different repo than the caller
                    # expects, we still strip to the remainder to avoid leaking
                    # repo prefixes into the normalization layer.
                    normalized = "/".join(remainder)
                else:
                    normalized = ""
            elif host == "raw.githubusercontent.com":
                parts = [p for p in parsed_path.split("/") if p]
                # /<owner>/<repo>/<ref>/<path>
                if len(parts) >= 4:
                    normalized = "/".join(parts[3:])
                else:
                    normalized = ""
            elif host == "api.github.com":
                # Preserve the leading slash so existing API-prefix stripping
                # logic can match.
                normalized = f"/{parsed_path}"
            else:
                # Unknown host: best-effort use of the URL path.
                normalized = parsed_path
    full_name_clean = (
        full_name.strip().lstrip("/") if isinstance(full_name, str) else ""
    )
    if full_name_clean:
        api_prefixes = (
            f"/repos/{full_name_clean}/contents/",
            f"repos/{full_name_clean}/contents/",
        )
        for prefix in api_prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break

        repo_prefixes = (
            f"/{full_name_clean}/",
            f"{full_name_clean}/",
        )
        for prefix in repo_prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        repo_name = full_name_clean.split("/")[-1]
        if repo_name:
            short_prefixes = (
                f"/{repo_name}/",
                f"{repo_name}/",
            )
            for prefix in short_prefixes:
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix) :]
                    break

    # After stripping common prefixes, ensure we still have a concrete path.
    # Many callers mistakenly pass repository URLs or repo roots; surface a
    # clearer error than "empty after normalization".
    cleaned = normalized.strip().replace("\\", "/")
    if cleaned in {"", "/", ".", "./"}:
        return ""

    return _normalize_repo_path(normalized)


def _normalize_branch(full_name: str, branch: str | None) -> str:
    """Normalize a branch name while honoring controller defaults."""

    normalized_branch = branch.strip() if isinstance(branch, str) else None
    effective = _effective_ref_for_repo(full_name, normalized_branch)

    # Let higher layers decide whether writes to the default branch are allowed.
    # The normalizer only ensures we have a stable, explicit ref.
    if not effective:
        effective = "main"

    if any(ord(ch) < 32 for ch in effective):
        # Permissive mode: strip control characters.
        effective = "".join(ch for ch in effective if ord(ch) >= 32).strip() or "main"

    return effective


def _normalize_write_context(
    full_name: str, branch: str | None, path: str | None = None
) -> tuple[str, str | None]:
    """Normalize standard write-context arguments (branch + optional path)."""

    effective_branch = _normalize_branch(full_name, branch)
    normalized_path: str | None = None
    if path is not None:
        normalized_path = _normalize_repo_path_for_repo(full_name, path)
        # A repo-relative file path must not normalize to "". Some callers pass
        # repo roots or URLs; treat those as invalid for write tools.
        if normalized_path == "":
            normalized_path = None
    return effective_branch, normalized_path


def extract_sha(decoded: Mapping[str, Any]) -> str | None:
    """Extract a SHA value from decoded GitHub content payloads."""

    if not isinstance(decoded, Mapping):
        return None
    json_blob = decoded.get("json")
    if isinstance(json_blob, Mapping) and isinstance(json_blob.get("sha"), str):
        return json_blob["sha"]
    sha_value = decoded.get("sha")
    return sha_value if isinstance(sha_value, str) else None


def require_text(
    decoded: Mapping[str, Any], *, error_message: str = "Decoded content is not text"
) -> str:
    """Return decoded text content or raise a GitHubAPIError."""

    text = decoded.get("text")
    if not isinstance(text, str):
        raise GitHubAPIError(error_message)
    return text


def _with_numbered_lines(text: str) -> list[dict[str, Any]]:
    return [
        {"line": idx, "text": line} for idx, line in enumerate(text.splitlines(), 1)
    ]


def _render_visible_whitespace(text: str) -> str:
    """Surface whitespace characters when clients hide them by default."""

    rendered_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        body = body.replace("\t", "→\t").replace(" ", "·")
        newline_marker = "⏎" if line.endswith("\n") else "␄"
        rendered_lines.append(f"{body}{newline_marker}")

    return "\n".join(rendered_lines)


def _decode_zipped_job_logs(zip_bytes: bytes) -> str:
    """Extract and concatenate text files from a zipped job log archive."""

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_file:
            parts: list[str] = []
            for name in sorted(
                entry for entry in zip_file.namelist() if not entry.endswith("/")
            ):
                with zip_file.open(name) as handle:
                    content = handle.read().decode("utf-8", errors="replace")
                parts.append(f"[{name}]\n{content}".rstrip())
            return "\n\n".join(parts)
    except Exception as exc:
        exc_name = type(exc).__name__
        exc_message = str(exc).strip()
        if exc_message:
            detail = f"{exc_name}: {exc_message}"
        else:
            detail = exc_name
        return f"[error decoding job logs archive: {detail}]"


def _load_repo_defaults() -> tuple[dict[str, dict[str, str]], str | None]:
    raw_value = os.environ.get("GITHUB_REPO_DEFAULTS")
    if raw_value is None:
        return {}, None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        return (
            {},
            f"Invalid JSON in GITHUB_REPO_DEFAULTS; defaults ignored ({exc.msg}).",
        )
    if not isinstance(parsed, dict):
        return (
            {},
            "GITHUB_REPO_DEFAULTS must be a JSON object; defaults ignored.",
        )

    # Normalize and validate defaults. The server expects a mapping
    # {"owner/repo": {"default_branch": "main"}}.
    # For backwards compatibility, also accept {"owner/repo": "main"}.
    normalized: dict[str, dict[str, str]] = {}
    dropped: list[str] = []
    for key, value in parsed.items():
        if not isinstance(key, str) or not key.strip():
            dropped.append(str(key))
            continue

        repo_key = key.strip()
        default_branch: str | None = None
        if isinstance(value, str):
            default_branch = value.strip() or None
        elif isinstance(value, dict):
            branch_candidate = value.get("default_branch")
            if isinstance(branch_candidate, str):
                default_branch = branch_candidate.strip() or None

        if not default_branch:
            dropped.append(repo_key)
            continue

        normalized[repo_key] = {"default_branch": default_branch}

    if dropped:
        return (
            normalized,
            "GITHUB_REPO_DEFAULTS contained invalid entries; those defaults were ignored.",
        )

    return normalized, None


REPO_DEFAULTS, REPO_DEFAULTS_PARSE_ERROR = _load_repo_defaults()


def _parse_github_remote_repo(remote_url: str) -> str | None:
    """Best-effort parse of a git remote URL into an owner/repo slug."""

    url = (remote_url or "").strip()
    if not url:
        return None

    # Common shapes:
    # - https://github.com/<owner>/<repo>.git
    # - git@github.com:<owner>/<repo>.git
    patterns = (r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",)
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            owner = (match.group("owner") or "").strip()
            repo = (match.group("repo") or "").strip()
            if owner and repo:
                return f"{owner}/{repo}"
    return None


def _detect_controller_repo(*, fallback: str) -> str:
    """Resolve the controller repo slug (owner/repo) with best-effort inference.

    Resolution order:
    1) Explicit override via ADAPTIV_MCP_CONTROLLER_REPO
    2) GitHub Actions-style env vars (GITHUB_REPOSITORY)
    3) Render-style env vars (if present)
    4) Local git remote.origin.url (if available)
    5) Provided fallback
    """

    explicit = (os.environ.get("ADAPTIV_MCP_CONTROLLER_REPO") or "").strip()
    if explicit:
        return explicit

    github_repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if github_repo and "/" in github_repo:
        return github_repo

    # Render (and similar platforms) occasionally expose repo metadata.
    render_slug = (
        os.environ.get("RENDER_GIT_REPO")
        or os.environ.get("RENDER_GIT_REPO_SLUG")
        or os.environ.get("RENDER_REPO")
        or os.environ.get("RENDER_REPO_SLUG")
        or ""
    ).strip()
    if render_slug:
        if "/" in render_slug:
            return render_slug
        render_owner = (
            os.environ.get("RENDER_GIT_REPO_OWNER")
            or os.environ.get("RENDER_REPO_OWNER")
            or ""
        ).strip()
        if render_owner and "/" not in render_owner:
            return f"{render_owner}/{render_slug}"

    try:
        remote_url = subprocess.check_output(  # nosec
            ["git", "config", "--get", "remote.origin.url"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        remote_url = ""

    parsed = _parse_github_remote_repo(remote_url)
    if parsed:
        return parsed

    return fallback


def _detect_controller_branch(*, fallback: str) -> str:
    """Resolve the controller default branch with best-effort inference."""

    explicit = (os.environ.get("ADAPTIV_MCP_CONTROLLER_BRANCH") or "").strip()
    if explicit:
        return explicit

    for env_name in (
        "GITHUB_REF_NAME",
        "GITHUB_HEAD_REF",
        "RENDER_GIT_BRANCH",
        "GIT_BRANCH",
    ):
        candidate = (os.environ.get(env_name) or "").strip()
        if candidate:
            return candidate

    # Try to infer from the local repo if git metadata is available.
    try:
        branch = subprocess.check_output(  # nosec
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if branch and branch not in {"HEAD", "(unknown)"}:
            return branch
    except Exception:  # nosec B110
        pass

    return fallback


CONTROLLER_REPO = _detect_controller_repo(fallback="owner/repo")
CONTROLLER_DEFAULT_BRANCH = _detect_controller_branch(fallback="main")

__all__ = [
    "_get_main_module",
    "REPO_DEFAULTS_PARSE_ERROR",
    "REPO_DEFAULTS",
    "_decode_zipped_job_logs",
    "_default_branch_for_repo",
    "_effective_ref_for_repo",
    "_extract_hostname",
    "_env_flag",
    "_normalize_timeout_seconds",
    "extract_sha",
    "_normalize_branch",
    "_normalize_repo_path",
    "_normalize_repo_path_for_repo",
    "_normalize_write_context",
    "require_text",
    "_render_external_hosts",
    "_render_visible_whitespace",
    "_with_numbered_lines",
]
