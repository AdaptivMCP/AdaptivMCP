from __future__ import annotations

import asyncio

from github_mcp.main_tools import dashboard


class _FakeMain:
    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []

    def _effective_ref_for_repo(self, full_name: str, ref: str | None) -> str:
        self.calls.append(("_effective_ref_for_repo", (full_name, ref), {}))
        return f"eff-{ref or 'none'}"

    async def get_repo_defaults(self, full_name: str):
        self.calls.append(("get_repo_defaults", (full_name,), {}))
        return {"defaults": {"default_branch": "develop"}}

    async def get_repository(self, full_name: str):
        self.calls.append(("get_repository", (full_name,), {}))
        return {"json": {"full_name": full_name, "private": False}}

    async def list_pull_requests(self, full_name: str, **kwargs):
        self.calls.append(("list_pull_requests", (full_name,), kwargs))
        return {"json": [{"number": 1}, {"number": 2}]}

    async def list_repository_issues(self, full_name: str, **kwargs):
        self.calls.append(("list_repository_issues", (full_name,), kwargs))
        return {
            "json": [
                {"number": 10, "title": "Issue"},
                {"number": 11, "pull_request": {"url": "https://example"}},
            ]
        }

    async def list_workflow_runs(self, full_name: str, **kwargs):
        self.calls.append(("list_workflow_runs", (full_name,), kwargs))
        return {"json": {"workflow_runs": [{"id": 123, "name": "CI"}]}}

    async def list_repository_tree(self, full_name: str, **kwargs):
        self.calls.append(("list_repository_tree", (full_name,), kwargs))
        return {
            "entries": [
                {"path": "README.md", "type": "blob", "size": 100},
                # A path with slashes is intentionally filtered out.
                {"path": "src/main.py", "type": "blob", "size": 1},
                # Non-dict + non-string cases are ignored.
                "not-a-dict",
                {"path": None, "type": "blob"},
                # A GitHub URL should be normalized down to a repo-relative path.
                {
                    "path": "https://github.com/octo/repo/blob/main/LICENSE",
                    "type": "blob",
                    "size": 55,
                },
            ]
        }


def test_get_repo_dashboard_uses_repo_defaults_and_filters(monkeypatch):
    fake = _FakeMain()

    # Ensure we do not accidentally consult _effective_ref_for_repo when repo
    # defaults already provide a default branch.
    def _effective_ref_guard(full_name: str, ref: str | None) -> str:
        raise AssertionError("_effective_ref_for_repo should not be called")

    fake._effective_ref_for_repo = _effective_ref_guard  # type: ignore[assignment]

    monkeypatch.setattr(dashboard, "_main", lambda: fake)

    result = asyncio.run(dashboard.get_repo_dashboard("octo/repo"))

    assert result["branch"] == "develop"
    assert result["repo"]["full_name"] == "octo/repo"
    assert [pr["number"] for pr in result["pull_requests"]] == [1, 2]

    # The GitHub issues API can return pull requests; those must be excluded.
    assert [issue["number"] for issue in result["issues"]] == [10]

    assert result["workflows"][0]["id"] == 123

    # Top-level tree should include only normalized, top-level paths.
    assert {entry["path"] for entry in result["top_level_tree"]} == {
        "README.md",
        "LICENSE",
    }


def test_get_repo_dashboard_resolves_explicit_branch(monkeypatch):
    class _BranchMain(_FakeMain):
        async def get_repo_defaults(self, full_name: str):
            raise AssertionError("get_repo_defaults should not be called when branch is provided")

    fake = _BranchMain()

    monkeypatch.setattr(dashboard, "_main", lambda: fake)

    result = asyncio.run(dashboard.get_repo_dashboard("octo/repo", branch="feature"))

    assert result["branch"] == "eff-feature"

    # Ensure workflow runs were requested on the effective branch.
    workflow_calls = [c for c in fake.calls if c[0] == "list_workflow_runs"]
    assert workflow_calls
    assert workflow_calls[0][2]["branch"] == "eff-feature"
