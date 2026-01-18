from __future__ import annotations

from typing import Any


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
        infer_write_action_from_shell("python -m pip install -r dev-requirements.txt") is True
    )


def test_mcp_tool_dynamic_write_action_is_exposed_in_response(monkeypatch) -> None:
    """When a resolver is present, mapping outputs include invocation-level metadata."""

    from github_mcp.mcp_server import decorators

    class FakeMCP:
        def tool(self, *, name=None, description=None, meta=None, annotations=None):
            def decorator(fn):
                return {"fn": fn, "name": name, "meta": meta, "annotations": annotations}

            return decorator

    monkeypatch.setattr(decorators, "mcp", FakeMCP())
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    def resolver(args):
        return bool(args.get("mode") == "write")

    @decorators.mcp_tool(name="dyn_tool", write_action=True, write_action_resolver=resolver)
    def dyn_tool(mode: str = "read") -> dict:
        return {"mode": mode}

    out_read = dyn_tool(mode="read")
    assert out_read.get("tool_metadata", {}).get("base_write_action") is True
    assert out_read.get("tool_metadata", {}).get("effective_write_action") is False

    out_write = dyn_tool(mode="write")
    assert out_write.get("tool_metadata", {}).get("base_write_action") is True
    assert out_write.get("tool_metadata", {}).get("effective_write_action") is True


def test_http_tool_registry_uses_effective_write_action_for_retries(monkeypatch) -> None:
    """Read-classified invocations may retry; write-classified invocations must not."""

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

    def resolver(args: dict[str, Any]) -> bool:
        # Read if the command is 'ls', otherwise write.
        return str(args.get("command") or "").strip() != "ls"

    # Attach MCP metadata so tool_registry can discover resolver/base classification.
    setattr(flaky_cmd, "__mcp_write_action__", True)
    setattr(flaky_cmd, "__mcp_write_action_resolver__", resolver)

    class ToolObj:
        write_action = True

    def fake_find_registered_tool(name: str):
        if name == "flaky_cmd":
            return ToolObj(), flaky_cmd
        return None

    monkeypatch.setattr(tool_registry, "_find_registered_tool", fake_find_registered_tool)

    endpoint = tool_registry.build_tool_invoke_endpoint()
    app = Starlette(routes=[Route("/tools/{tool_name}/invoke", endpoint, methods=["POST"])])
    client = TestClient(app)

    # 1) Read invocation should retry up to max_attempts.
    calls["n"] = 0
    resp = client.post("/tools/flaky_cmd/invoke?max_attempts=2", json={"command": "ls"})
    assert resp.status_code == 429
    assert calls["n"] == 2

    # 2) Write invocation should NOT retry.
    calls["n"] = 0
    resp2 = client.post(
        "/tools/flaky_cmd/invoke?max_attempts=2",
        json={"command": "rm -f x"},
    )
    assert resp2.status_code == 429
    assert calls["n"] == 1

