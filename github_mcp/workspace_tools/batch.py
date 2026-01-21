"""High-level batch operations across multiple files, folders, and branches.

Adds a single orchestration tool, `workspace_batch`, that composes the existing
workspace tools to support:
- multi-file edits/replaces/deletes/moves (via apply_workspace_operations)
- multi-path delete/move (files OR folders)
- staging/unstaging
- diffs (staged or working tree)
- change summaries
- running tests
- committing and pushing
- doing the above across multiple branches in one call
"""

from __future__ import annotations

import shlex
from typing import Any

from github_mcp import config
from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import _structured_tool_error, mcp_tool
from github_mcp.utils import _normalize_timeout_seconds

from ._shared import _filter_kwargs_for_callable, _tw
from .commit import commit_workspace, commit_workspace_files, get_workspace_changes_summary
from .fs import apply_workspace_operations, delete_workspace_paths, move_workspace_paths
from .git_ops import workspace_create_branch, workspace_git_diff
from .suites import run_tests


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def _as_str(value: Any, default: str | None = None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_list_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


async def _remote_branch_exists(full_name: str, *, base_ref: str, branch: str) -> bool:
    """Check whether a branch exists on origin.

    Uses the repo mirror so this works even when direct API helpers are
    unavailable.
    """

    deps = _tw()._workspace_deps()
    effective_base = _tw()._effective_ref_for_repo(full_name, base_ref)
    repo_dir = await deps["clone_repo"](full_name, ref=effective_base, preserve_changes=True)
    t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)
    q_branch = shlex.quote(branch)

    res = await deps["run_shell"](
        f"git ls-remote --heads origin {q_branch}",
        cwd=repo_dir,
        timeout_seconds=t_default,
    )
    if res.get("exit_code", 0) != 0:
        stderr = res.get("stderr", "") or res.get("stdout", "")
        raise GitHubAPIError(f"Failed to check remote branches: {stderr}")
    return bool((res.get("stdout", "") or "").strip())


async def _stage_paths(full_name: str, *, ref: str, paths: list[str] | None) -> dict[str, Any]:
    deps = _tw()._workspace_deps()
    effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
    repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
    t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

    if paths is None:
        cmd = "git add -A"
    else:
        quoted = " ".join(shlex.quote(p) for p in paths if p.strip())
        cmd = f"git add -- {quoted}" if quoted else "git add -A"

    res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
    if res.get("exit_code", 0) != 0:
        stderr = res.get("stderr", "") or res.get("stdout", "")
        raise GitHubAPIError(f"git add failed: {stderr}")

    staged = await deps["run_shell"](
        "git diff --cached --name-only", cwd=repo_dir, timeout_seconds=t_default
    )
    staged_files = [ln for ln in (staged.get("stdout", "") or "").splitlines() if ln.strip()]

    return {"ref": effective_ref, "command": cmd, "staged_files": staged_files, "ok": True}


async def _unstage_paths(full_name: str, *, ref: str, paths: list[str] | None) -> dict[str, Any]:
    deps = _tw()._workspace_deps()
    effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
    repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
    t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

    if not paths:
        cmd = "git reset"
    else:
        quoted = " ".join(shlex.quote(p) for p in paths if p.strip())
        cmd = f"git reset -- {quoted}"

    res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
    if res.get("exit_code", 0) != 0:
        stderr = res.get("stderr", "") or res.get("stdout", "")
        raise GitHubAPIError(f"git reset failed: {stderr}")

    staged = await deps["run_shell"](
        "git diff --cached --name-only", cwd=repo_dir, timeout_seconds=t_default
    )
    staged_files = [ln for ln in (staged.get("stdout", "") or "").splitlines() if ln.strip()]

    return {"ref": effective_ref, "command": cmd, "staged_files": staged_files, "ok": True}


