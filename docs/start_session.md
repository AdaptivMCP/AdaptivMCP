# start_session: GitHub MCP session protocol

This document describes how assistants should start and run sessions when using the GitHub MCP server for this controller repo (Proofgate-Revocations/chatgpt-mcp-github).

## Goals

- Reduce invalid tool calls
- Keep long workflows from getting stuck
- Provide a single protocol that controllers can copy into system prompts

## 1. Startup sequence

At the start of a new conversation, or after context loss, do these tool calls in order:

1. Call `get_server_config` to learn write_allowed, default branch, and limits.
2. Call `controller_contract` with compact set to true to load expectations and guardrails.
3. Call `list_all_actions` with include_parameters set to true so you know every tool and its JSON schema.

Treat the results of these tools as the source of truth for the rest of the session.

## 2. Tool arguments and validation

- Follow each tool's declared parameter schema exactly.
- Build arguments as literal JSON objects, not strings containing JSON.
- Do not invent parameters that are not documented in `list_all_actions`.

Before using a write tool, or a tool you have not called yet in this conversation:

1. Prepare the arguments you plan to use.
2. Call `validate_tool_args` with the tool name and those arguments.
3. Only call the real tool when validation reports valid is true.

If a tool call fails because of argument or schema errors:

- Stop guessing.
- Re-read the tool definition from `list_all_actions`.
- Fix the payload and re-run `validate_tool_args` before trying again.

## 3. Editing, branches, and pull requests

- Check `get_server_config` to confirm that write actions are allowed.
- Prefer diff based tools such as `build_unified_diff`, `build_section_based_diff`, and commit helpers instead of rewriting whole files.
- For larger work, use `ensure_workspace_clone`, `run_command`, and `run_tests` to work inside the persistent workspace.
- Prefer working on feature branches and open pull requests into the default branch unless the user says otherwise.

## 4. Long workflows

For non trivial tasks:

- Write a short numbered plan.
- Execute a few steps at a time.
- After each batch of work, summarize what changed and what is next.

If you see repeated failures on the same operation:

- After two failed tool calls, stop retrying.
- Re-check the schema and use `validate_tool_args`.
- If you still cannot progress, explain the blocker to the user instead of looping.

## 5. Interaction with the user

- Do not ask the user to run shell commands or apply patches by hand.
- Clearly state which files, branches, and tools you used.
- When you open a pull request, include what changed, why, and how it was tested.