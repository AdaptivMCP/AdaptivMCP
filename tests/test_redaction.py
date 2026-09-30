from __future__ import annotations

import logging

from github_mcp.mcp_server.error_handling import _structured_tool_error
from github_mcp.redaction import REDACTED, redact_any, redact_url


def test_redact_any_recurses_through_secret_keys() -> None:
    secret = "ghp_" + "A" * 32
    value = {
        "token": secret,
        "nested": {"authorization": f"Bearer {secret}"},
        "normal": "keep-this-value",
    }

    out = redact_any(value)

    assert out["token"] == REDACTED
    assert out["nested"]["authorization"] == REDACTED
    assert out["normal"] == "keep-this-value"


def test_redact_any_scrubs_secret_forms_embedded_in_strings() -> None:
    secret = "ghp_" + "B" * 32
    text = (
        f"Authorization: Bearer {secret}\n"
        f"GITHUB_TOKEN={secret}\n"
        f"https://user:{secret}@github.com/example/repo.git"
    )

    out = redact_any(text)

    assert secret not in out
    assert "Bearer <REDACTED_SECRET>" in out
    assert "GITHUB_TOKEN=<REDACTED_SECRET>" in out
    assert "https://<REDACTED_SECRET>@github.com" in out


def test_redact_url_preserves_url_without_credentials() -> None:
    url = "https://github.com/example/repo.git?x=1"
    assert redact_url(url) == url


def test_structured_error_redacts_exception_and_details() -> None:
    secret = "ghp_" + "C" * 32

    class SecretError(Exception):
        pass

    exc = SecretError(f"Git failed: Authorization: Bearer {secret}")
    exc.details = {"token": secret}

    payload = _structured_tool_error(exc, context="test")
    rendered = repr(payload)

    assert secret not in rendered
    assert REDACTED in rendered


def test_config_log_sanitizer_redacts_secrets(monkeypatch) -> None:
    import github_mcp.config as config

    monkeypatch.delenv("ADAPTIV_MCP_LOG_FULL_FIDELITY", raising=False)
    secret = "ghp_" + "D" * 32
    payload = {
        "headers": {"Authorization": f"Bearer {secret}"},
        "body": {"token": secret},
        "safe": "hello",
    }

    out = config._sanitize_for_logs(payload)

    assert secret not in repr(out)
    assert out["safe"] == "hello"
    assert out["body"]["token"] == REDACTED


def test_redaction_does_not_replace_short_orordinary_values() -> None:
    assert redact_any("abc123") == "abc123"
    assert redact_any("0123456789abcdef" * 3) == "0123456789abcdef" * 3
