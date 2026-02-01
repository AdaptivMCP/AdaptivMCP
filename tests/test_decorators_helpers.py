import pytest

from github_mcp.mcp_server import decorators as dec


def test_strip_internal_log_fields_strips_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dec, "STRIP_INTERNAL_LOG_FIELDS", True)

    payload = {
        "keep": 1,
        "__log_debug": "secret",
        "__log_payload": {"a": 1},
        42: "non_str_key_should_stay",
    }
    out = dec._strip_internal_log_fields(payload)

    assert out["keep"] == 1
    assert "__log_debug" not in out
    assert "__log_payload" not in out
    assert out[42] == "non_str_key_should_stay"


def test_strip_internal_log_fields_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dec, "STRIP_INTERNAL_LOG_FIELDS", False)

    payload = {"keep": 1, "__log_debug": "secret"}
    out = dec._strip_internal_log_fields(payload)

    assert out == payload


@pytest.mark.parametrize(
    "result, expected",
    [
        ("scalar", "ok"),
        ({"ok": False}, "error"),
        ({"status": "FAILED"}, "error"),
        ({"exit_code": 2}, "error"),
        ({"timed_out": True}, "error"),
        ({"result": {"exit_code": 1}}, "error"),
        ({"result": {"timed_out": True}}, "error"),
        ({"error": " boom "}, "error"),
        ({"error": {"message": "boom"}}, "error"),
        ({"status": "warning"}, "warning"),
        ({"status": "passed_with_warnings", "warnings": ["x"]}, "warning"),
        ({"warnings": "warn"}, "warning"),
        ({"warnings": [None, "", "  ", "x"]}, "warning"),
        ({"ok": True, "status": "ok"}, "ok"),
    ],
)
def test_tool_result_outcome(result: object, expected: str) -> None:
    assert dec._tool_result_outcome(result) == expected


def test_normalize_tool_result_envelope_noop_under_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The helper intentionally returns early under pytest.
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE", True)
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE_SCALARS", True)

    payload = {"foo": 1}
    out = dec._normalize_tool_result_envelope(payload)

    assert out is payload


def test_normalize_tool_result_envelope_mapping_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE", True)
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE_SCALARS", False)

    payload = {"foo": 1}
    out = dec._normalize_tool_result_envelope(payload)

    assert payload == {"foo": 1}  # should not mutate input
    assert out["ok"] is True
    assert out["status"] == "success"
    assert out["foo"] == 1


def test_normalize_tool_result_envelope_preserves_scalars_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE", True)
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE_SCALARS", False)

    value = [1, 2, 3]
    out = dec._normalize_tool_result_envelope(value)

    assert out is value


def test_normalize_tool_result_envelope_wraps_scalar_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE", True)
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE_SCALARS", True)

    out = dec._normalize_tool_result_envelope("hi")

    assert out == {"status": "success", "ok": True, "result": "hi"}


def test_normalize_tool_result_envelope_infers_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE", True)

    out = dec._normalize_tool_result_envelope(
        {"ok": False, "error_detail": {"message": "Boom"}}
    )

    assert out["status"] == "error"
    assert out["ok"] is False
    assert out["error"] == "Boom"


def test_normalize_tool_result_envelope_warning_normalizes_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "TOOL_RESULT_ENVELOPE", True)

    out = dec._normalize_tool_result_envelope(
        {"status": "passed_with_warnings", "warnings": [None, "  ", "x", 7]}
    )

    assert out["status"] == "warning"
    assert out["ok"] is True
    assert out["status_raw"] == "passed_with_warnings"
    assert out["warnings"] == ["x", "7"]


def test_effective_response_mode_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "RESPONSE_MODE_DEFAULT", "raw")

    assert dec._effective_response_mode({"response_mode": "CHATGPT"}) == "chatgpt"
    assert (
        dec._effective_response_mode({"chatgpt": {"response_mode": "compact"}})
        == "compact"
    )

    # Invalid override -> fallback to default
    assert dec._effective_response_mode({"response_mode": "nope"}) == "raw"
