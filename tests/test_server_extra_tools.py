import sys
import types

from github_mcp import server


def test_register_extra_tools_invokes_extension(monkeypatch):
    calls = []

    def fake_register(decorator):
        calls.append(decorator)

    fake_module = types.SimpleNamespace(register_extra_tools=fake_register)
    monkeypatch.setitem(sys.modules, "extra_tools", fake_module)

    server.register_extra_tools_if_available()

    assert calls == [server.mcp_tool]


def test_register_extra_tools_swallows_import_errors(monkeypatch):
    real_import = __import__

    def boom_import(name, *args, **kwargs):
        if name == "extra_tools":
            raise ImportError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", boom_import)

    # Should not raise even though import fails
    server.register_extra_tools_if_available()


def test_register_extra_tools_logs_failures(monkeypatch, caplog):
    def broken_register(_decorator):
        raise RuntimeError("nope")

    fake_module = types.SimpleNamespace(register_extra_tools=broken_register)
    monkeypatch.setitem(sys.modules, "extra_tools", fake_module)

    with caplog.at_level("ERROR"):
        server.register_extra_tools_if_available()

    assert any("register_extra_tools failed" in rec.message for rec in caplog.records)
