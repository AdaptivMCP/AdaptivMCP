from __future__ import annotations

from typing import Any

from starlette.testclient import TestClient

import main


def test_unknown_tool_includes_suggested_tool_and_warnings(monkeypatch: Any) -> None:
    import github_mcp.http_routes.tool_registry as tool_registry
    from github_mcp.mcp_server import registry as mcp_registry

    class Tool:
        name = "terminal_command"
        write_action = True

    def func(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "success", "ok": True}

    # Force the invoke path to treat the requested name as unknown.
    monkeypatch.setattr(tool_registry, "_find_registered_tool", lambda _name: None)
    monkeypatch.setattr(mcp_registry, "_REGISTERED_MCP_TOOLS", [(Tool(), func)])

    client = TestClient(main.app)
    resp = client.post("/tools/terminal_comand", json={"args": {}})
    assert resp.status_code == 404
    payload = resp.json()
    assert payload.get("category") == "not_found"
    assert payload.get("suggested_tool") == "terminal_command"
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any("Did you mean" in w for w in warnings)


def test_unknown_tool_ambiguous_does_not_force_single_suggestion(
    monkeypatch: Any,
) -> None:
    """When multiple close matches exist, avoid anchoring on a single tool."""

    import github_mcp.http_routes.tool_registry as tool_registry
    from github_mcp.mcp_server import registry as mcp_registry

    class ToolA:
        name = "terminal_command"
        write_action = True

    class ToolB:
        name = "terminal_commands"
        write_action = True

    def func(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "success", "ok": True}

    # Force the invoke path to treat the requested name as unknown.
    monkeypatch.setattr(tool_registry, "_find_registered_tool", lambda _name: None)
    monkeypatch.setattr(
        mcp_registry, "_REGISTERED_MCP_TOOLS", [(ToolA(), func), (ToolB(), func)]
    )

    client = TestClient(main.app)
    resp = client.post("/tools/terminal_comand", json={"args": {}})
    assert resp.status_code == 404
    payload = resp.json()
    assert payload.get("category") == "not_found"

    # We should not force a single tool when two close matches exist.
    assert payload.get("suggested_tool") in {None, ""}
    suggested = payload.get("suggested_tools")
    assert isinstance(suggested, list)
    assert "terminal_command" in suggested
    assert "terminal_commands" in suggested

    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any("Close matches" in w for w in warnings)


def test_invalid_tool_args_includes_expected_args_warning(monkeypatch: Any) -> None:
    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "fake_sig"
        write_action = False

    def func(a: int, b: int = 1) -> dict[str, Any]:
        return {"status": "success", "ok": True, "result": a + b}

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )

    client = TestClient(main.app)
    resp = client.post("/tools/fake_sig", json={"args": {"aa": 1}})
    assert resp.status_code == 400
    payload = resp.json()
    assert payload.get("status") == "error"
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any("Valid args for fake_sig" in w for w in warnings)
    detail = payload.get("error_detail")
    assert isinstance(detail, dict)
    details = detail.get("details")
    assert isinstance(details, dict)
    expected = details.get("expected_args")
    assert isinstance(expected, dict)
    assert expected.get("required") == ["a"]
    assert "b" in (expected.get("optional") or [])


def test_expected_args_excludes_positional_only(monkeypatch: Any) -> None:
    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "positional_only_sig"
        write_action = False

    def func(a: int, /, b: int, c: int = 3) -> dict[str, Any]:
        return {"status": "success", "ok": True, "result": a + b + c}

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )

    client = TestClient(main.app)
    resp = client.post("/tools/positional_only_sig", json={"args": {"b": 2}})
    assert resp.status_code == 400
    payload = resp.json()
    detail = payload.get("error_detail")
    assert isinstance(detail, dict)
    details = detail.get("details")
    assert isinstance(details, dict)
    expected = details.get("expected_args")
    assert isinstance(expected, dict)
    assert expected.get("required") == ["b"]
    assert "c" in (expected.get("optional") or [])
    assert "a" not in (expected.get("all") or [])
