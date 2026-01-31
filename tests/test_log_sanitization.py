import pytest


def test_sanitize_for_logs_collapses_whitespace(monkeypatch):
    # Ensure compact mode so _sanitize_for_logs runs its clipping logic.
    monkeypatch.delenv("ADAPTIV_MCP_LOG_FULL_FIDELITY", raising=False)

    from github_mcp import config

    out = config._sanitize_for_logs("hello\nworld\tfrom\r\nlogs")
    assert out == "hello world from logs"


def test_sanitize_for_logs_bytes_decoded_single_line(monkeypatch):
    monkeypatch.delenv("ADAPTIV_MCP_LOG_FULL_FIDELITY", raising=False)

    from github_mcp import config

    out = config._sanitize_for_logs(b"hello\nworld")
    assert out == "hello world"


@pytest.mark.parametrize(
    "payload",
    [
        b"\x00\x01\x02",
        b"\xff\xfe",
        bytearray(b"\xff\n\xfe"),
    ],
)
def test_sanitize_for_logs_bytes_binary_compact(monkeypatch, payload):
    monkeypatch.delenv("ADAPTIV_MCP_LOG_FULL_FIDELITY", raising=False)

    from github_mcp import config

    out = config._sanitize_for_logs(payload)
    assert isinstance(out, str)
    assert out.startswith("<bytes len=")


def test_sanitize_for_logs_nested_bytes(monkeypatch):
    monkeypatch.delenv("ADAPTIV_MCP_LOG_FULL_FIDELITY", raising=False)

    from github_mcp import config

    out = config._sanitize_for_logs({"body": b"a\n\tb", "ok": True})
    assert out["body"] == "a b"
    assert out["ok"] is True
