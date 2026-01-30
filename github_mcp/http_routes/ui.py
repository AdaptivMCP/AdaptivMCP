from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from starlette.responses import FileResponse, JSONResponse, Response

from github_mcp.config import SERVER_GIT_COMMIT, SERVER_START_TIME
from github_mcp.path_utils import request_base_path as _request_base_path
from github_mcp.utils import CONTROLLER_DEFAULT_BRANCH, CONTROLLER_REPO


def _assets_dir() -> Path:
    # main.py mounts /static from `<repo_root>/assets`.
    # Keep this aligned for UI routes.
    return Path(__file__).resolve().parents[2] / "assets"


def _iso_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))
    except Exception:
        return None


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
    async def _endpoint(request) -> Response:
        # Avoid guessing hostnames. This endpoint is purely descriptive.
        base_prefix = _request_base_path(request, ["/ui.json"])
        now = time.time()
        uptime_seconds = max(0, int(now - float(SERVER_START_TIME)))

        return JSONResponse(
            {
                "service": "adaptiv-mcp-github",
                "repo": {
                    "full_name": CONTROLLER_REPO,
                    "default_branch": CONTROLLER_DEFAULT_BRANCH,
                },
                "version": {
                    "git_commit": (
                        SERVER_GIT_COMMIT
                        or os.getenv("GIT_COMMIT")
                        or os.getenv("RENDER_GIT_COMMIT")
                    ),
                    "git_branch": os.getenv("GIT_BRANCH")
                    or os.getenv("RENDER_GIT_BRANCH"),
                },
                "runtime": {
                    "server_time_utc": _iso_utc(now),
                    "started_at_utc": _iso_utc(float(SERVER_START_TIME)),
                    "uptime_seconds": uptime_seconds,
                },
                "endpoints": {
                    "health": f"{base_prefix}/healthz",
                    "tools": f"{base_prefix}/tools",
                    "resources": f"{base_prefix}/resources",
                    "stream": f"{base_prefix}/sse",
                    "tools_ui": f"{base_prefix}/ui/tools",
                    "tools_json": f"{base_prefix}/ui/tools.json",
                    "render": {
                        "owners": f"{base_prefix}/render/owners",
                        "services": f"{base_prefix}/render/services",
                        "service": f"{base_prefix}/render/services/<service_id>",
                        "deploys": f"{base_prefix}/render/services/<service_id>/deploys",
                        "deploy": f"{base_prefix}/render/services/<service_id>/deploys/<deploy_id>",
                        "deploy_create": (
                            f"POST {base_prefix}/render/services/<service_id>/deploys"
                        ),
                        "deploy_cancel": (
                            f"POST {base_prefix}/render/services/<service_id>/deploys/<deploy_id>/cancel"
                        ),
                        "deploy_rollback": (
                            f"POST {base_prefix}/render/services/<service_id>/deploys/<deploy_id>/rollback"
                        ),
                        "restart": f"POST {base_prefix}/render/services/<service_id>/restart",
                        "logs": f"{base_prefix}/render/logs",
                    },
                },
                "notes": [
                    "/healthz reports baseline health after deploy.",
                    "/tools supports discovery; POST /tools/{tool_name} invokes a tool.",
                    "Render endpoints require RENDER_API_KEY/RENDER_API_TOKEN configured.",
                    "/ui/tools provides a developer-facing tool catalog (search/filter).",
                ],
            }
        )

    return _endpoint


def register_ui_routes(app: Any) -> None:
    """Register lightweight UI routes for browser-based diagnostics."""

    app.add_route("/", build_ui_index_endpoint(), methods=["GET"])
    app.add_route("/ui", build_ui_index_endpoint(), methods=["GET"])
    app.add_route("/ui.json", build_ui_json_endpoint(), methods=["GET"])
    app.add_route("/ui/tools", build_ui_tools_endpoint(), methods=["GET"])
    app.add_route("/ui/tools.json", build_ui_tools_json_endpoint(), methods=["GET"])


def build_ui_tools_json_endpoint() -> Any:
    async def _endpoint(_request) -> Response:
        from github_mcp.main_tools.introspection import list_all_actions

        catalog = list_all_actions(include_parameters=True, compact=False)
        return JSONResponse(catalog)

    return _endpoint


