import inspect


def _params(fn) -> list[str]:
    return list(inspect.signature(fn).parameters)


def test_apply_workspace_operations_accepts_ops_alias() -> None:
    from github_mcp.workspace_tools.fs import apply_workspace_operations

    params = _params(apply_workspace_operations)
    assert "operations" in params
    assert "ops" in params


def test_workspace_apply_ops_and_open_pr_accepts_ops_alias() -> None:
    from github_mcp.workspace_tools.workflows import workspace_apply_ops_and_open_pr

    params = _params(workspace_apply_ops_and_open_pr)
    assert "operations" in params
    assert "ops" in params


def test_workspace_task_workflows_accept_ops_alias() -> None:
    from github_mcp.workspace_tools.task_workflows import workspace_task_apply_edits, workspace_task_execute

    assert "ops" in _params(workspace_task_apply_edits)
    assert "ops" in _params(workspace_task_execute)

