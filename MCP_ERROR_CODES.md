# MCP error codes and failure modes for Joeys GitHub MCP

This document describes the most common ways tool calls can fail when using the Joeys GitHub MCP server and what assistants should do next.

The main layers that can fail are:

1. The MCP host and ChatGPT.
2. The Joeys GitHub MCP server code in this repo.
3. GitHub and Render infrastructure.

Assistants should always capture the exact error text shown in ChatGPT and, when possible, the structured error fields returned by the tool result. That context should be summarized for Joey before asking to change code or settings.

## 1. GitHub and MCP tool errors

These errors come from the server itself or directly from the GitHub API.

### GitHubAPIError

Most GitHub failures are wrapped as a GitHubAPIError with details such such as status code and message. Common causes include:

- Repository not found or wrong full_name.
- Branch or ref does not exist.
- Path does not exist at the requested ref.
- Permission issues when token scopes are not sufficient.

When an assistant sees a GitHubAPIError they should:

1. Repeat back the key fields such as status and message.
2. Double check full_name, branch or ref, and file paths.
3. Ask Joey before assuming scopes or permissions need to change.

### content_url validation errors

Some tools accept either inline content or a content_url value. The server enforces that content_url must be an absolute http or https URL, or a sandbox path that the host rewrites before the request reaches this server.

If a content_url is missing or has an unsupported scheme, the server returns a clear validation error instead of attempting a network call. Assistants should:

- Prefer apply_patch_and_open_pr for code changes instead of sending full file bodies.
- Only use content_url when Joey explicitly wants a larger document committed from an external location.

### apply_patch_and_open_pr error field

The apply_patch_and_open_pr tool returns an error field that indicates where the workflow failed. Typical values include:

- git_checkout_failed
- git_apply_failed
- empty_patch
- empty_diff
- git_commit_failed
- tests_failed
- git_push_failed

Alongside error, the result usually contains stderr text from the failing step and sometimes a tests section when tests were run.

Assistants should:

1. Quote the error value and summarize any stderr lines that look important.
2. For git_apply_failed, regenerate a smaller or simpler patch and try again.
3. For empty_patch, rebuild the diff to include the intended changes; the server returns immediately before cloning or applying.
4. For empty_diff, double-check that the diff actually changes files; identical old/new hunks will be rejected after patching.
5. For tests_failed, summarize which tests failed and ask Joey whether to fix the tests in this PR or open a follow up task.
6. For git_checkout_failed or git_push_failed, confirm the target branch and that Joey has not force pushed conflicting history.

## 2. ChatGPT side and MCP host errors

These errors appear inside ChatGPT even when the server is healthy. Examples include:

- Invocation is blocked on safety.
- Tool call timed out.
- JSON validation or argument size errors.

When this happens, assistants should:

1. Avoid retrying exactly the same giant patch or payload.
2. Split large diffs into smaller patches or multiple PRs.
3. Keep each apply_patch_and_open_pr patch under roughly five hundred lines and around twenty thousand characters.
4. Report the failure to Joey in plain language before attempting a different approach.

## 3. Render and infrastructure failures

Sometimes the Render service or underlying container can fail even when the code and tools are correct. This can show up as:

- Connection errors reaching the /sse endpoint.
- Unusual HTTP status codes such as 502, 503, or 504.
- Logs mentioning out of memory, container restart, or similar messages.

When assistants suspect an infrastructure problem they should:

1. Tell Joey exactly which tool failed and what status code or message was returned.
2. Avoid spamming retries; a single retry is fine, but repeated failures usually mean Joey needs to check Render logs or adjust the plan.
3. Pause further write heavy operations until Joey confirms the service is healthy again.

By following this guide assistants can keep Joey fully informed about failures and avoid making risky changes when the underlying problem is outside the code or tools themselves.