def build_ui_tools_endpoint() -> Any:
    async def _endpoint(_request) -> Response:
        # Minimal, self-contained HTML. Avoids a build step.
        html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Adaptiv MCP – Tool Catalog</title>
  <style>
    body{font-family:ui-monospace,Menlo,Monaco,Consolas,monospace;margin:16px;}
    .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:12px;}
    input{padding:8px 10px;min-width:260px;}
    select,button{padding:8px 10px;}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;}
    .card{border:1px solid #333;border-radius:10px;padding:12px;}
    .name{font-size:14px;font-weight:700;margin-bottom:6px;}
    .badges{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 10px;}
    .badge{border:1px solid #555;border-radius:999px;padding:2px 8px;font-size:12px;}
    .desc{font-size:12px;white-space:pre-wrap;opacity:.9;}
    .meta{font-size:12px;opacity:.8;margin-top:10px;}
    .kv{display:flex;gap:8px;flex-wrap:wrap;}
    .kv span{border:1px dashed #555;border-radius:8px;padding:2px 8px;}
    .small{font-size:11px;opacity:.85;}
  </style>
</head>
<body>
  <div class=\"row\">
    <div><strong>Adaptiv MCP</strong> – Tool Catalog</div>
    <div class=\"small\">Source: <a href=\"tools.json\">tools.json</a></div>
  </div>
  <div class=\"row\">
    <input id=\"q\" placeholder=\"Search tools…\" />
    <select id=\"mode\">
      <option value=\"all\">All</option>
      <option value=\"read\">Read</option>
      <option value=\"write\">Write</option>
    </select>
    <button id=\"refresh\">Refresh</button>
  </div>
  <div id=\"status\" class=\"small\"></div>
  <div id=\"grid\" class=\"grid\"></div>

<script>
const elQ = document.getElementById('q');
const elMode = document.getElementById('mode');
const elGrid = document.getElementById('grid');
const elStatus = document.getElementById('status');
const elRefresh = document.getElementById('refresh');

function badge(text){
  const s = document.createElement('span');
  s.className='badge';
  s.textContent=text;
  return s;
}

function toolBadges(t){
  const b = document.createElement('div');
  b.className='badges';
  const ann = t.annotations || {};
  const write = !!t.write_action;
  b.appendChild(badge(write ? 'WRITE' : 'READ'));
  if (ann.openWorldHint) b.appendChild(badge('OPEN WORLD'));
  if (t.visibility) b.appendChild(badge(String(t.visibility).toUpperCase()));
  if (t.invoking_message) b.appendChild(badge('INVOKING'));
  return b;
}

function card(t){
  const c = document.createElement('div');
  c.className='card';

  const name = document.createElement('div');
  name.className='name';
  name.textContent = t.name;
  c.appendChild(name);

  c.appendChild(toolBadges(t));

  const desc = document.createElement('div');
  desc.className='desc';
  desc.textContent = t.description || '';
  c.appendChild(desc);

  const meta = document.createElement('div');
  meta.className='meta';
  const kv = document.createElement('div');
  kv.className='kv';

  const ui = t.ui || {};
  if (ui.group) kv.appendChild(Object.assign(document.createElement('span'), {textContent: 'group=' + ui.group}));
  if (ui.icon) kv.appendChild(Object.assign(document.createElement('span'), {textContent: 'icon=' + ui.icon}));
  if (t.invoking_message) kv.appendChild(Object.assign(document.createElement('span'), {textContent: 'invoking=' + t.invoking_message}));
  if (t.invoked_message) kv.appendChild(Object.assign(document.createElement('span'), {textContent: 'invoked=' + t.invoked_message}));
  if (Array.isArray(t.tags) && t.tags.length) kv.appendChild(Object.assign(document.createElement('span'), {textContent: 'tags=' + t.tags.join(',')}));
  meta.appendChild(kv);
  c.appendChild(meta);

  return c;
}

function matchesMode(t){
  const mode = elMode.value;
  const ann = t.annotations || {};
  if (mode === 'all') return true;
  if (mode === 'read') return !t.write_action;
  if (mode === 'write') return !!t.write_action;
  return true;
}

function matchesQuery(t){
  const q = (elQ.value || '').trim().toLowerCase();
  if (!q) return true;
  const hay = [t.name, t.description, (t.tags||[]).join(' '), JSON.stringify(t.ui||{})].join(' ').toLowerCase();
  return hay.includes(q);
}

async function load(){
  elStatus.textContent = 'Loading…';
  const resp = await fetch('tools.json', {cache: 'no-store'});
  const data = await resp.json();
  const tools = (data.tools || []).slice();
  tools.sort((a,b)=>String(a.name).localeCompare(String(b.name)));
  const filtered = tools.filter(t=>matchesMode(t) && matchesQuery(t));
  elGrid.innerHTML = '';
  filtered.forEach(t=>elGrid.appendChild(card(t)));
  elStatus.textContent = `Showing ${filtered.length} / ${tools.length} tools.`;
}

elQ.addEventListener('input', ()=>load());
elMode.addEventListener('change', ()=>load());
elRefresh.addEventListener('click', ()=>load());
load();
</script>
</body>
</html>"""
        return Response(html, media_type="text/html")

    return _endpoint
