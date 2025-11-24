# main.py
# MCP Github Connector replacement implementing read/write/workflow functionality
#
# Endpoints:
#   GET  /                 - health check
#   POST /authorize_write_actions - return whether writes are authorized (auto-approve or PAT)
#   POST /commit_file      - create or update a file in a repo (supports content or content_url)
#   POST /create_branch    - create a new branch from existing ref
#   POST /create_pull_request - open a PR
#   POST /get_file_contents - fetch single file contents (decoded)
#   POST /fetch_files      - fetch multiple files concurrently (for ~500 files)
#   POST /fetch_url        - fetch arbitrary http(s) url (with safety check)
#   GET  /get_profile      - return authenticated user profile
#   POST /list_repositories - list repos (simple, paged)
#
# Environment variables:
#   GITHUB_PAT                - required for write operations
#   GITHUB_MCP_AUTO_APPROVE   - if "1" then /authorize_write_actions returns authorized
#   MAX_CONCURRENCY           - int, concurrency for fetch_files (default 40)
#   GITHUB_API_BASE           - optional override, default https://api.github.com
#   PORT                      - optional port (render will set)
#
# Push to repo and restart your Render service.

import os
import base64
import json
import logging
import asyncio
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import httpx

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-github")

# Config from env
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
AUTO_APPROVE = os.getenv("GITHUB_MCP_AUTO_APPROVE", "0") == "1"
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "40"))
GITHUB_API_BASE = os.getenv("GITHUB_API_BASE", "https://api.github.com")
TIMEOUT = int(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))

if not GITHUB_PAT:
    logger.warning("GITHUB_PAT not set. Write operations will fail until GITHUB_PAT is configured.")

app = FastAPI(title="Joeys GitHub MCP Connector (replacement)")

# Helper model types
class CommitFilePayload(BaseModel):
    repository_full_name: str
    path: str
    content: Optional[str] = None
    content_url: Optional[str] = None
    message: str
    branch: Optional[str] = "main"
    author: Optional[Dict[str,str]] = None  # {"name": "...", "email": "..."}

class CreateBranchPayload(BaseModel):
    repository_full_name: str
    new_branch: str
    from_branch: Optional[str] = "main"

class CreatePRPayload(BaseModel):
    repository_full_name: str
    title: str
    head: str  # branch name
    base: Optional[str] = "main"
    body: Optional[str] = ""

class GetFilePayload(BaseModel):
    repository_full_name: str
    path: str
    ref: Optional[str] = "main"

class FetchFilesPayload(BaseModel):
    repository_full_name: str
    paths: List[str]
    ref: Optional[str] = "main"

class FetchUrlPayload(BaseModel):
    url: str
    timeout_seconds: Optional[int] = 30

class ListReposPayload(BaseModel):
    page_size: Optional[int] = 50
    page: Optional[int] = 1

# auth headers
def gh_headers():
    if not GITHUB_PAT:
        return {}
    return {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "joeys-mcp-github-connector"
    }

async def gh_get(path: str, params: dict=None):
    url = f"{GITHUB_API_BASE.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(url, headers=gh_headers(), params=params)
    return resp

async def gh_post(path: str, data: dict):
    url = f"{GITHUB_API_BASE.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(url, headers=gh_headers(), json=data)
    return resp

async def gh_put(path: str, data: dict):
    url = f"{GITHUB_API_BASE.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.put(url, headers=gh_headers(), json=data)
    return resp

@app.get("/")
async def health():
    return {"status": "ok", "auto_approve": AUTO_APPROVE, "github_pat_provided": bool(GITHUB_PAT)}

@app.post("/authorize_write_actions")
async def authorize_write_actions():
    """
    Return authorization status for write actions. If GITHUB_MCP_AUTO_APPROVE=1, this returns authorized.
    Otherwise the client UI should call this and present an authorization flow.
    """
    if AUTO_APPROVE:
        return {"result": {"authorized": True, "reason": "auto_approve"}}
    if GITHUB_PAT:
        return {"result": {"authorized": True, "reason": "pat_present"}}
    return {"result": {"authorized": False, "reason": "no_github_pat"}}

