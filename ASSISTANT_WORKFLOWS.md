# Assistant workflows for the GitHub MCP server

This guide lists example paths agents can take when using the tools in
`main.py`. They are reference recipes rather than requirements; feel free to
mix and match steps or take a different approach entirely.

## Quickly check capabilities
1. `get_server_config` can show whether write tools are enabled and what
   timeout/log limits apply.
2. To modify repositories or run shell commands, `authorize_write_actions`
   with `approved=true` enables write-tagged tools for the session.

## Edit files and open a pull request
1. `get_file_contents` (or the listing/search helpers) can fetch the file you
   plan to change.
2. Prepare the new content locally in whatever workflow you prefer.
3. For one-file lint/doc fixes, `update_file_and_open_pr` commits that file and
   opens a PR in one call without cloning. For multiple files, use
   `update_files_and_open_pr` with `{path, content}` entries plus a PR title/body.

## Run tests or linters against pending changes
1. Provide a unified diff if you want `run_tests` or `run_command` to mirror
   your edits in a temporary clone by passing the `patch` argument.
2. Review `stdout`/`stderr` from the response; the server truncates outputs to
   keep results compact.

## Kick off or monitor workflows
* Use `trigger_workflow_dispatch` to start a workflow by filename.
* Call `trigger_and_wait_for_workflow` to dispatch and poll for completion when
  you need a single synchronous result.

These recipes mirror flows that have worked well in practice but are not
mandatory; use them only when they help.
