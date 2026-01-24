from __future__ import annotations

from typing import Any

from ._main import _main


async def pr_smoke_test(
    full_name: str | None = None,
    base_branch: str | None = None,
    draft: bool = True,
) -> dict[str, Any]:
    """Create a trivial branch with a one-line change and open a draft PR.

    This is intended for diagnostics of PR tooling in the live environment.
    """

    m = _main()

    defaults = await m.get_repo_defaults(full_name=full_name)
    defaults_payload = defaults.get("defaults") or {}
    repo = defaults_payload.get("full_name") or full_name or m.CONTROLLER_REPO
    base = (
        base_branch
        or defaults_payload.get("default_branch")
        or m.CONTROLLER_DEFAULT_BRANCH
    )

    import uuid

    branch = f"mcp-pr-smoke-{uuid.uuid4().hex[:8]}"

    await m.ensure_branch(full_name=repo, branch=branch, from_ref=base)

    path = "mcp_pr_smoke_test.txt"
    normalized_path = m._normalize_repo_path(path)
    content = f"MCP PR smoke test branch {branch}.\n"

    await m.apply_text_update_and_commit(
        full_name=repo,
        path=normalized_path,
        updated_content=content,
        branch=branch,
        message=f"MCP PR smoke test on {branch}",
    )

    pr = await m.create_pull_request(
        full_name=repo,
        title=f"MCP PR smoke test ({branch})",
        head=branch,
        base=base,
        body="Automated MCP PR smoke test created by pr_smoke_test.",
        draft=draft,
    )

    pr_json = pr.get("json") or {}
    if not isinstance(pr_json, dict) or not pr_json.get("number"):
        return {
            "status": "error",
            "ok": False,
            "repository": repo,
            "base": base,
            "branch": branch,
            "raw_response": pr,
        }

    return {
        "status": "ok",
        "repository": repo,
        "base": base,
        "branch": branch,
        "pr_number": pr_json.get("number"),
        "pr_url": pr_json.get("html_url"),
    }