@mcp_tool(write_action=True)
async def workspace_batch(
    full_name: str,
    plans: list[dict[str, Any]],
    *,
    default_base_ref: str = "main",
    fail_fast: bool = True,
) -> dict[str, Any]:
    """Execute multiple workspace plans (across multiple branches).

    Each item in `plans` is a dict. Supported keys:

    Branch selection:
      - ref: str (required)
      - base_ref: str (optional; default is `default_base_ref`)
      - create_branch_if_missing: bool

    Content ops:
      - apply_ops: { operations: [...], preview_only?: bool }
        - operations schema matches `apply_workspace_operations` (write/replace_text/
          edit_range/delete_lines/delete_word/delete_chars/delete/move/apply_patch)

      - delete_paths: { paths: [...], allow_missing?: bool, allow_recursive?: bool }
      - move_paths:   { moves: [{src,dst},...], overwrite?: bool, create_parents?: bool }

    Git ops:
      - stage:   { paths?: [...] }    (omit `paths` to stage all)
      - unstage: { paths?: [...] }    (omit `paths` to unstage all)
      - diff:    { staged?: bool, paths?: [...], left_ref?: str, right_ref?: str,
                  context_lines?: int, max_chars?: int }
      - summary: { path_prefix?: str, max_files?: int }

    Quality:
      - tests: { command?: str, timeout_seconds?: float, workdir?: str,
                use_temp_venv?: bool, installing_dependencies?: bool }

    Commit:
      - commit: { message: str, push?: bool, add_all?: bool, files?: [...] }

    Returns per-plan outputs.
    """

    try:
        if not isinstance(full_name, str) or not full_name.strip():
            raise ValueError("full_name must be a non-empty string")
        if not isinstance(plans, list) or any(not isinstance(p, dict) for p in plans):
            raise TypeError("plans must be a list of dicts")
        if not plans:
            raise ValueError("plans must contain at least one plan")

        out_plans: list[dict[str, Any]] = []

        for idx, plan in enumerate(plans):
            ref = _as_str(plan.get("ref"))
            if not ref:
                out_plans.append(
                    {"index": idx, "status": "error", "ok": False, "error": "plan.ref is required"}
                )
                if fail_fast:
                    break
                continue

            base_ref = _as_str(plan.get("base_ref"), default_base_ref) or default_base_ref
            create_if_missing = _as_bool(plan.get("create_branch_if_missing"), False)

            steps: dict[str, Any] = {}

            if create_if_missing:
                exists = await _remote_branch_exists(full_name, base_ref=base_ref, branch=ref)
                steps["branch_exists"] = {"ref": ref, "exists": exists}
                if not exists:
                    extra_branch = plan.get("create_branch_args")
                    extra_branch = extra_branch if isinstance(extra_branch, dict) else {}
                    extra_branch = dict(extra_branch)
                    for k in ("full_name", "base_ref", "new_branch"):
                        extra_branch.pop(k, None)
                    branch_call = {
                        "full_name": full_name,
                        "base_ref": base_ref,
                        "new_branch": ref,
                        "push": True,
                        **extra_branch,
                    }
                    steps["create_branch"] = await workspace_create_branch(
                        **_filter_kwargs_for_callable(workspace_create_branch, branch_call)
                    )

            if isinstance(plan.get("apply_ops"), dict):
                ao = plan["apply_ops"]
                operations = ao.get("operations")
                if operations is None:
                    raise ValueError("apply_ops.operations is required when apply_ops is provided")
                extra = dict(ao)
                for k in ("full_name", "ref"):
                    extra.pop(k, None)
                extra.setdefault("fail_fast", True)
                extra.setdefault("rollback_on_error", True)
                extra.setdefault("preview_only", _as_bool(ao.get("preview_only"), False))
                extra.setdefault("create_parents", True)
                call = {"full_name": full_name, "ref": ref, **extra}
                steps["apply_ops"] = await apply_workspace_operations(
                    **_filter_kwargs_for_callable(apply_workspace_operations, call)
                )

            if isinstance(plan.get("delete_paths"), dict):
                dp = plan["delete_paths"]
                paths = _as_list_str(dp.get("paths"))
                if not paths:
                    raise ValueError("delete_paths.paths must be a non-empty list")
                extra = dict(dp)
                for k in ("full_name", "ref"):
                    extra.pop(k, None)
                extra["paths"] = paths
                extra.setdefault("allow_missing", _as_bool(dp.get("allow_missing"), True))
                extra.setdefault("allow_recursive", _as_bool(dp.get("allow_recursive"), True))
                call = {"full_name": full_name, "ref": ref, **extra}
                steps["delete_paths"] = await delete_workspace_paths(
                    **_filter_kwargs_for_callable(delete_workspace_paths, call)
                )

            if isinstance(plan.get("move_paths"), dict):
                mp = plan["move_paths"]
                raw_moves = mp.get("moves")
                if not isinstance(raw_moves, list) or any(
                    not isinstance(m, dict) for m in raw_moves
                ):
                    raise TypeError("move_paths.moves must be a list of {src,dst} objects")
                moves: list[dict[str, str]] = []
                for m in raw_moves:
                    src = _as_str(m.get("src"))
                    dst = _as_str(m.get("dst"))
                    if not src or not dst:
                        raise ValueError("move_paths.moves entries must include src and dst")
                    moves.append({"src": src, "dst": dst})

                extra = dict(mp)
                for k in ("full_name", "ref"):
                    extra.pop(k, None)
                extra["moves"] = moves
                extra.setdefault("overwrite", _as_bool(mp.get("overwrite"), False))
                extra.setdefault("create_parents", _as_bool(mp.get("create_parents"), True))
                call = {"full_name": full_name, "ref": ref, **extra}
                steps["move_paths"] = await move_workspace_paths(
                    **_filter_kwargs_for_callable(move_workspace_paths, call)
                )

            if isinstance(plan.get("stage"), dict):
                st = plan["stage"]
                raw = st.get("paths")
                stage_paths = None if raw is None else _as_list_str(raw)
                steps["stage"] = await _stage_paths(full_name, ref=ref, paths=stage_paths)

            if isinstance(plan.get("unstage"), dict):
                ust = plan["unstage"]
                raw = ust.get("paths")
                unstage_paths = None if raw is None else _as_list_str(raw)
                steps["unstage"] = await _unstage_paths(full_name, ref=ref, paths=unstage_paths)

            if isinstance(plan.get("diff"), dict):
                df = plan["diff"]
                extra = dict(df)
                for k in ("full_name", "ref"):
                    extra.pop(k, None)
                extra.setdefault("left_ref", _as_str(df.get("left_ref")))
                extra.setdefault("right_ref", _as_str(df.get("right_ref")))
                extra.setdefault("staged", _as_bool(df.get("staged"), False))
                extra.setdefault("paths", _as_list_str(df.get("paths")) or None)
                extra.setdefault("context_lines", _as_int(df.get("context_lines"), 3))
                extra.setdefault("max_chars", _as_int(df.get("max_chars"), 200_000))
                call = {"full_name": full_name, "ref": ref, **extra}
                steps["diff"] = await workspace_git_diff(
                    **_filter_kwargs_for_callable(workspace_git_diff, call)
                )

            if isinstance(plan.get("summary"), dict):
                sm = plan["summary"]
                extra = dict(sm)
                for k in ("full_name", "ref"):
                    extra.pop(k, None)
                extra.setdefault("path_prefix", _as_str(sm.get("path_prefix")))
                extra.setdefault("max_files", _as_int(sm.get("max_files"), 200))
                call = {"full_name": full_name, "ref": ref, **extra}
                steps["summary"] = await get_workspace_changes_summary(
                    **_filter_kwargs_for_callable(get_workspace_changes_summary, call)
                )

            if isinstance(plan.get("tests"), dict):
                ts = plan["tests"]
                cmd = _as_str(ts.get("test_command")) or _as_str(ts.get("command")) or "pytest -q"
                extra = dict(ts)
                for k in ("full_name", "ref"):
                    extra.pop(k, None)
                extra.setdefault("test_command", cmd)
                extra.setdefault("timeout_seconds", float(ts.get("timeout_seconds") or 0))
                extra.setdefault("workdir", _as_str(ts.get("workdir")))
                extra.setdefault("use_temp_venv", _as_bool(ts.get("use_temp_venv"), True))
                extra.setdefault(
                    "installing_dependencies", _as_bool(ts.get("installing_dependencies"), True)
                )
                call = {"full_name": full_name, "ref": ref, **extra}
                steps["tests"] = await run_tests(**_filter_kwargs_for_callable(run_tests, call))

            if isinstance(plan.get("commit"), dict):
                cm = plan["commit"]
                message = _as_str(cm.get("message")) or _as_str(cm.get("commit_message"))
                if not message:
                    raise ValueError("commit.message must be a non-empty string")

                push = _as_bool(cm.get("push"), True)
                add_all = _as_bool(cm.get("add_all"), True)
                files = _as_list_str(cm.get("files"))

                extra = dict(cm)
                for k in ("full_name", "ref", "branch"):
                    extra.pop(k, None)
                if files:
                    call = {
                        "full_name": full_name,
                        "files": files,
                        "ref": ref,
                        "message": message,
                        "push": push,
                        **extra,
                    }
                    steps["commit"] = await commit_workspace_files(
                        **_filter_kwargs_for_callable(commit_workspace_files, call)
                    )
                else:
                    call = {
                        "full_name": full_name,
                        "ref": ref,
                        "message": message,
                        "add_all": add_all,
                        "push": push,
                        **extra,
                    }
                    steps["commit"] = await commit_workspace(
                        **_filter_kwargs_for_callable(commit_workspace, call)
                    )

            ok = True
            for v in steps.values():
                if isinstance(v, dict) and v.get("status") == "error":
                    ok = False
                    break

            out_plans.append(
                {
                    "index": idx,
                    "ref": ref,
                    "ok": ok,
                    "status": "ok" if ok else "partial",
                    "steps": steps,
                }
            )

            if fail_fast and not ok:
                break

        overall_ok = all(p.get("ok") for p in out_plans if isinstance(p, dict))
        return {
            "status": "ok" if overall_ok else "partial",
            "ok": overall_ok,
            "full_name": full_name,
            "plans": out_plans,
        }

    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_batch")
