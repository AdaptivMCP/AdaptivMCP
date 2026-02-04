from __future__ import annotations


def _set_auto_approve(monkeypatch, enabled: bool | None) -> None:
    """Helper to make auto-approve behavior explicit in tests.

    The server defaults to auto-approve enabled; many annotation tests expect
    the legacy UI hints behavior, so they must force auto-approve off.
    """

    if enabled is None:
        monkeypatch.delenv("ADAPTIV_MCP_AUTO_APPROVE", raising=False)
    else:
        monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "true" if enabled else "false")


def test_infer_write_action_from_shell_read_only_examples() -> None:
    from github_mcp.command_classification import infer_write_action_from_shell

    assert infer_write_action_from_shell("ls -la") is False
    assert infer_write_action_from_shell("pwd") is False
    assert infer_write_action_from_shell("git status --porcelain") is False
    assert infer_write_action_from_shell('rg -n "foo" .') is False
    assert infer_write_action_from_shell("sed -n '1,20p' README.md") is False


def test_infer_write_action_from_shell_write_examples() -> None:
    from github_mcp.command_classification import infer_write_action_from_shell

    assert infer_write_action_from_shell("git commit -m 'x'") is True
    assert infer_write_action_from_shell("rm -f foo.txt") is True
    assert infer_write_action_from_shell("sed -i 's/a/b/' file.txt") is True
    assert infer_write_action_from_shell("echo hi > out.txt") is True
    assert infer_write_action_from_shell("tee out.txt < in.txt") is True
    assert (
        infer_write_action_from_shell("python -m pip install -r dev-requirements.txt")
        is True
    )


def test_http_tool_registry_uses_write_action_for_retries(monkeypatch) -> None:
    """Read-classified tools may retry; write-classified tools must not."""

    _set_auto_approve(monkeypatch, False)

    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import github_mcp.http_routes.tool_registry as tool_registry

    # Avoid real sleeps in retry loops.
    monkeypatch.setattr(tool_registry, "_jitter_sleep_seconds", lambda *_a, **_k: 0.0)

    calls = {"n": 0}

    async def flaky_cmd(command: str) -> dict:
        calls["n"] += 1
        # Return retryable structured error. tool_registry maps this to 429.
        return {
            "error": "rate limited",
            "error_detail": {
                "category": "rate_limited",
                "retryable": True,
                "details": {"retry_after_seconds": 0.0},
            },
        }

    # Attach MCP metadata so tool_registry can discover write_action classification.
    flaky_cmd.__mcp_write_action__ = False

    class ToolObj:
        write_action = False

    def fake_find_registered_tool(name: str):
        if name == "flaky_cmd":
            return ToolObj(), flaky_cmd
        return None

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", fake_find_registered_tool
    )

    endpoint = tool_registry.build_tool_invoke_endpoint()
    app = Starlette(
        routes=[Route("/tools/{tool_name}/invoke", endpoint, methods=["POST"])]
    )
    client = TestClient(app)

    # 1) Read tool should retry up to max_attempts.
    calls["n"] = 0
    resp = client.post("/tools/flaky_cmd/invoke?max_attempts=2", json={"command": "ls"})
    assert resp.status_code == 429
    assert calls["n"] == 2

    # 2) Flip to write tool and ensure it does NOT retry.
    flaky_cmd.__mcp_write_action__ = True
    ToolObj.write_action = True
    calls["n"] = 0
    resp2 = client.post(
        "/tools/flaky_cmd/invoke?max_attempts=2",
        json={"command": "rm -f x"},
    )
    assert resp2.status_code == 429
    assert calls["n"] == 1


def test_auto_approve_suppresses_all_ui_hints(monkeypatch) -> None:
    """When auto-approve is enabled, all UI hint flags should be turned off."""

    from github_mcp.mcp_server import decorators

    _set_auto_approve(monkeypatch, True)

    class FakeMCP:
        def tool(self, *, name=None, description=None, meta=None, annotations=None):
            def decorator(fn):
                return {
                    "fn": fn,
                    "name": name,
                    "meta": meta,
                    "annotations": annotations,
                }

            return decorator

    monkeypatch.setattr(decorators, "mcp", FakeMCP())
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    @decorators.mcp_tool(name="hint_suppression_tool", write_action=True)
    def hint_suppression_tool() -> dict:
        return {"ok": True}

    tool_obj = hint_suppression_tool.__mcp_tool__
    ann = tool_obj.get("annotations", {})
    assert ann.get("readOnlyHint") is False
    assert ann.get("openWorldHint") is False
