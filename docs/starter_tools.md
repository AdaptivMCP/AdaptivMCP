# Starter Tools: 10 Quick Wins

This page gives a fast preview of 10 useful Adaptiv MCP tools without needing to scan the full codebase.

Each item includes:
- **Tool name** (as exposed by the MCP server)
- **What it does**
- **Example prompt** you can give ChatGPT
- **Example output shape** (abbreviated)

---

## 1) `validate_environment`
**What it does:** Checks whether required tokens/config are present and whether major integrations are reachable.

**Example prompt:**
> Use `validate_environment` and summarize what I still need to configure.

**Example output (abbreviated):**
```json
{
  "ok": true,
  "github": { "configured": true, "status": "ok" },
  "render": { "configured": false, "status": "missing_token" },
  "workspace": { "base_dir": "/var/data/mcp-workspaces" }
}
```

## 2) `get_user_login`
**What it does:** Shows who the current GitHub token authenticates as.

**Example prompt:**
> Run `get_user_login` so I can confirm which GitHub identity is active.

**Example output (abbreviated):**
```json
{
  "status_code": 200,
  "login": "octocat",
  "account_type": "User"
}
```

## 3) `list_repositories`
**What it does:** Lists repositories visible to the authenticated identity.

**Example prompt:**
> Use `list_repositories` and show me the first 10 repos I can access.

**Example output (abbreviated):**
```json
{
  "status_code": 200,
  "json": [
    { "full_name": "org/api", "private": true, "default_branch": "main" },
    { "full_name": "org/web", "private": false, "default_branch": "main" }
  ]
}
```

## 4) `list_recent_issues`
**What it does:** Returns recent issues for a repository.

**Example prompt:**
> Use `list_recent_issues` for `org/api` and show open bugs from the last week.

**Example output (abbreviated):**
```json
{
  "status_code": 200,
  "json": [
    { "number": 421, "title": "Fix timeout in auth flow", "state": "open" },
    { "number": 419, "title": "Race in cache invalidation", "state": "open" }
  ]
}
```

## 5) `list_pull_requests`
**What it does:** Lists pull requests for a repository (open/closed/all).

**Example prompt:**
> Run `list_pull_requests` for `org/api` with `state="open"` and summarize risk areas.

**Example output (abbreviated):**
```json
{
  "status_code": 200,
  "json": [
    { "number": 198, "title": "Refactor billing retry logic", "draft": false },
    { "number": 197, "title": "Upgrade http client", "draft": true }
  ]
}
```

## 6) `ensure_workspace_clone`
**What it does:** Creates/refreshes a persistent local workspace mirror for a repo.

**Example prompt:**
> Use `ensure_workspace_clone` for `org/api` on `main`, then tell me whether it was newly created.

**Example output (abbreviated):**
```json
{
  "ref": "main",
  "reset": false,
  "created": true
}
```

## 7) `read_workspace_file_excerpt`
**What it does:** Reads a section of a file from the workspace mirror.

**Example prompt:**
> Use `read_workspace_file_excerpt` on `src/auth/service.py` lines 1-120 and highlight weak error handling.

**Example output (abbreviated):**
```json
{
  "path": "src/auth/service.py",
  "start_line": 1,
  "end_line": 120,
  "content": "1| from fastapi import ...\n2| ..."
}
```

## 8) `apply_workspace_operations`
**What it does:** Applies structured file edits (create/update/delete/replace) in the workspace mirror.

**Example prompt:**
> Use `apply_workspace_operations` to replace deprecated `requests` usage in `src/http/client.py` with `httpx`.

**Example output (abbreviated):**
```json
{
  "ok": true,
  "summary": { "files_updated": 1, "files_created": 0, "files_deleted": 0 },
  "operations": [
    { "op": "replace_text", "path": "src/http/client.py", "applied": true }
  ]
}
```

## 9) `terminal_command`
**What it does:** Runs a shell command inside the workspace mirror (great for tests/lint/build).

**Example prompt:**
> Run `terminal_command` with `pytest -q tests/test_auth.py` and explain any failures.

**Example output (abbreviated):**
```json
{
  "ok": true,
  "exit_code": 0,
  "stdout": "... 12 passed in 2.31s",
  "stderr": ""
}
```

## 10) `commit_and_open_pr_from_workspace`
**What it does:** Commits local workspace changes, pushes a branch, and opens a PR.

**Example prompt:**
> Use `commit_and_open_pr_from_workspace` with commit message "Fix auth timeout handling" and open a PR into `main`.

**Example output (abbreviated):**
```json
{
  "commit": { "sha": "abc123...", "message": "Fix auth timeout handling" },
  "pull_request": {
    "number": 205,
    "html_url": "https://github.com/org/api/pull/205",
    "state": "open"
  }
}
```

---

## Suggested first-run sequence
If you are brand new, this flow works well:
1. `validate_environment`
2. `get_user_login`
3. `list_repositories`
4. `ensure_workspace_clone`
5. `read_workspace_file_excerpt`
6. `apply_workspace_operations`
7. `terminal_command`
8. `commit_and_open_pr_from_workspace`

That sequence gives you a complete "inspect → edit → test → ship PR" loop.
