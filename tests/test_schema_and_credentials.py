from __future__ import annotations

import asyncio
import types


def test_schema_for_callable_handles_uninspectable_callable() -> None:
    from github_mcp.mcp_server.schemas import _schema_for_callable

    schema = _schema_for_callable(object(), None, tool_name="dummy")
    assert schema.get("type") == "object"
    assert isinstance(schema.get("properties"), dict)


def test_schema_for_callable_jsonable_tool_schema() -> None:
    from github_mcp.mcp_server.schemas import _schema_for_callable

    tool_obj = types.SimpleNamespace(
        input_schema={"type": "object", "properties": {"x": {"examples": {1, 2}}}},
    )
    schema = _schema_for_callable(object(), tool_obj, tool_name="dummy")
    examples = schema.get("properties", {}).get("x", {}).get("examples")
    assert isinstance(examples, list)
    assert set(examples) == {1, 2}


def test_cmd_invokes_git_detects_wrapped_git_commands() -> None:
    from github_mcp.workspace_tools._shared import _cmd_invokes_git

    assert _cmd_invokes_git("git status")
    assert _cmd_invokes_git("GIT_SSH_COMMAND=ssh git fetch origin")
    assert _cmd_invokes_git("env GIT_SSH_COMMAND=ssh git fetch origin")
    assert _cmd_invokes_git("sudo git status")
    assert not _cmd_invokes_git("echo git status")


def test_workspace_deps_injects_git_auth_env(monkeypatch) -> None:
    import main
    from github_mcp.workspace_tools import _shared

    calls: list[dict[str, str]] = []

    async def _stub_run_shell(
        cmd: str,
        *,
        cwd: str | None = None,
        timeout_seconds: int = 0,
        env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        calls.append(env or {})
        return {"exit_code": 0}

    monkeypatch.setattr(main, "_run_shell", _stub_run_shell)
    monkeypatch.setattr(_shared, "_git_auth_env", lambda: {"GIT_HTTP_EXTRAHEADER": "auth"})

    deps = _shared._workspace_deps()
    asyncio.run(deps["run_shell"]("git status", cwd=".", timeout_seconds=1, env={"EXISTING": "1"}))
    asyncio.run(
        deps["run_shell"]("echo hello", cwd=".", timeout_seconds=1, env={"EXISTING": "2"})
    )

    assert calls[0].get("EXISTING") == "1"
    assert calls[0].get("GIT_HTTP_EXTRAHEADER") == "auth"
    assert calls[1].get("EXISTING") == "2"
    assert "GIT_HTTP_EXTRAHEADER" not in calls[1]
