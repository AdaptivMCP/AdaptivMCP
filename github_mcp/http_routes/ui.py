from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from starlette.responses import FileResponse, JSONResponse, Response


def _assets_dir() -> Path:
    # main.py mounts /static from `<repo_root>/assets`.
    # Keep this aligned for UI routes.
    return Path(__file__).resolve().parents[2] / "assets"


def build_ui_index_endpoint() -> Any:
    async def _endpoint(_request) -> Response:
        index_path = _assets_dir() / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path), media_type="text/html")
        return JSONResponse(
            {
                "error": {
                    "code": "ui_missing",
                    "message": "UI assets are not installed on this deployment.",
                    "details": {"expected_path": str(index_path)},
                }
            },
            status_code=404,
        )

    return _endpoint


def build_ui_json_endpoint() -> Any:
    async def _endpoint(_request) -> Response:
        # Avoid guessing hostnames. This endpoint is purely descriptive.
        return JSONResponse(
            {
                "service": "adaptiv-mcp-github",
                "version": {
                    "git_commit": os.getenv("GIT_COMMIT") or os.getenv("RENDER_GIT_COMMIT"),
                    "git_branch": os.getenv("GIT_BRANCH") or os.getenv("RENDER_GIT_BRANCH"),
                },
                "endpoints": {
                    "health": "/healthz",
                    "tools": "/tools",
                    "resources": "/resources",
                    "stream": "/sse",
                },
                "notes": [
                    "/healthz reports baseline health after deploy.",
                    "/tools supports discovery; POST /tools/<name> invokes a tool.",
                ],
            }
        )

    return _endpoint


def register_ui_routes(app: Any) -> None:
    """Register lightweight UI routes for browser-based diagnostics."""

    app.add_route("/", build_ui_index_endpoint(), methods=["GET"])
    app.add_route("/ui", build_ui_index_endpoint(), methods=["GET"])
    app.add_route("/ui.json", build_ui_json_endpoint(), methods=["GET"])
