# Assistant workflows for the GitHub MCP server

This guide distills the fastest paths for agents to complete common GitHub tasks
without getting stuck in loops. The server exposes every tool referenced here in
`main.py`.

## Quickly check capabilities
1. Call `get_server_config` to see whether write tools are enabled and to read
   timeout/log limits.
2. If you need to modify repositories or run shell commands, call
   `authorize_write_actions` with `approved=true` to enable write-tagged tools
   for the session.

## Edit files and open a pull request
1. Use `get_file_contents` (or the listing/search helpers) to fetch the file you
   plan to change.
2. Prepare the new content locally.
3. Call `update_files_and_open_pr` with a list of `{path, content}` entries and a
   PR title/body. The helper will create a branch, commit each file, and open the
   PR in one request.

## Run tests or linters against pending changes
1. Capture your current unified diff (the connector typically provides it).
2. Call `run_tests` or `run_command`, supplying the diff via the `patch`
   argument so the temporary clone mirrors your edits.
3. Review `stdout`/`stderr` from the response; the server truncates outputs to
   keep results compact.

## Kick off or monitor workflows
* Use `trigger_workflow_dispatch` to start a workflow by filename.
* Call `trigger_and_wait_for_workflow` to dispatch and poll for completion when
  you need a single synchronous result.

These recipes mirror the steps taken by this repository's maintainers and are
kept alongside the code so tool behaviors and documentation stay in sync.
