import io
import zipfile

import pytest

from github_mcp.utils import (
    CONTROLLER_DEFAULT_BRANCH,
    CONTROLLER_REPO,
    _decode_zipped_job_logs,
    _normalize_branch,
    _normalize_repo_path,
    _render_visible_whitespace,
    normalize_args,
)
from github_mcp.exceptions import ToolPreflightValidationError


class TestNormalizeRepoPath:
    def test_strips_leading_slashes_and_collapses_separators(self):
        assert _normalize_repo_path("/foo//bar") == "foo/bar"

    def test_rejects_parent_directory_segments(self):
        with pytest.raises(ToolPreflightValidationError):
            _normalize_repo_path("../evil")

    def test_rejects_empty_after_normalization(self):
        with pytest.raises(ToolPreflightValidationError):
            _normalize_repo_path("///")


class TestNormalizeBranch:
    def test_uses_controller_default_branch_when_matching_repo(self, monkeypatch):
        monkeypatch.setattr("github_mcp.utils.CONTROLLER_REPO", "example/repo")
        monkeypatch.setattr("github_mcp.utils.CONTROLLER_DEFAULT_BRANCH", "develop")

        assert _normalize_branch("example/repo", None) == "develop"

    def test_accepts_explicit_branch(self, monkeypatch):
        monkeypatch.setattr("github_mcp.utils.CONTROLLER_REPO", CONTROLLER_REPO)
        monkeypatch.setattr(
            "github_mcp.utils.CONTROLLER_DEFAULT_BRANCH", CONTROLLER_DEFAULT_BRANCH
        )

        assert _normalize_branch("other/repo", "feature/foo") == "feature/foo"


class TestNormalizeArgs:
    def test_returns_dict_for_mapping(self):
        src = {"a": 1}
        result = normalize_args(src)

        assert result == src
        assert result is not src

    def test_parses_json_text_object(self):
        assert normalize_args('{"name": "value"}') == {"name": "value"}

    @pytest.mark.parametrize(
        "payload,expected_exception",
        [
            ("{not-json}", ValueError),
            ("[]", TypeError),
            ("freeform", TypeError),
            (123, TypeError),
        ],
    )
    def test_invalid_payloads_raise(self, payload, expected_exception):
        with pytest.raises(expected_exception):
            normalize_args(payload)


class TestDecodeZippedJobLogs:
    def test_concatenates_sorted_text_entries(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("b.log", "second")
            archive.writestr("a.log", "first")

        content = _decode_zipped_job_logs(buffer.getvalue())

        assert content == "[a.log]\nfirst\n\n[b.log]\nsecond"


class TestRenderVisibleWhitespace:
    def test_replaces_spaces_and_tabs_and_marks_newlines(self):
        text = "line 1\n\tline2 "
        rendered = _render_visible_whitespace(text)

        assert rendered == "line·1⏎\n→\tline2·␄"