# Utility to decode GitHub content result
def decode_github_content(github_item: dict) -> dict:
    # github_item may have 'content' base64
    if github_item.get("encoding") == "base64" and github_item.get("content") is not None:
        try:
            raw = base64.b64decode(github_item["content"]).decode("utf-8", errors="replace")
        except Exception:
            raw = base64.b64decode(github_item["content"]).decode("latin-1", errors="replace")
    else:
        raw = github_item.get("content")
    return {"path": github_item.get("path"), "content": raw, "sha": github_item.get("sha"), "url": github_item.get("html_url")}

@app.post("/get_file_contents")
async def get_file_contents(p: GetFilePayload):
    """Get a single file contents (decoded)"""
    path = p.path
    repo = p.repository_full_name
    ref = p.ref or "main"
    r = await gh_get(f"repos/{repo}/contents/{path}", params={"ref": ref})
    if r.status_code == 200:
        payload = r.json()
        return {"result": decode_github_content(payload)}
    elif r.status_code == 404:
        raise HTTPException(status_code=404, detail="File not found")
    else:
        logger.error("GitHub response: %s %s", r.status_code, r.text)
        raise HTTPException(status_code=500, detail=f"GitHub error: {r.status_code}")

@app.post("/fetch_files")
async def fetch_files(payload: FetchFilesPayload):
    """
    Fetch list of file paths concurrently. Returns array of {path, content, sha}.
    Tuned by MAX_CONCURRENCY env.
    """
    repo = payload.repository_full_name
    ref = payload.ref or "main"
    results = []

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async def fetch_one(path: str):
            async with sem:
                url = f"{GITHUB_API_BASE.rstrip('/')}/repos/{repo}/contents/{path}"
                resp = await client.get(url, headers=gh_headers(), params={"ref": ref})
                if resp.status_code == 200:
                    j = resp.json()
                    return decode_github_content(j)
                elif resp.status_code == 404:
                    return {"path": path, "error": "not_found"}
                else:
                    logger.warning("fetch_files: GitHub returned %s for %s", resp.status_code, path)
                    return {"path": path, "error": f"github_error_{resp.status_code}"}

        tasks = [fetch_one(p) for p in payload.paths]
        fetched = await asyncio.gather(*tasks, return_exceptions=False)
        results.extend(fetched)
    return {"result": results}

async def read_content_from_content_url(content_url: str) -> str:
    """
    content_url may be:
      - a local '/mnt/data/...' path (read from FS)
      - an http(s) URL (fetch)
      - direct content (this function will return as-is)
    """
    if content_url.startswith("/"):
        # local file
        try:
            with open(content_url, "rb") as f:
                data = f.read()
            # try utf-8
            try:
                return data.decode("utf-8")
            except Exception:
                return data.decode("latin-1")
        except Exception as e:
            raise RuntimeError(f"Failed to read local content_url: {e}")
    elif content_url.startswith("http://") or content_url.startswith("https://"):
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(content_url)
            if r.status_code != 200:
                raise RuntimeError(f"Failed to fetch content_url: {r.status_code}")
            # return text
            return r.text
    else:
        # treat as raw content
        return content_url

