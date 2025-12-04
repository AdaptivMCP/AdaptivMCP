'''End-to-end smoke tests for the GitHub MCP server.'''

import pytest

import main
from github_mcp.exceptions import GitHubAPIError, GitHubAuthError


@pytest.mark.asyncio
async def test_end_to_end_small_doc_edit_and_test_run():
    '''End-to-end workflow: list, read, diff, commit, and run tests.

    This test exercises a small but realistic workflow that an assistant or
    controller might drive:
      - Discover a small docs file.
      - Read its contents.
      - Build a unified diff representing a tiny edit.
      - Apply the edit via apply_text_update_and_commit on a throwaway branch.
      - Run the project's tests through run_tests.
    '''

    # Explicitly enable write tools for this smoke test so it can exercise
    # the full long-workflow path end to end. In real usage, the controller
    # or assistant should call authorize_write_actions before write tools.
    main.authorize_write_actions(approved=True)

    # 1) Discover a small docs file via list_repository_tree.
    # get_repo_defaults returns a wrapper object with a nested 'defaults' field.
    defaults_result = await main.get_repo_defaults('Proofgate-Revocations/chatgpt-mcp-github')
    defaults = defaults_result['defaults']
    full_name = defaults['full_name']
    base_ref = defaults['default_branch']

    tree = await main.list_repository_tree(
        full_name, ref=base_ref, path_prefix='docs', recursive=False
    )
    doc_paths = [
        e['path'] for e in tree['entries']
        if e['path'].endswith('start_session.md')
    ]
    assert doc_paths, 'expected to find docs/start_session.md in the tree'
    target_path = doc_paths[0]

    # 2) Read the current contents.
    file_info = await main.get_file_contents(full_name, target_path, ref=base_ref)
    original_text = file_info['text']

    # 3) Prepare a tiny edit marker and avoid accumulating it across runs.
    marker = 'End-to-end smoke marker'
    if marker in original_text:
        base_text = original_text.replace(marker, '').rstrip() + '\n'
    else:
        base_text = original_text.rstrip() + '\n'

    new_text = base_text + '\n<!-- ' + marker + ' -->\n'

    # 4) Build a unified diff for the change.
    diff_result = await main.build_unified_diff(
        full_name=full_name, path=target_path, new_content=new_text, ref=base_ref
    )

    assert 'diff' in diff_result
    diff_text = diff_result['diff']
    assert marker in diff_text

    # 5) Apply the edit on a throwaway branch.
    branch_name = 'tests/long-workflow-smoke-temp'

    apply_result = await main.apply_text_update_and_commit(
        full_name=full_name,
        path=target_path,
        updated_content=new_text,
        branch=branch_name,
        message='test: long workflow smoke edit',
    )

    assert apply_result.get('status') == 'committed'
    assert apply_result.get('branch') == branch_name

    # 6) Run tests on the updated branch using the run_tests tool.
    tests_result = await main.run_tests(
        full_name=full_name,
        ref=branch_name,
        test_command='python -m pytest -q',
        timeout_seconds=900,
    )

    # We do not require a green suite here; the point is that the workflow runs.
    assert tests_result.get('status') in {'passed', 'failed'}
    assert tests_result.get('command') == 'python -m pytest -q'
