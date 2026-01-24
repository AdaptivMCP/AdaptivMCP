import github_mcp.retry_utils as retry_utils


def test_jitter_sleep_seconds_deterministic_under_pytest(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")

    assert (
        retry_utils.jitter_sleep_seconds(1.23, respect_min=True, cap_seconds=0.25)
        == 1.23
    )
    assert retry_utils.jitter_sleep_seconds(1.23, respect_min=False) == 1.23


def test_jitter_sleep_seconds_respect_min_adds_capped_jitter(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Force jitter to the maximum possible value for determinism.
    monkeypatch.setattr(retry_utils.random, "uniform", lambda a, b: b)

    # delay * 0.25 = 2.5, cap_seconds = 0.25 => additive jitter = 0.25
    assert (
        retry_utils.jitter_sleep_seconds(10.0, respect_min=True, cap_seconds=0.25)
        == 10.25
    )


def test_jitter_sleep_seconds_full_jitter_uses_uniform(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    captured = {}

    def fake_uniform(a, b):
        captured["a"] = a
        captured["b"] = b
        return b

    monkeypatch.setattr(retry_utils.random, "uniform", fake_uniform)

    assert retry_utils.jitter_sleep_seconds(5.0, respect_min=False) == 5.0
    assert captured == {"a": 0.0, "b": 5.0}