@app.post("/commit_file")
async def commit_file(p: CommitFilePayload):
    """
    Create or update a file in the repository.
    Uses the GitHub "create/update file contents" endpoint.
    Supports either direct 'content' or 'content_url' (local path or HTTP).
    """
    if not GITHUB_PAT:
        raise HTTPException(status_code=403, detail="Write operations require GITHUB_PAT")

    repo = p.repository_full_name
    branch = p.branch or "main"
    path = p.path
    message = p.message or "Update via MCP connector"

    # determine content
    if p.content is not None:
        raw_text = p.content
    elif p.content_url is not None:
        try:
            raw_text = await read_content_from_content_url(p.content_url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read content_url: {e}")
    else:
        raise HTTPException(status_code=400, detail="Either 'content' or 'content_url' must be provided.")

    # encode
    try:
        b64 = base64.b64encode(raw_text.encode("utf-8")).decode("ascii")
    except Exception:
        b64 = base64.b64encode(raw_text.encode("latin-1")).decode("ascii")

    # check if exists to get sha
    get_resp = await gh_get(f"repos/{repo}/contents/{path}", params={"ref": branch})
    sha = None
    if get_resp.status_code == 200:
        j = get_resp.json()
        sha = j.get("sha")
    elif get_resp.status_code == 404:
        sha = None
    else:
        logger.error("commit_file: failed to fetch existing file: %s %s", get_resp.status_code, get_resp.text)
        # continue: maybe we can still create

    put_data = {
        "message": message,
        "content": b64,
        "branch": branch
    }
    if p.author:
        put_data["committer"] = {"name": p.author.get("name"), "email": p.author.get("email")}

    if sha:
        put_data["sha"] = sha

    put_resp = await gh_put(f"repos/{repo}/contents/{path}", put_data)
    if put_resp.status_code in (200, 201):
        return {"result": put_resp.json()}
    else:
        logger.error("commit_file: GitHub PUT failed %s %s", put_resp.status_code, put_resp.text)
        raise HTTPException(status_code=500, detail=f"GitHub commit failed: {put_resp.status_code}: {put_resp.text}")

@app.post("/create_branch")
async def create_branch(p: CreateBranchPayload):
    if not GITHUB_PAT:
        raise HTTPException(status_code=403, detail="Write operations require GITHUB_PAT")
    repo = p.repository_full_name
    from_branch = p.from_branch or "main"
    new_branch = p.new_branch

    # get sha of from_branch
    ref_resp = await gh_get(f"repos/{repo}/git/ref/heads/{from_branch}")
    if ref_resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Could not find branch {from_branch}: {ref_resp.status_code}")
    sha = ref_resp.json()["object"]["sha"]
    create_data = {"ref": f"refs/heads/{new_branch}", "sha": sha}
    post_resp = await gh_post(f"repos/{repo}/git/refs", create_data)
    if post_resp.status_code in (201,):
        return {"result": post_resp.json()}
    elif post_resp.status_code == 422:
        # branch exists
        return {"result": {"message": "branch_exists", "details": post_resp.json()}}
    else:
        logger.error("create_branch failed: %s %s", post_resp.status_code, post_resp.text)
        raise HTTPException(status_code=500, detail=f"GitHub create ref failed: {post_resp.status_code}")

@app.post("/create_pull_request")
async def create_pull_request(p: CreatePRPayload):
    if not GITHUB_PAT:
        raise HTTPException(status_code=403, detail="Write operations require GITHUB_PAT")
    repo = p.repository_full_name
    data = {"title": p.title, "head": p.head, "base": p.base or "main", "body": p.body or ""}
    resp = await gh_post(f"repos/{repo}/pulls", data)
    if resp.status_code in (200, 201):
        return {"result": resp.json()}
    else:
        logger.error("create_pull_request failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=500, detail=f"GitHub create PR failed: {resp.status_code}: {resp.text}")

@app.post("/fetch_url")
async def fetch_url(payload: FetchUrlPayload):
    # Simple fetch with allowed schemes only
    url = payload.url
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Only http(s) URLs are supported.")
    timeout = payload.timeout_seconds or 30
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
    return {"status_code": resp.status_code, "headers": dict(resp.headers), "text": resp.text[:100000]}

@app.get("/get_profile")
async def get_profile():
    if not GITHUB_PAT:
        raise HTTPException(status_code=403, detail="GITHUB_PAT required for profile")
    r = await gh_get("user")
    if r.status_code == 200:
        return {"result": r.json()}
    else:
        logger.error("get_profile failed: %s %s", r.status_code, r.text)
        raise HTTPException(status_code=500, detail=f"GitHub profile failed: {r.status_code}")

@app.post("/list_repositories")
async def list_repositories(payload: ListReposPayload):
    page = payload.page or 1
    per_page = payload.page_size or 50
    r = await gh_get("user/repos", params={"per_page": per_page, "page": page})
    if r.status_code == 200:
        return {"result": r.json()}
    else:
        logger.error("list_repositories failed: %s %s", r.status_code, r.text)
        raise HTTPException(status_code=500, detail=f"GitHub list repos failed: {r.status_code}")

# Error handlers for debugging
@app.exception_handler(httpx.HTTPError)
async def httpx_exception_handler(request: Request, exc: httpx.HTTPError):
    logger.exception("HTTPX error: %s", exc)
    return HTTPException(status_code=500, detail=str(exc))

# Run instructions are handled by uvicorn on Render (uvicorn main:app --host 0.0.0.0 --port $PORT)
