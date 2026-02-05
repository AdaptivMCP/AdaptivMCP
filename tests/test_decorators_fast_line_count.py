import github_mcp.mcp_server.decorators as dec


def test_fast_line_count_matches_splitlines_common_cases() -> None:
    cases = [
        "",
        "one",
        "one\n",
        "one\ntwo",
        "one\ntwo\n",
        "\n",
        "\n\n",
        "one\n\nthree",
        "one\n\nthree\n",
    ]

    for text in cases:
        assert dec._fast_line_count(text) == len(text.splitlines())


def test_fast_line_count_large_string_is_linear_and_correct() -> None:
    # Ensure we don't accidentally regress to an allocating implementation.
    text = ("x\n" * 10_000) + "tail"
    assert dec._fast_line_count(text) == len(text.splitlines())

