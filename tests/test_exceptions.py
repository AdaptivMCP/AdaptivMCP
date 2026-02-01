from github_mcp import exceptions


def test_api_error_carries_status_and_payload():
    err = exceptions.APIError(
        "nope",
        status_code=418,
        response_payload={"message": "teapot"},
    )
    assert str(err) == "nope"
    assert err.status_code == 418
    assert err.response_payload == {"message": "teapot"}


def test_tool_preflight_validation_error_message_and_tool_field():
    err = exceptions.ToolPreflightValidationError("do_thing", "bad arg")
    assert err.tool == "do_thing"
    assert str(err) == "Preflight validation failed for tool 'do_thing': bad arg"


def test_tool_operation_error_defaults_and_bool_retryable():
    err = exceptions.ToolOperationError("boom")
    assert str(err) == "boom"
    assert err.category == "internal"
    assert err.code is None
    assert err.details == {}
    assert err.hint is None
    assert err.origin is None
    assert err.retryable is False

    err2 = exceptions.ToolOperationError(
        "boom",
        category="validation",
        code="E123",
        details=None,
        retryable=1,
    )
    assert err2.category == "validation"
    assert err2.code == "E123"
    assert err2.details == {}
    assert err2.retryable is True


def test_write_approval_required_code_constant():
    assert exceptions.WriteApprovalRequiredError.code == "WRITE_APPROVAL_REQUIRED"


def test___all___exports_expected_symbols():
    # Keep this intentionally strict so refactors don't accidentally drop exports.
    assert set(exceptions.__all__) == {
        "APIError",
        "GitHubAPIError",
        "GitHubAuthError",
        "GitHubRateLimitError",
        "RenderAPIError",
        "RenderAuthError",
        "WriteNotAuthorizedError",
        "WriteApprovalRequiredError",
        "ToolPreflightValidationError",
        "UsageError",
        "ToolOperationError",
    }
