from __future__ import annotations

from starlette.testclient import TestClient

import main


def test_llm_execute_invalid_json_body_returns_executed_false() -> None:
    client = TestClient(main.app)

    resp = client.post(
        "/llm/execute",
        content="not-json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["calls"] == []
    assert payload["executed"] is False


def test_llm_execute_dry_run_does_not_execute(monkeypatch) -> None:
    import github_mcp.http_routes.llm_execute as llm_execute

    executed = {"called": False}

    async def _execute_tool(*_args, **_kwargs):
        executed["called"] = True
        return {"should_not": "run"}, 200, {}

    monkeypatch.setattr(llm_execute, "_execute_tool", _execute_tool)

    client = TestClient(main.app)
    text = """```tool
{"tool":"anything","args":{"x":1}}
```"""

    resp = client.post("/llm/execute?dry_run=1", json={"text": text})
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["executed"] is False
    assert payload["calls"] and payload["calls"][0]["tool_name"] == "anything"
    assert executed["called"] is False


def test_llm_execute_executes_calls_and_resolves_file_blocks(monkeypatch) -> None:
    import github_mcp.http_routes.llm_execute as llm_execute

    observed: dict[str, object] = {}

    async def _execute_tool(tool_name: str, args: dict, *, max_attempts=None):
        observed.update({"tool_name": tool_name, "args": args, "max_attempts": max_attempts})
        return {"ok": True}, 201, {"x-test": "1"}

    monkeypatch.setattr(llm_execute, "_execute_tool", _execute_tool)

    client = TestClient(main.app)

    text = """```file
path: foo.txt

hello world
```

```tool
{"tool":"fake_tool","args":{"content":"@file:foo.txt"}}
```"""

    resp = client.post(
        "/llm/execute",
        json={"text": text, "max_attempts": "2"},
    )
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["executed"] is True
    assert observed["tool_name"] == "fake_tool"
    assert observed["args"] == {"content": "hello world"}
    assert observed["max_attempts"] == 2

    assert payload["results"][0]["status_code"] == 201
    assert payload["results"][0]["headers"] == {"x-test": "1"}
    assert payload["results"][0]["result"] == {"ok": True}


def test_llm_execute_messages_format_filters_non_text_and_coerces_max_calls(monkeypatch) -> None:
    import github_mcp.http_routes.llm_execute as llm_execute

    def _extract(texts, *, max_calls: int = 20):
        # Only the first message has string content; others should be ignored.
        assert texts == [("analysis", "hi")]
        # Non-int should coerce to the default.
        assert max_calls == 20
        return []

    monkeypatch.setattr(llm_execute, "extract_tool_calls_from_text", _extract)

    client = TestClient(main.app)
    resp = client.post(
        "/llm/execute",
        json={
            "messages": [
                {"channel": "analysis", "content": "hi"},
                {"channel": "analysis", "content": ["not", "a", "string"]},
                "not-a-dict",
            ],
            "max_calls": "not-an-int",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["calls"] == []
    assert payload["executed"] is False
