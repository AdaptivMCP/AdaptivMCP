from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ._main import _main


def _strip_heads_prefix(ref: str) -> str:
    """Normalize common git ref prefixes for branch-like inputs."""

    cleaned = (ref or "").strip()
    for prefix in ("refs/heads/", "heads/"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :]
    return cleaned


def _parse_head_ref(head: str) -> tuple[Optional[str], str]:
    """Parse a PR head ref.

 Returns (owner, branch). Owner is None when the head is unqualified.

 GitHub accepts:
 - "branch" for same-repo PRs
 - "owner:branch" for fork PRs
 """

    cleaned = _strip_heads_prefix(head)
    if ":" in cleaned:
        owner, branch = cleaned.split(":", 1)
        return (owner.strip() or None, _strip_heads_prefix(branch))
    return (None, cleaned)


def _head_for_api(head: str) -> str:
    owner, branch = _parse_head_ref(head)
    return f"{owner}:{branch}" if owner else branch


def _head_branch_only(head: str) -> str:
    """Return the branch portion of a head ref (suitable for Actions filters)."""

    _owner, branch = _parse_head_ref(head)
    return branch


async def list_pull_requests(
    full_name: str,
    state: str = "open",
    head: Optional[str] = None,
    base: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List pull requests with optional head/base filters."""

    allowed_states = {"open", "closed", "all"}
    if state not in allowed_states:
        raise ValueError("state must be 'open', 'closed', or 'all'")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    m = _main()
    params: Dict[str, Any] = {"state": state, "per_page": per_page, "page": page}
    if head:
        params["head"] = head
    if base:
        params["base"] = base
    return await m._github_request("GET", f"/repos/{full_name}/pulls", params=params)


async def merge_pull_request(
    full_name: str,
    number: int,
    merge_method: str = "squash",
    commit_title: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge a pull request."""

    allowed_methods = {"merge", "squash", "rebase"}
    if merge_method not in allowed_methods:
        raise ValueError("merge_method must be 'merge', 'squash', or 'rebase'")

    m = _main()
    payload: Dict[str, Any] = {"merge_method": merge_method}
    if commit_title is not None:
        payload["commit_title"] = commit_title
    if commit_message is not None:
        payload["commit_message"] = commit_message
    return await m._github_request(
        "PUT",
        f"/repos/{full_name}/pulls/{number}/merge",
        json_body=payload,
    )


async def close_pull_request(full_name: str, number: int) -> Dict[str, Any]:
    """Close a pull request without merging."""

    m = _main()
    return await m._github_request(
        "PATCH",
        f"/repos/{full_name}/pulls/{number}",
        json_body={"state": "closed"},
    )


async def comment_on_pull_request(full_name: str, number: int, body: str) -> Dict[str, Any]:
    """Post a comment on a pull request (issue API under the hood)."""

    m = _main()
    return await m._github_request(
        "POST",
        f"/repos/{full_name}/issues/{number}/comments",
        json_body={"body": body},
    )


async def fetch_pr(full_name: str, pull_number: int) -> Dict[str, Any]:
    """Fetch pull request details."""

    m = _main()
    return await m._github_request("GET", f"/repos/{full_name}/pulls/{pull_number}")


async def get_pr_info(full_name: str, pull_number: int) -> Dict[str, Any]:
    """Get metadata for a pull request."""

    data = await fetch_pr(full_name, pull_number)
    pr = data.get("json") or {}
    if isinstance(pr, dict):
        summary = {
            "title": pr.get("title"),
            "state": pr.get("state"),
            "draft": pr.get("draft"),
            "merged": pr.get("merged"),
            "user": pr.get("user", {}).get("login") if isinstance(pr.get("user"), dict) else None,
            "head": pr.get("head", {}).get("ref") if isinstance(pr.get("head"), dict) else None,
            "base": pr.get("base", {}).get("ref") if isinstance(pr.get("base"), dict) else None,
        }
    else:
        summary = None
    return {"status_code": data.get("status_code"), "summary": summary, "pr": pr}


async def fetch_pr_comments(
    full_name: str, pull_number: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    """Fetch issue-style comments for a pull request."""

    m = _main()
    params = {"per_page": per_page, "page": page}
    return await m._github_request(
        "GET", f"/repos/{full_name}/issues/{pull_number}/comments", params=params
    )


async def list_pr_changed_filenames(
    full_name: str, pull_number: int, per_page: int = 100, page: int = 1
) -> Dict[str, Any]:
    """List files changed in a pull request."""

    m = _main()
    params = {"per_page": per_page, "page": page}
    return await m._github_request(
        "GET", f"/repos/{full_name}/pulls/{pull_number}/files", params=params
    )


async def get_commit_combined_status(full_name: str, ref: str) -> Dict[str, Any]:
    """Get combined status for a commit or ref."""

    m = _main()
    return await m._github_request("GET", f"/repos/{full_name}/commits/{ref}/status")


async def _build_default_pr_body(
    *,
    full_name: str,
    title: str,
    head: str,
    effective_base: str,
    draft: bool,
) -> str:
    """Compose a rich default PR body when the caller omits one.

 This helper intentionally favors robustness over strictness: if any of the
 underlying GitHub lookups fail, it falls back to partial information instead
 of raising and breaking the overall tool call.
 """

    lines: List[str] = []
    head_branch = _head_branch_only(head)

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Title: {title}")
    lines.append(f"- From: `{head}` → `{effective_base}`")
    lines.append(f"- Status: {'Draft (still in progress)' if draft else 'Ready for review'}")
    lines.append("")

    # Change summary
    lines.append("## Change summary")
    lines.append("")
    lines.append("- See the PR *Files changed* tab for the authoritative change list.")
    lines.append("")

    # CI & quality: look at recent workflow runs on this branch.
    lines.append("## CI & quality")
    lines.append("")
    # Intentionally do not call other tools here: PR creation should remain
    # reliable even when workflow endpoints are unavailable or the head is
    # qualified (e.g. forks).
    lines.append(f"- CI: check GitHub Actions for branch `{head_branch}`.")

    lines.append("")
    lines.append("## Testing")
    lines.append("")
    lines.append("- [ ] `pytest`")
    lines.append("- [ ] Additional checks")
    lines.append("- [ ] Not run (explain why)")
    lines.append("")

    lines.append("## Risks & rollout")
    lines.append("")
    lines.append("- Risk level: low/medium/high")
    lines.append("- Rollback plan: describe how to revert if needed.")
    lines.append("")

    lines.append("## Reviewer checklist")
    lines.append("")
    lines.append("- [ ] Code style and readability")
    lines.append("- [ ] Tests cover the main paths")
    lines.append("- [ ] Breaking changes are documented")
    lines.append("- [ ] CI is green or issues are understood")
    lines.append("")

    lines.append("<!-- Default PR body generated by chatgpt-mcp-github. Edit freely. -->")

    return "\n".join(lines)


async def create_pull_request(
    full_name: str,
    title: str,
    head: str,
    base: str = "main",
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """Open a pull request from ``head`` into ``base``.

 The base branch is normalized via ``_effective_ref_for_repo`` so that
 controller repos honor the configured default branch even when callers
 supply a simple base name like "main".
 """

    m = _main()

    try:
        effective_base = m._effective_ref_for_repo(full_name, base)

        normalized_head = _head_for_api(head)
        effective_body = body
        if effective_body is None or not str(effective_body).strip():
            try:
                effective_body = await _build_default_pr_body(
                    full_name=full_name,
                    title=title,
                    head=normalized_head,
                    effective_base=effective_base,
                    draft=draft,
                )
            except Exception:
                # If the helper fails for any reason, fall back to whatever the
                # caller provided (including None) instead of blocking PR
                # creation entirely.
                effective_body = body

        payload: Dict[str, Any] = {
            "title": title,
            "head": normalized_head,
            "base": effective_base,
            "draft": draft,
        }
        if effective_body is not None:
            payload["body"] = effective_body

        return await m._github_request(
            "POST",
            f"/repos/{full_name}/pulls",
            json_body=payload,
        )
    except Exception as exc:
        # Include a lightweight path-style hint so callers can see which
        # repository and head/base pair failed without scraping the message.
        path_hint = f"{full_name} {head}->{base}"
        return m._structured_tool_error(
            exc,
            context="create_pull_request",
            path=path_hint,
        )


async def open_pr_for_existing_branch(
    full_name: str,
    branch: str,
    base: str = "main",
    title: Optional[str] = None,
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """Open a pull request for an existing branch into a base branch.

 This helper is intentionally idempotent: if there is already an open PR for
 the same head/base pair, it will return that existing PR instead of failing
 or creating a duplicate.

 If this tool call fails in the hosted environment, use the workspace flow: `terminal_command` to create or reuse the PR.
 """

    m = _main()

    # Resolve the effective base branch using the same logic as other helpers.
    effective_base = m._effective_ref_for_repo(full_name, base)
    pr_title = title or f"{branch} -> {effective_base}"

    # GitHub's API expects the head in the form "owner:branch" when used
    # with the head filter on the pulls listing endpoint.
    owner, _repo = full_name.split("/", 1)
    branch_owner, branch_name = _parse_head_ref(branch)
    head_ref = f"{branch_owner}:{branch_name}" if branch_owner else f"{owner}:{branch_name}"

    # 1) Try creating the PR first. This avoids an extra network call and
    # tends to be more reliable in hosted environments where listing endpoints
    # can intermittently stall.
    pr = await create_pull_request(
        full_name=full_name,
        title=pr_title,
        head=head_ref,
        base=effective_base,
        body=body,
        draft=draft,
    )

    pr_json = pr.get("json") or {}
    if isinstance(pr_json, dict) and pr_json.get("number"):
        return {
            "status": "ok",
            "pull_request": pr_json,
            "pr_number": pr_json.get("number"),
            "pr_url": pr_json.get("html_url"),
        }

    # If PR creation failed, `create_pull_request` returns a structured error
    # dict rather than raising. If it's a "PR already exists" conflict, fall
    # back to listing and reuse the existing PR.
    raw_error = pr.get("error") if isinstance(pr, dict) else None
    raw_message = ""
    if isinstance(raw_error, dict):
        raw_message = str(raw_error.get("message") or "")
    status_code = None
    raw_resp = None
    if isinstance(pr, dict):
        raw_resp = pr.get("raw_response") or pr.get("raw_response_payload")
    if isinstance(raw_resp, dict):
        status_code = raw_resp.get("status_code")

    error_hint_parts: List[str] = []
    if raw_message:
        error_hint_parts.append(raw_message)
    if isinstance(raw_resp, dict):
        raw_json = raw_resp.get("json")
        if isinstance(raw_json, dict):
            errors = raw_json.get("errors")
            if isinstance(errors, list):
                for entry in errors:
                    if isinstance(entry, dict):
                        msg = entry.get("message")
                        if isinstance(msg, str) and msg.strip():
                            error_hint_parts.append(msg)

    conflict_hint = "\n".join(error_hint_parts).lower()

    is_existing_pr_conflict = bool(
        status_code == 422
        and (
            "already exists" in conflict_hint
            or "a pull request already exists" in conflict_hint
            or "pull request already exists" in conflict_hint
        )
    )
    is_no_commits_conflict = bool(status_code == 422 and "no commits between" in conflict_hint)

    if not (is_existing_pr_conflict or is_no_commits_conflict):
        return {
            "status": "error",
            "raw_response": pr,
            "message": "create_pull_request did not return a PR document with a number",
        }

    # 2) The create attempt indicates we should look for an existing PR.
    existing_json: Any = []
    try:
        existing_resp = await m.list_pull_requests(
            full_name,
            state="open",
            head=head_ref,
            base=effective_base,
            per_page=10,
            page=1,
        )
        existing_json = existing_resp.get("json") or []
    except Exception as exc:
        return m._structured_tool_error(
            exc,
            context="open_pr_for_existing_branch:list_pull_requests",
            path=f"{full_name} {head_ref}->{effective_base}",
        )

    if isinstance(existing_json, list) and existing_json:
        pr_obj = existing_json[0]
        if isinstance(pr_obj, dict):
            return {
                "status": "ok",
                "reused_existing": True,
                "pull_request": pr_obj,
                "pr_number": pr_obj.get("number"),
                "pr_url": pr_obj.get("html_url"),
            }
        return {
            "status": "error",
            "message": "Existing PR listing returned a non-dict entry",
            "raw_entry": pr_obj,
        }

    if is_no_commits_conflict:
        # GitHub returns 422 when the head is identical to the base. Treat this
        # as a no-op rather than a hard error so callers can remain idempotent.
        return {
            "status": "ok",
            "noop": True,
            "reason": "no_commits_between_branches",
            "message": f"No commits between {effective_base} and {branch_name}; nothing to open as a PR.",
            "raw_response": pr,
        }

    return {
        "status": "error",
        "message": "PR creation reported an existing-PR conflict, but no matching open PR was found.",
        "raw_response": pr,
    }


async def update_files_and_open_pr(
    full_name: str,
    title: str,
    files: List[Dict[str, Any]],
    base_branch: str = "main",
    new_branch: Optional[str] = None,
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """Commit multiple files, verify each, then open a PR in one call."""

    m = _main()

    current_path: Optional[str] = None
    try:
        effective_base = m._effective_ref_for_repo(full_name, base_branch)

        if not files:
            raise ValueError("files must contain at least one item")

        # 1) Ensure a dedicated branch exists
        branch = new_branch or f"ally-{os.urandom(4).hex()}"
        await m.ensure_branch(full_name, branch, from_ref=effective_base)

        commit_results: List[Dict[str, Any]] = []
        verifications: List[Dict[str, Any]] = []

        # 2) Commit each file, with verification
        for f in files:
            current_path = f.get("path")
            if not current_path:
                raise ValueError("Each file dict must include a 'path' key")

            file_message = f.get("message") or title
            file_content = f.get("content")
            file_content_url = f.get("content_url")

            if file_content is None and file_content_url is None:
                raise ValueError(
                    f"File entry for {current_path!r} must specify "
                    "either 'content' or 'content_url'"
                )
            if file_content is not None and file_content_url is not None:
                raise ValueError(
                    f"File entry for {current_path!r} may not specify both "
                    "'content' and 'content_url'"
                )

            # Load content
            if file_content_url is not None:
                try:
                    body_bytes = await m._load_body_from_content_url(
                        file_content_url,
                        context=(f"update_files_and_open_pr({full_name}/{current_path})"),
                    )
                except Exception as exc:
                    return m._structured_tool_error(
                        exc,
                        context="update_files_and_open_pr.load_content",
                        path=current_path,
                    )
            else:
                body_bytes = file_content.encode("utf-8")

            # Resolve SHA and commit
            try:
                sha = await m._resolve_file_sha(full_name, current_path, branch)
                commit_result = await m._perform_github_commit(
                    full_name=full_name,
                    path=current_path,
                    message=file_message,
                    branch=branch,
                    body_bytes=body_bytes,
                    sha=sha,
                )
            except Exception as exc:
                return m._structured_tool_error(
                    exc,
                    context="update_files_and_open_pr.commit_file",
                    path=current_path,
                )

            commit_results.append(
                {
                    "path": current_path,
                    "message": file_message,
                    "result": commit_result,
                }
            )

            # Post-commit verification for this file
            try:
                verification = await m._verify_file_on_branch(full_name, current_path, branch)
            except Exception as exc:
                return m._structured_tool_error(
                    exc,
                    context="update_files_and_open_pr.verify_file",
                    path=current_path,
                )

            verifications.append(verification)

        # 3) Open the PR
        try:
            pr = await create_pull_request(
                full_name=full_name,
                title=title,
                head=branch,
                base=effective_base,
                body=body,
                draft=draft,
            )
        except Exception as exc:
            return m._structured_tool_error(
                exc, context="update_files_and_open_pr.create_pr", path=current_path
            )

        return {
            "branch": branch,
            "pull_request": pr,
            "commits": commit_results,
            "verifications": verifications,
        }

    except Exception as exc:
        return m._structured_tool_error(exc, context="update_files_and_open_pr", path=current_path)


async def get_pr_overview(full_name: str, pull_number: int) -> Dict[str, Any]:
    """Return a compact overview of a pull request, including files and CI status."""

    m = _main()

    pr_resp = await m.fetch_pr(full_name, pull_number)
    pr_json = pr_resp.get("json") or {}
    if not isinstance(pr_json, dict):
        pr_json = {}

    def _get_user(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        login = raw.get("login")
        if not isinstance(login, str):
            return None
        return {"login": login, "html_url": raw.get("html_url")}

    pr_summary: Dict[str, Any] = {
        "number": pr_json.get("number"),
        "title": pr_json.get("title"),
        "state": pr_json.get("state"),
        "draft": pr_json.get("draft"),
        "merged": pr_json.get("merged"),
        "html_url": pr_json.get("html_url"),
        "user": _get_user(pr_json.get("user")),
        "created_at": pr_json.get("created_at"),
        "updated_at": pr_json.get("updated_at"),
        "closed_at": pr_json.get("closed_at"),
        "merged_at": pr_json.get("merged_at"),
    }

    files: List[Dict[str, Any]] = []
    try:
        files_resp = await m.list_pr_changed_filenames(full_name, pull_number, per_page=100)
        files_json = files_resp.get("json") or []
        if isinstance(files_json, list):
            for f in files_json:
                if not isinstance(f, dict):
                    continue
                files.append(
                    {
                        "filename": f.get("filename"),
                        "status": f.get("status"),
                        "additions": f.get("additions"),
                        "deletions": f.get("deletions"),
                        "changes": f.get("changes"),
                    }
                )
    except Exception:
        files = []

    status_checks: Optional[Dict[str, Any]] = None
    head = pr_json.get("head")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    if isinstance(head_sha, str):
        try:
            status_resp = await m.get_commit_combined_status(full_name, head_sha)
            status_checks = status_resp.get("json") or {}
        except Exception:
            status_checks = None

    workflow_runs: List[Dict[str, Any]] = []
    head_ref = head.get("ref") if isinstance(head, dict) else None
    if isinstance(head_ref, str):
        try:
            runs_resp = await m.list_workflow_runs(
                full_name,
                branch=head_ref,
                per_page=5,
                page=1,
            )
            runs_json = runs_resp.get("json") or {}
            raw_runs = runs_json.get("workflow_runs", []) if isinstance(runs_json, dict) else []
            for run in raw_runs:
                if not isinstance(run, dict):
                    continue
                workflow_runs.append(
                    {
                        "id": run.get("id"),
                        "name": run.get("name"),
                        "event": run.get("event"),
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "head_branch": run.get("head_branch"),
                        "head_sha": run.get("head_sha"),
                        "html_url": run.get("html_url"),
                        "created_at": run.get("created_at"),
                        "updated_at": run.get("updated_at"),
                    }
                )
        except Exception:
            workflow_runs = []

    return {
        "repository": full_name,
        "pull_number": pull_number,
        "pr": pr_summary,
        "files": files,
        "status_checks": status_checks,
        "workflow_runs": workflow_runs,
    }


async def recent_prs_for_branch(
    full_name: str,
    branch: str,
    include_closed: bool = False,
    per_page_open: int = 20,
    per_page_closed: int = 5,
) -> Dict[str, Any]:
    """Return recent pull requests associated with a branch, grouped by state."""

    m = _main()

    if not full_name or "/" not in full_name:
        raise ValueError("full_name must be of the form 'owner/repo'")
    if not branch:
        raise ValueError("branch must be a non-empty string")

    owner, _repo = full_name.split("/", 1)
    branch_owner, branch_name = _parse_head_ref(branch)
    head_filter = f"{branch_owner}:{branch_name}" if branch_owner else f"{owner}:{branch_name}"

    normalize = getattr(m, "_normalize_pr_payload", None)

    open_resp = await m.list_pull_requests(
        full_name=full_name,
        state="open",
        head=head_filter,
        per_page=per_page_open,
        page=1,
    )
    open_raw = open_resp.get("json") or []
    if callable(normalize):
        open_prs = [normalize(pr) for pr in open_raw if isinstance(pr, dict)]
    else:
        open_prs = [pr for pr in open_raw if isinstance(pr, dict)]
    open_prs = [pr for pr in open_prs if pr is not None]

    closed_prs: List[Dict[str, Any]] = []
    if include_closed:
        closed_resp = await m.list_pull_requests(
            full_name=full_name,
            state="closed",
            head=head_filter,
            per_page=per_page_closed,
            page=1,
        )
        closed_raw = closed_resp.get("json") or []
        if callable(normalize):
            closed_prs = [normalize(pr) for pr in closed_raw if isinstance(pr, dict)]
        else:
            closed_prs = [pr for pr in closed_raw if isinstance(pr, dict)]
        closed_prs = [pr for pr in closed_prs if pr is not None]

    return {
        "full_name": full_name,
        "branch": branch,
        "head_filter": head_filter,
        "open": open_prs,
        "closed": closed_prs,
    }
