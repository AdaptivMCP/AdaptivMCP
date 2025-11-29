import pytest

import main
import extra_tools


def test_effective_ref_for_repo_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pretend this repo is the controller and has a custom default branch.
    monkeypatch.setattr(main, "CONTROLLER_REPO", "owner/controller")
    monkeypatch.setattr(main, "CONTROLLER_DEFAULT_BRANCH", "ally-refactor")

    fn = main._effective_ref_for_repo

    # Missing or "main" ref should map to the controller default branch.
    assert fn("owner/controller", None) == "ally-refactor"
    assert fn("owner/controller", "main") == "ally-refactor"
    # Explicit non-main refs should be preserved.
    assert fn("owner/controller", "feature/x") == "feature/x"


def test_effective_ref_for_repo_non_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    # Non-controller repos should fall back to "main" when ref is omitted.
    monkeypatch.setattr(main, "CONTROLLER_REPO", "owner/controller")
    monkeypatch.setattr(main, "CONTROLLER_DEFAULT_BRANCH", "ally-refactor")

    fn = main._effective_ref_for_repo

    assert fn("other/repo", None) == "main"
    assert fn("other/repo", "dev") == "dev"


@pytest.mark.asyncio
async def test_run_command_uses_controller_default_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    # Enable writes and configure controller defaults.
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)
    monkeypatch.setattr(main, "CONTROLLER_REPO", "owner/controller")
    monkeypatch.setattr(main, "CONTROLLER_DEFAULT_BRANCH", "ally-refactor")

    calls: dict[str, object] = {}

    async def fake_clone(full_name: str, ref: str | None = None) -> str:
        calls["clone_full_name"] = full_name
        calls["clone_ref"] = ref
        return str(tmp_path)

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        calls["run_shell_cmd"] = cmd
        calls["run_shell_cwd"] = cwd
        calls["run_shell_env"] = env
        return {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    def fake_ensure_write_allowed(context: str) -> None:
        calls["write_context"] = context

    monkeypatch.setattr(main, "_clone_repo", fake_clone)
    monkeypatch.setattr(main, "_run_shell", fake_run_shell)
    monkeypatch.setattr(main, "_ensure_write_allowed", fake_ensure_write_allowed)

    await main.run_command(
        full_name="owner/controller",
        ref="main",  # should be remapped to CONTROLLER_DEFAULT_BRANCH
        command="echo hi",
        use_temp_venv=False,
    )

    assert calls["clone_full_name"] == "owner/controller"
    # The effective ref should be the controller default branch, not "main".
    assert calls["clone_ref"] == "ally-refactor"
    # The write context string should also include the effective ref.
    assert "@ally-refactor" in str(calls["write_context"])


@pytest.mark.asyncio
async def test_run_command_non_controller_defaults_to_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)
    monkeypatch.setattr(main, "CONTROLLER_REPO", "owner/controller")
    monkeypatch.setattr(main, "CONTROLLER_DEFAULT_BRANCH", "ally-refactor")

    calls: dict[str, object] = {}

    async def fake_clone(full_name: str, ref: str | None = None) -> str:
        calls["clone_full_name"] = full_name
        calls["clone_ref"] = ref
        return str(tmp_path)

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        return {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    def fake_ensure_write_allowed(context: str) -> None:
        calls["write_context"] = context

    monkeypatch.setattr(main, "_clone_repo", fake_clone)
    monkeypatch.setattr(main, "_run_shell", fake_run_shell)
    monkeypatch.setattr(main, "_ensure_write_allowed", fake_ensure_write_allowed)

    await main.run_command(
        full_name="other/repo",
        ref=None,  # should fall back to "main"
        command="echo hi",
        use_temp_venv=False,
    )

    assert calls["clone_full_name"] == "other/repo"
    assert calls["clone_ref"] == "main"
    assert "@main" in str(calls["write_context"])


@pytest.mark.asyncio
async def test_delete_file_uses_effective_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_effective_ref(full_name: str, branch: str | None) -> str:
        calls["effective_full_name"] = full_name
        calls["effective_branch_param"] = branch
        return "ally-refactor"

    async def fake_resolve_sha(full_name: str, path: str, branch: str) -> str | None:
        calls["resolve_branch"] = branch
        return "sha123"

    async def fake_github_request(method: str, url: str, json_body=None, **kwargs):
        calls["request_method"] = method
        calls["request_url"] = url
        calls["request_json"] = json_body
        return {"commit": {"sha": "newsha"}}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(extra_tools, "_resolve_file_sha", fake_resolve_sha)
    monkeypatch.setattr(extra_tools, "_github_request", fake_github_request)

    result = await extra_tools.delete_file(
        full_name="owner/controller",
        path="foo.txt",
        branch="main",  # should be remapped via _effective_ref_for_repo
        message="delete foo",
        if_missing="error",
    )

    assert calls["effective_full_name"] == "owner/controller"
    assert calls["effective_branch_param"] == "main"
    # The actual SHA resolution and DELETE request should use the effective branch.
    assert calls["resolve_branch"] == "ally-refactor"
    assert calls["request_json"]["branch"] == "ally-refactor"
    # The reported branch in the result should also be the effective one.
    assert result["branch"] == "ally-refactor"


@pytest.mark.asyncio
async def test_get_file_slice_uses_effective_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def fake_effective_ref(full_name: str, ref: str | None) -> str:
        calls["effective_full_name"] = full_name
        calls["effective_ref_param"] = ref
        return "ally-refactor"

    async def fake_decode(full_name: str, path: str, ref: str | None = None):
        calls["decode_ref"] = ref
        return {"text": "line1\nline2\n"}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await extra_tools.get_file_slice(
        full_name="owner/controller",
        path="foo.txt",
        ref="main",  # input ref; should be remapped
        start_line=1,
        max_lines=10,
    )

    assert calls["effective_full_name"] == "owner/controller"
    assert calls["effective_ref_param"] == "main"
    assert calls["decode_ref"] == "ally-refactor"
    assert result["ref"] == "ally-refactor"
