from __future__ import annotations

import platform
import sys
import time
from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from github_mcp.config import (
    SERVER_GIT_COMMIT,
    SERVER_START_TIME,
)
from github_mcp.exceptions import GitHubAuthError
from github_mcp.http_clients import _get_github_token
from github_mcp.server import CONTROLLER_DEFAULT_BRANCH, CONTROLLER_REPO


def _github_token_present() -> bool:
    try:
        return bool(_get_github_token())
    except GitHubAuthError:
        return False
    except Exception:
        # Be conservative: treat unexpected failures as missing tokens so that
        # the health endpoint signals degraded state instead of crashing.
        return False


def _build_health_payload() -> dict[str, Any]:
    github_token_present = _github_token_present()
    uptime_seconds = max(0, int(time.time() - SERVER_START_TIME))

    payload = {
        "status": "ok",
        "git_commit": SERVER_GIT_COMMIT,
        "uptime_seconds": uptime_seconds,
        "github_token_present": github_token_present,
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "controller": {
            "repo": CONTROLLER_REPO,
            "default_branch": CONTROLLER_DEFAULT_BRANCH,
        },
    }
    return payload


def build_healthz_endpoint() -> Callable[[Request], JSONResponse]:
    async def _endpoint(_: Request) -> JSONResponse:
        return JSONResponse(_build_health_payload())

    return _endpoint


def register_healthz_route(app: Any) -> None:
    """Register the /healthz route on the ASGI app."""

    app.add_route("/healthz", build_healthz_endpoint(), methods=["GET"])


__all__ = ["register_healthz_route"]
