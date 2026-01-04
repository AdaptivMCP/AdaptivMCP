"""Utility helpers shared by GitHub MCP tools."""

from __future__ import annotations

import io
import json
import os  # noqa: E402  pylint: disable=wrong-import-position
import sys
import zipfile
from types import SimpleNamespace
from typing import Any, Dict, Mapping
from urllib.parse import urlparse

from .exceptions import GitHubAPIError, ToolPreflightValidationError


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
        host = parsed.hostname or parsed.netloc
        return host or None
    return cleaned


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
        raise ToolPreflightValidationError("<server>", "path must be a string")

    normalized = path.strip().replace("\\", "/").lstrip("/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")

    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ToolPreflightValidationError(
            "<server>",
            f"Invalid path {path!r}: parent-directory segments are not allowed.",
        )

    normalized = "/".join(parts)
    if not normalized:
        raise ToolPreflightValidationError(
            "<server>", "Path must not be empty after normalization."
        )

    return normalized


def _normalize_repo_path_for_repo(full_name: str, path: str) -> str:
    """Normalize a repo-relative path while forgiving common assistant prefixes."""

    if not isinstance(path, str):
        raise ToolPreflightValidationError("<server>", "path must be a string")

    normalized = path.strip().replace("\\", "/")
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

    return _normalize_repo_path(normalized)


def _normalize_branch(full_name: str, branch: str | None) -> str:
    """Normalize a branch name while honoring controller defaults."""

    normalized_branch = branch.strip() if isinstance(branch, str) else None
    effective = _effective_ref_for_repo(full_name, normalized_branch)

    # Let higher layers decide whether writes to the default branch are allowed.
    # The normalizer only ensures we have a stable, explicit ref.
    if not effective:
        raise ToolPreflightValidationError(
            "<server>", "Effective branch name resolved to an empty value."
        )

    if any(ord(ch) < 32 for ch in effective):
        raise ToolPreflightValidationError(
            "<server>", f"Branch name contains control characters: {effective!r}"
        )

    return effective


def _normalize_write_context(
    full_name: str, branch: str | None, path: str | None = None
) -> tuple[str, str | None]:
    """Normalize standard write-context arguments (branch + optional path)."""

    effective_branch = _normalize_branch(full_name, branch)
    normalized_path: str | None = None
    if path is not None:
        normalized_path = _normalize_repo_path_for_repo(full_name, path)
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


def _with_numbered_lines(text: str) -> list[Dict[str, Any]]:
    return [
        {"line": idx, "text": line} for idx, line in enumerate(text.splitlines(), 1)
    ]


def _render_visible_whitespace(text: str) -> str:
    """Surface whitespace characters for assistants that hide them by default."""

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
    except Exception:
        return ""


def _load_repo_defaults() -> tuple[Dict[str, Dict[str, str]], str | None]:
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
    return parsed, None


REPO_DEFAULTS, REPO_DEFAULTS_PARSE_ERROR = _load_repo_defaults()
CONTROLLER_REPO = os.environ.get(
    "GITHUB_MCP_CONTROLLER_REPO", "Proofgate-Revocations/chatgpt-mcp-github"
)
CONTROLLER_DEFAULT_BRANCH = os.environ.get("GITHUB_MCP_CONTROLLER_BRANCH", "main")

__all__ = [
    "_get_main_module",
    "REPO_DEFAULTS_PARSE_ERROR",
    "REPO_DEFAULTS",
    "_decode_zipped_job_logs",
    "_default_branch_for_repo",
    "_effective_ref_for_repo",
    "_extract_hostname",
    "_env_flag",
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
