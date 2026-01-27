# Adaptiv MCP Tools & Payload Shapes

## Overview

Adaptiv MCP tools accept JSON objects that conform to the input schemas published by the server. Tool invocations always return JSON-serializable payloads. On success, the shape depends on the tool; on failure, tools may either raise (surfaced via the server) or return a structured error envelope. The sections below describe the shared payload patterns and then enumerate every tool with its published input schema.

## Common Output Payload Shapes

### Structured tool error envelope

Tools that catch exceptions return a structured error payload with consistent top-level keys:

```json
{
  "status": "error",
  "ok": false,
  "error": "Human readable message",
  "error_detail": {
    "message": "Detailed message",
    "category": "validation|auth|rate_limit|patch|internal|...",
    "code": "OPTIONAL_CODE",
    "details": {"any": "structured details"},
    "retryable": false,
    "hint": "Optional remediation hint",
    "origin": "Optional origin label",
    "trace": {"optional": "trace"},
    "debug": {"args": {"...": "..."}, "arg_keys": ["..."]}
  },
  "context": "optional tool context",
  "path": "optional path",
  "request": {"optional": "request metadata"},
  "tool_surface": "optional tool surface",
  "routing_hint": {"optional": "routing hint"},
  "tool_descriptor": {"optional": "tool descriptor"},
  "tool_descriptor_text": "optional tool descriptor string"
}
```

Cancellations use the same envelope with `status: "cancelled"` and `error: "cancelled"`.

### GitHub API response payload

Tools backed by the GitHub REST/GraphQL APIs return a standardized payload with response metadata:

```json
{
  "status_code": 200,
  "headers": {"header": "value"},
  "json": {"GitHub": "response body"}
}
```

If `expect_json=false`, the payload contains `text` instead of `json`.

### Render API response payload

Render API tools return the same shape as GitHub API responses (status_code, headers, json/text), but the JSON body is the Render response.

### Workspace shell result

Workspace shell execution helpers return:

```json
{
  "exit_code": 0,
  "timed_out": false,
  "stdout": "...",
  "stderr": "...",
  "stdout_truncated": false,
  "stderr_truncated": false
}
```

### Terminal/command tool payloads (`terminal_command`, `render_shell`, aliases)

Command tools wrap shell results with execution metadata:

```json
{
  "status": "ok|failed",
  "ok": true,
  "error": "optional error",
  "error_detail": {"exit_code": 1, "timed_out": false},
  "workdir": "/abs/path",
  "command": "<command>",
  "command_lines": ["<line>", "..."],
  "install": {"skipped": false, "...": "..."},
  "install_steps": ["..."],
  "result": {"exit_code": 0, "stdout": "..."},
  "auto_push_branch": {"optional": "auto push metadata"},
  "test_artifact_cleanup": {"optional": "cleanup summary"}
}
```

### Workspace file/content payloads

Workspace read helpers (`get_workspace_file_contents`, `read_workspace_file_excerpt`, etc.) return dictionaries that include repo/ref identifiers plus file content/metadata, such as:

```json
{
  "full_name": "owner/repo",
  "ref": "main",
  "path": "relative/path",
  "exists": true,
  "text": "file contents",
  "encoding": "utf-8",
  "size_bytes": 1234,
  "truncated": false
}
```

Multi-file reads (`get_workspace_files_contents`) add `files`, `missing_paths`, `errors`, and a `summary` block with counts and truncation flags.

### Workspace diff payloads

Git diff tools (`workspace_git_diff`, `make_workspace_diff`, `make_diff`, etc.) return the diff plus metadata:

```json
{
  "full_name": "owner/repo",
  "ref": "main",
  "left_ref": "optional",
  "right_ref": "optional",
  "staged": false,
  "paths": ["optional/path"],
  "context_lines": 3,
  "diff": "unified diff text",
  "truncated": false,
  "numstat": [{"path": "file", "added": 1, "removed": 2, "is_binary": false}]
}
```

### Workspace commit payloads

Commit helpers return commit metadata and slimmed shell results:

```json
{
  "branch": "main",
  "changed_files": ["file"],
  "commit_sha": "<sha>",
  "commit_summary": "<oneline>",
  "commit": {"exit_code": 0, "stdout": "..."},
  "push": {"exit_code": 0, "stdout": "..."}
}
```

### Workspace quality suite payloads

Test/lint/quality suite tools return a top-level status plus a list of steps:

```json
{
  "status": "passed|failed|no_tests",
  "workdir": "optional",
  "steps": [{"name": "tests", "status": "passed", "summary": {"exit_code": 0}}],
  "controller_log": ["human readable log entries"]
}
```

### Workspace virtualenv payloads

Virtualenv tools expose a `venv` object from the workspace status helper:

```json
{
  "ref": "main",
  "venv": {
    "venv_dir": "/path/.venv-mcp",
    "exists": true,
    "python_exists": true,
    "ready": true,
    "python_path": "/path/.venv-mcp/bin/python"
  }
}
```

## Tool Input Schemas (Authoritative)

This section enumerates every registered tool and the JSON input schema published by the server. These schemas reflect the payload shapes clients must send when invoking the tool.

### `apply_diff`

- Write action: `true`
- Description:

```text
Backward-compatible alias for :func:`apply_workspace_diff`.  Schema: add:boolean=False, check_changes:boolean=False, commit:boolean=False, commit_message:string=Apply diff, diff*:any, full_name*:string, push:boolean=False, ref:string=main

Tool metadata:
- name: apply_diff
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- add (boolean; optional, default=False)
- check_changes (boolean; optional, default=False)
- commit (boolean; optional, default=False)
- commit_message (string; optional, default='Apply diff')
- diff (unknown; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- push (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "add": {
      "default": false,
      "title": "Add",
      "type": "boolean"
    },
    "check_changes": {
      "default": false,
      "title": "Check Changes",
      "type": "boolean"
    },
    "commit": {
      "default": false,
      "title": "Commit",
      "type": "boolean"
    },
    "commit_message": {
      "default": "Apply diff",
      "title": "Commit Message",
      "type": "string"
    },
    "diff": {
      "title": "Diff"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "push": {
      "default": false,
      "title": "Push",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "diff"
  ],
  "title": "Apply Diff",
  "type": "object"
}
```

### `apply_patch`

- Write action: `true`
- Description:

```text
Apply one or more unified diff patches to the persistent repo mirror.  Schema: add:boolean=False, check_changes:boolean=False, commit:boolean=False, commit_message:string=Apply patch, full_name*:string, patch*:any, push:boolean=False, ref:string=main

Args:
  patch: a unified diff string or a list of unified diff strings.
  add: if true, stage changes after applying.
  commit: if true, create a local commit after applying (requires changes).
  push: if true, push the created commit to origin (requires commit=true and a branch ref).
  check_changes: if true, include `status_output` (git status porcelain) in the response.

Returns:
  A dict with stable keys: ref, status, ok, patches_applied (+ optional diff_stats/status_output).

Notes:
  - Visual tool logs look for `__log_diff` in the *raw* tool payload. The decorator wrapper
    strips `__log_*` fields from the client-facing response by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - To avoid leaking patch contents in error responses, we only include short digests.

Tool metadata:
- name: apply_patch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- add (boolean; optional, default=False)
- check_changes (boolean; optional, default=False)
- commit (boolean; optional, default=False)
- commit_message (string; optional, default='Apply patch')
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- patch (unknown; required)
- push (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "add": {
      "default": false,
      "title": "Add",
      "type": "boolean"
    },
    "check_changes": {
      "default": false,
      "title": "Check Changes",
      "type": "boolean"
    },
    "commit": {
      "default": false,
      "title": "Commit",
      "type": "boolean"
    },
    "commit_message": {
      "default": "Apply patch",
      "title": "Commit Message",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "patch": {
      "title": "Patch"
    },
    "push": {
      "default": false,
      "title": "Push",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "patch"
  ],
  "title": "Apply Patch",
  "type": "object"
}
```

### `apply_text_update_and_commit`

- Write action: `true`
- Description:

```text
Apply Text Update And Commit. Signature: apply_text_update_and_commit(full_name: str, path: str, updated_content: str, *, branch: str = 'main', message: str | None = None, return_diff: bool = False) -> dict[str, typing.Any].  Schema: branch:string=main, full_name*:string, message:any, path*:string, return_diff:boolean=False, updated_content*:string

Tool metadata:
- name: apply_text_update_and_commit
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- branch (string; optional, default='main')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (unknown; optional)
  Commit message.
  Examples: 'Refactor tool schemas'
- path (string; required)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- return_diff (boolean; optional, default=False)
- updated_content (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": "main",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "message": {
      "default": null,
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message"
    },
    "path": {
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "return_diff": {
      "default": false,
      "title": "Return Diff",
      "type": "boolean"
    },
    "updated_content": {
      "title": "Updated Content",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "path",
    "updated_content"
  ],
  "title": "Apply Text Update And Commit",
  "type": "object"
}
```

### `apply_workspace_diff`

- Write action: `true`
- Description:

```text
Apply one or more unified diffs to the persistent repo mirror.  Schema: add:boolean=False, check_changes:boolean=False, commit:boolean=False, commit_message:string=Apply diff, diff*:any, full_name*:string, push:boolean=False, ref:string=main

Tool metadata:
- name: apply_workspace_diff
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- add (boolean; optional, default=False)
- check_changes (boolean; optional, default=False)
- commit (boolean; optional, default=False)
- commit_message (string; optional, default='Apply diff')
- diff (unknown; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- push (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "add": {
      "default": false,
      "title": "Add",
      "type": "boolean"
    },
    "check_changes": {
      "default": false,
      "title": "Check Changes",
      "type": "boolean"
    },
    "commit": {
      "default": false,
      "title": "Commit",
      "type": "boolean"
    },
    "commit_message": {
      "default": "Apply diff",
      "title": "Commit Message",
      "type": "string"
    },
    "diff": {
      "title": "Diff"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "push": {
      "default": false,
      "title": "Push",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "diff"
  ],
  "title": "Apply Workspace Diff",
  "type": "object"
}
```

### `apply_workspace_operations`

- Write action: `true`
- Description:

```text
Apply multiple file operations in a single workspace mirror.  Schema: create_parents:boolean=True, fail_fast:boolean=True, full_name*:string, operations:any, preview_only:boolean=False, ref:string=main, rollback_on_error:boolean=True

This is a higher-level, multi-file alternative to calling the single-file
primitives repeatedly.

Supported operations (each item in `operations`):
  - {"op": "write", "path": "...", "content": "..."}
  - {"op": "replace_text", "path": "...", "old": "...", "new": "...", "replace_all": bool, "occurrence": int}
  - {"op": "edit_range", "path": "...", "start": {"line": int, "col": int}, "end": {"line": int, "col": int}, "replacement": "..."}
  - {"op": "delete_lines", "path": "...", "start_line": int, "end_line": int}
  - {"op": "delete_word", "path": "...", "word": "...", "occurrence": int, "replace_all": bool, "case_sensitive": bool, "whole_word": bool}
  - {"op": "delete_chars", "path": "...", "line": int, "col": int, "count": int}
  - {"op": "delete", "path": "...", "allow_missing": bool}
  - {"op": "mkdir", "path": "...", "exist_ok": bool, "parents": bool}
  - {"op": "rmdir", "path": "...", "allow_missing": bool, "allow_recursive": bool}
  - {"op": "move", "src": "...", "dst": "...", "overwrite": bool}
  - {"op": "apply_patch", "patch": "..."}
  - {"op": "read_sections", "path": "...", "start_line": int, "max_sections": int, "max_lines_per_section": int, "max_chars_per_section": int, "overlap_lines": int}

Tool metadata:
- name: apply_workspace_operations
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- create_parents (boolean; optional, default=True)
- fail_fast (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- operations (unknown; optional)
- preview_only (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- rollback_on_error (boolean; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "fail_fast": {
      "default": true,
      "title": "Fail Fast",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "operations": {
      "default": null,
      "title": "Operations"
    },
    "preview_only": {
      "default": false,
      "title": "Preview Only",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "rollback_on_error": {
      "default": true,
      "title": "Rollback On Error",
      "type": "boolean"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Apply Workspace Operations",
  "type": "object"
}
```

### `build_pr_summary`

- Write action: `false`
- Description:

```text
Build a normalized JSON summary for a pull request description.  Schema: body*:string, breaking_changes:any, changed_files:any, full_name*:string, lint_status:any, ref*:string, tests_status:any, title*:string

Tool metadata:
- name: build_pr_summary
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- body (string; required)
- breaking_changes (unknown; optional)
- changed_files (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- lint_status (unknown; optional)
- ref (string; required)
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- tests_status (unknown; optional)
- title (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "body": {
      "title": "Body",
      "type": "string"
    },
    "breaking_changes": {
      "default": null,
      "title": "Breaking Changes"
    },
    "changed_files": {
      "default": null,
      "title": "Changed Files"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "lint_status": {
      "default": null,
      "title": "Lint Status"
    },
    "ref": {
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "tests_status": {
      "default": null,
      "title": "Tests Status"
    },
    "title": {
      "title": "Title",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "ref",
    "title",
    "body"
  ],
  "title": "Build Pr Summary",
  "type": "object"
}
```

### `cache_files`

- Write action: `false`
- Description:

```text
Fetch one or more files and persist them in the server-side cache so callers can reuse them without repeating GitHub reads. refresh=true bypasses existing cache entries.  Schema: full_name*:string, paths*:array, ref:string=main, refresh:boolean=False

Tool metadata:
- name: cache_files
- visibility: public
- write_action: false
- write_allowed: true
- tags: cache, files, github

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (array; required)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- refresh (boolean; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "paths": {
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "items": {},
      "title": "Paths",
      "type": "array"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "refresh": {
      "default": false,
      "title": "Refresh",
      "type": "boolean"
    }
  },
  "required": [
    "full_name",
    "paths"
  ],
  "title": "Cache Files",
  "type": "object"
}
```

### `cancel_render_deploy`

- Write action: `true`
- Description:

```text
Cancel an in-progress Render deploy.  Schema: deploy_id*:string, service_id*:string

Tool metadata:
- name: cancel_render_deploy
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "deploy_id": {
      "description": "Render deploy id (example: dpl-...).",
      "title": "Deploy Id",
      "type": "string"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Cancel Render Deploy",
  "type": "object"
}
```

### `close_pull_request`

- Write action: `true`
- Description:

```text
Close pull request. Signature: close_pull_request(full_name: str, number: int) -> dict[str, typing.Any].  Schema: full_name*:string, number*:integer

Tool metadata:
- name: close_pull_request
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "number": {
      "title": "Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "number"
  ],
  "title": "Close Pull Request",
  "type": "object"
}
```

### `comment_on_issue`

- Write action: `true`
- Description:

```text
Post a comment on an issue.  Schema: body*:string, full_name*:string, issue_number*:integer

Tool metadata:
- name: comment_on_issue
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- body (string; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "body": {
      "title": "Body",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "issue_number": {
      "title": "Issue Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "issue_number",
    "body"
  ],
  "title": "Comment On Issue",
  "type": "object"
}
```

### `comment_on_pull_request`

- Write action: `true`
- Description:

```text
Comment On Pull Request. Signature: comment_on_pull_request(full_name: str, number: int, body: str) -> dict[str, typing.Any].  Schema: body*:string, full_name*:string, number*:integer

Tool metadata:
- name: comment_on_pull_request
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- body (string; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "body": {
      "title": "Body",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "number": {
      "title": "Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "number",
    "body"
  ],
  "title": "Comment On Pull Request",
  "type": "object"
}
```

### `commit_and_open_pr_from_workspace`

- Write action: `true`
- Description:

```text
Commit repo mirror changes on `ref` and open a PR into `base`.  Schema: base:any=main, body:any, commit_message:any=Commit workspace changes, draft:any=False, full_name*:any, lint_command:any=ruff check ., quality_timeout_seconds:any=0, ref:any=main, +3 more

This helper is intended for the common "edit in repo mirror -> commit/push -> open PR" flow.

Notes:
- This tool only pushes to the current `ref` (feature branch). It does not mutate the base branch.
- When `run_quality` is enabled, lint/tests run before the commit is created.

Tool metadata:
- name: commit_and_open_pr_from_workspace
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- base (unknown; optional, default='main')
- body (unknown; optional)
- commit_message (unknown; optional, default='Commit workspace changes')
- draft (unknown; optional, default=False)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- lint_command (unknown; optional, default='ruff check .')
- quality_timeout_seconds (unknown; optional, default=0)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- run_quality (unknown; optional, default=False)
- test_command (unknown; optional, default='pytest -q')
- title (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base": {
      "default": "main",
      "title": "Base"
    },
    "body": {
      "default": null,
      "title": "Body"
    },
    "commit_message": {
      "default": "Commit workspace changes",
      "title": "Commit Message"
    },
    "draft": {
      "default": false,
      "title": "Draft"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "lint_command": {
      "default": "ruff check .",
      "title": "Lint Command"
    },
    "quality_timeout_seconds": {
      "default": 0,
      "title": "Quality Timeout Seconds"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "run_quality": {
      "default": false,
      "title": "Run Quality"
    },
    "test_command": {
      "default": "pytest -q",
      "title": "Test Command"
    },
    "title": {
      "default": null,
      "title": "Title"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Commit And Open Pr From Workspace",
  "type": "object"
}
```

### `commit_workspace`

- Write action: `true`
- Description:

```text
Commit repo mirror changes and optionally push them.  Schema: add_all:boolean=True, full_name:any, message:string=Commit workspace changes, push:boolean=True, ref:string=main

Tool metadata:
- name: commit_workspace
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- add_all (boolean; optional, default=True)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (string; optional, default='Commit workspace changes')
  Commit message.
  Examples: 'Refactor tool schemas'
- push (boolean; optional, default=True)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "add_all": {
      "default": true,
      "title": "Add All",
      "type": "boolean"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "message": {
      "default": "Commit workspace changes",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message",
      "type": "string"
    },
    "push": {
      "default": true,
      "title": "Push",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "title": "Commit Workspace",
  "type": "object"
}
```

### `commit_workspace_files`

- Write action: `true`
- Description:

```text
Commit and optionally push specific files from the persistent repo mirror.  Schema: files*:array, full_name*:any, message:string=Commit selected workspace changes, push:boolean=True, ref:string=main

Tool metadata:
- name: commit_workspace_files
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- files (array; required)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (string; optional, default='Commit selected workspace changes')
  Commit message.
  Examples: 'Refactor tool schemas'
- push (boolean; optional, default=True)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "files": {
      "items": {},
      "title": "Files",
      "type": "array"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "message": {
      "default": "Commit selected workspace changes",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message",
      "type": "string"
    },
    "push": {
      "default": true,
      "title": "Push",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "files"
  ],
  "title": "Commit Workspace Files",
  "type": "object"
}
```

### `compare_workspace_files`

- Write action: `false`
- Description:

```text
Compare multiple file pairs or ref/path variants and return diffs.  Schema: comparisons:any, context_lines:integer=3, full_name*:string, include_stats:boolean=False, max_chars_per_side:integer=200000, max_diff_chars:integer=200000, ref:string=main

Each entry in `comparisons` supports one of the following shapes:
  1) {"left_path": "a.txt", "right_path": "b.txt"}
     Compares two workspace paths.
  2) {"path": "a.txt", "base_ref": "main"}
     Compares the workspace file at `path` (current checkout) to the file
     content at `base_ref:path` via `git show`.
  3) {"left_ref": "main", "left_path": "a.txt", "right_ref": "feature", "right_path": "a.txt"}
     Compares two git object versions without changing checkout.

Returned diffs are unified diffs with full file contents.

If include_stats is true, each comparison result includes a "stats" object
with {added, removed} line counts derived from the full unified diff.

Tool metadata:
- name: compare_workspace_files
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- comparisons (unknown; optional)
- context_lines (integer; optional, default=3)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_stats (boolean; optional, default=False)
- max_chars_per_side (integer; optional, default=200000)
- max_diff_chars (integer; optional, default=200000)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "comparisons": {
      "default": null,
      "title": "Comparisons"
    },
    "context_lines": {
      "default": 3,
      "title": "Context Lines",
      "type": "integer"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "include_stats": {
      "default": false,
      "title": "Include Stats",
      "type": "boolean"
    },
    "max_chars_per_side": {
      "default": 200000,
      "title": "Max Chars Per Side",
      "type": "integer"
    },
    "max_diff_chars": {
      "default": 200000,
      "title": "Max Diff Chars",
      "type": "integer"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Compare Workspace Files",
  "type": "object"
}
```

### `create_branch`

- Write action: `true`
- Description:

```text
Create branch. Signature: create_branch(full_name: str, branch: str, from_ref: str = 'main') -> dict[str, typing.Any].  Schema: branch*:string, from_ref:string=main, full_name*:string

Tool metadata:
- name: create_branch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- branch (string; required)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- from_ref (string; optional, default='main')
  Ref to create the new branch from (branch/tag/SHA).
  Examples: 'main'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "from_ref": {
      "default": "main",
      "description": "Ref to create the new branch from (branch/tag/SHA).",
      "examples": [
        "main"
      ],
      "title": "From Ref",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Create Branch",
  "type": "object"
}
```

### `create_file`

- Write action: `true`
- Description:

```text
Create file. Signature: create_file(full_name: str, path: str, content: str, *, branch: str = 'main', message: str | None = None) -> dict[str, typing.Any].  Schema: branch:string=main, content*:string, full_name*:string, message:any, path*:string

Tool metadata:
- name: create_file
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- branch (string; optional, default='main')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- content (string; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (unknown; optional)
  Commit message.
  Examples: 'Refactor tool schemas'
- path (string; required)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": "main",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "content": {
      "title": "Content",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "message": {
      "default": null,
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message"
    },
    "path": {
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "path",
    "content"
  ],
  "title": "Create File",
  "type": "object"
}
```

### `create_issue`

- Write action: `true`
- Description:

```text
Create a GitHub issue in the given repository.  Schema: assignees:any, body:any, full_name*:string, labels:any, title*:string

Tool metadata:
- name: create_issue
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- assignees (unknown; optional)
- body (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- labels (unknown; optional)
- title (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "assignees": {
      "default": null,
      "title": "Assignees"
    },
    "body": {
      "default": null,
      "title": "Body"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "labels": {
      "default": null,
      "title": "Labels"
    },
    "title": {
      "title": "Title",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "title"
  ],
  "title": "Create Issue",
  "type": "object"
}
```

### `create_pull_request`

- Write action: `true`
- Description:

```text
Open a pull request from ``head`` into ``base``.  Schema: base:string=main, body:any, draft:boolean=False, full_name*:string, head*:string, title*:string

The base branch is normalized via ``_effective_ref_for_repo`` so that
controller repos honor the configured default branch even when callers
supply a simple base name like "main".

Tool metadata:
- name: create_pull_request
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- base (string; optional, default='main')
- body (unknown; optional)
- draft (boolean; optional, default=False)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- head (string; required)
- title (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base": {
      "default": "main",
      "title": "Base",
      "type": "string"
    },
    "body": {
      "default": null,
      "title": "Body"
    },
    "draft": {
      "default": false,
      "title": "Draft",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "head": {
      "title": "Head",
      "type": "string"
    },
    "title": {
      "title": "Title",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "title",
    "head"
  ],
  "title": "Create Pull Request",
  "type": "object"
}
```

### `create_render_deploy`

- Write action: `true`
- Description:

```text
Trigger a new deploy for a Render service.  Schema: clear_cache:boolean=False, commit_id:any, image_url:any, service_id*:string

Tool metadata:
- name: create_render_deploy
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- clear_cache (boolean; optional, default=False)
  When true, clears the build cache before deploying.
  Examples: True, False
- commit_id (unknown; optional)
  Optional git commit SHA to deploy (repo-backed services).
- image_url (unknown; optional)
  Optional container image URL to deploy (image-backed services).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "clear_cache": {
      "default": false,
      "description": "When true, clears the build cache before deploying.",
      "examples": [
        true,
        false
      ],
      "title": "Clear Cache",
      "type": "boolean"
    },
    "commit_id": {
      "default": null,
      "description": "Optional git commit SHA to deploy (repo-backed services).",
      "title": "Commit Id"
    },
    "image_url": {
      "default": null,
      "description": "Optional container image URL to deploy (image-backed services).",
      "title": "Image Url"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "Create Render Deploy",
  "type": "object"
}
```

### `create_render_service`

- Write action: `true`
- Description:

```text
Create a new Render service.  Schema: service_spec*:object

Tool metadata:
- name: create_render_service
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- service_spec (object; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "service_spec": {
      "additionalProperties": true,
      "title": "Service Spec",
      "type": "object"
    }
  },
  "required": [
    "service_spec"
  ],
  "title": "Create Render Service",
  "type": "object"
}
```

### `create_repository`

- Write action: `true`
- Description:

```text
Create repository. Signature: create_repository(name: str, owner: str | None = None, owner_type: Literal['auto', 'user', 'org'] = 'auto', description: str | None = None, homepage: str | None = None, visibility: Optional[Literal['public', 'private', 'internal']] = None, private: bool | None = None, auto_init: bool = True, gitignore_template: str | None = None, license_template: str | None = None, is_template: bool = False, has_issues: bool = True, has_projects: bool | None = None, has_wiki: bool = True, has_discussions: bool | None = None, team_id: int | None = None, security_and_analysis: dict[str, typing.Any] | None = None, template_full_name: str | None = None, include_all_branches: bool = False, topics: list[str] | None = None, create_payload_overrides: dict[str, typing.Any] | None = None, update_payload_overrides: dict[str, typing.Any] | None = None, clone_to_workspace: bool = False, clone_ref: str | None = None) -> dict[str, typing.Any].  Schema: auto_init:boolean=True, clone_ref:any, clone_to_workspace:boolean=False, create_payload_overrides:any, description:any, gitignore_template:any, has_discussions:any, has_issues:boolean=True, +16 more

Tool metadata:
- name: create_repository
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- auto_init (boolean; optional, default=True)
- clone_ref (unknown; optional)
- clone_to_workspace (boolean; optional, default=False)
- create_payload_overrides (unknown; optional)
- description (unknown; optional)
- gitignore_template (unknown; optional)
- has_discussions (unknown; optional)
- has_issues (boolean; optional, default=True)
- has_projects (unknown; optional)
- has_wiki (boolean; optional, default=True)
- homepage (unknown; optional)
- include_all_branches (boolean; optional, default=False)
- is_template (boolean; optional, default=False)
- license_template (unknown; optional)
- name (string; required)
- owner (unknown; optional)
- owner_type (string; optional, default='auto')
- private (unknown; optional)
- security_and_analysis (unknown; optional)
- team_id (unknown; optional)
- template_full_name (unknown; optional)
- topics (unknown; optional)
- update_payload_overrides (unknown; optional)
- visibility (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "auto_init": {
      "default": true,
      "title": "Auto Init",
      "type": "boolean"
    },
    "clone_ref": {
      "default": null,
      "title": "Clone Ref"
    },
    "clone_to_workspace": {
      "default": false,
      "title": "Clone To Workspace",
      "type": "boolean"
    },
    "create_payload_overrides": {
      "default": null,
      "title": "Create Payload Overrides"
    },
    "description": {
      "default": null,
      "title": "Description"
    },
    "gitignore_template": {
      "default": null,
      "title": "Gitignore Template"
    },
    "has_discussions": {
      "default": null,
      "title": "Has Discussions"
    },
    "has_issues": {
      "default": true,
      "title": "Has Issues",
      "type": "boolean"
    },
    "has_projects": {
      "default": null,
      "title": "Has Projects"
    },
    "has_wiki": {
      "default": true,
      "title": "Has Wiki",
      "type": "boolean"
    },
    "homepage": {
      "default": null,
      "title": "Homepage"
    },
    "include_all_branches": {
      "default": false,
      "title": "Include All Branches",
      "type": "boolean"
    },
    "is_template": {
      "default": false,
      "title": "Is Template",
      "type": "boolean"
    },
    "license_template": {
      "default": null,
      "title": "License Template"
    },
    "name": {
      "title": "Name",
      "type": "string"
    },
    "owner": {
      "default": null,
      "title": "Owner"
    },
    "owner_type": {
      "default": "auto",
      "title": "Owner Type",
      "type": "string"
    },
    "private": {
      "default": null,
      "title": "Private"
    },
    "security_and_analysis": {
      "default": null,
      "title": "Security And Analysis"
    },
    "team_id": {
      "default": null,
      "title": "Team Id"
    },
    "template_full_name": {
      "default": null,
      "title": "Template Full Name"
    },
    "topics": {
      "default": null,
      "title": "Topics"
    },
    "update_payload_overrides": {
      "default": null,
      "title": "Update Payload Overrides"
    },
    "visibility": {
      "default": null,
      "title": "Visibility"
    }
  },
  "required": [
    "name"
  ],
  "title": "Create Repository",
  "type": "object"
}
```

### `create_workspace_folders`

- Write action: `true`
- Description:

```text
Create one or more folders in the repo mirror.  Schema: create_parents:boolean=True, exist_ok:boolean=True, full_name*:string, paths:any, ref:string=main

Notes:
  - `paths` must be repo-relative paths.
  - When `exist_ok` is false, existing folders are treated as failures.

Tool metadata:
- name: create_workspace_folders
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- create_parents (boolean; optional, default=True)
- exist_ok (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "exist_ok": {
      "default": true,
      "title": "Exist Ok",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Create Workspace Folders",
  "type": "object"
}
```

### `delete_file`

- Write action: `true`
- Description:

```text
Delete a file from a GitHub repository using the Contents API. Often used in combination with branch management helpers.  Schema: branch:any=main, full_name*:any, if_missing:any=error, message:any=Delete file via MCP GitHub connector, path*:any

Tool metadata:
- name: delete_file
- visibility: public
- write_action: true
- write_allowed: true
- tags: delete, files, github, write

Parameters:
- branch (unknown; optional, default='main')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- if_missing (unknown; optional, default='error')
- message (unknown; optional, default='Delete file via MCP GitHub connector')
  Commit message.
  Examples: 'Refactor tool schemas'
- path (unknown; required)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": "main",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "if_missing": {
      "default": "error",
      "title": "If Missing"
    },
    "message": {
      "default": "Delete file via MCP GitHub connector",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message"
    },
    "path": {
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    }
  },
  "required": [
    "full_name",
    "path"
  ],
  "title": "Delete File",
  "type": "object"
}
```

### `delete_workspace_char`

- Write action: `true`
- Description:

```text
Delete one or more characters starting at a (line, col) position.  Schema: col:integer=1, count:integer=1, create_parents:boolean=True, full_name*:string, line:integer=1, path:string=, ref:string=main

Positions are 1-indexed. `count` is measured in Python string characters.

Tool metadata:
- name: delete_workspace_char
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- col (integer; optional, default=1)
- count (integer; optional, default=1)
- create_parents (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- line (integer; optional, default=1)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "col": {
      "default": 1,
      "title": "Col",
      "type": "integer"
    },
    "count": {
      "default": 1,
      "title": "Count",
      "type": "integer"
    },
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "line": {
      "default": 1,
      "title": "Line",
      "type": "integer"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Delete Workspace Char",
  "type": "object"
}
```

### `delete_workspace_folders`

- Write action: `true`
- Description:

```text
Delete one or more folders from the repo mirror.  Schema: allow_missing:boolean=True, allow_recursive:boolean=False, full_name*:string, paths:any, ref:string=main

Notes:
  - `paths` must be repo-relative paths.
  - Non-empty folders require `allow_recursive=true`.

Tool metadata:
- name: delete_workspace_folders
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- allow_missing (boolean; optional, default=True)
- allow_recursive (boolean; optional, default=False)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "allow_missing": {
      "default": true,
      "title": "Allow Missing",
      "type": "boolean"
    },
    "allow_recursive": {
      "default": false,
      "title": "Allow Recursive",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Delete Workspace Folders",
  "type": "object"
}
```

### `delete_workspace_lines`

- Write action: `true`
- Description:

```text
Delete one or more whole lines from a workspace file.  Schema: create_parents:boolean=True, end_line:integer=1, full_name*:string, path:string=, ref:string=main, start_line:integer=1

Line numbers are 1-indexed and inclusive. Deleting a single line is the same
as setting start_line=end_line.

This is a convenience wrapper over edit_workspace_text_range where the range
spans complete lines (including their newline when present).

Tool metadata:
- name: delete_workspace_lines
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- create_parents (boolean; optional, default=True)
- end_line (integer; optional, default=1)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- start_line (integer; optional, default=1)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "end_line": {
      "default": 1,
      "title": "End Line",
      "type": "integer"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "start_line": {
      "default": 1,
      "title": "Start Line",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Delete Workspace Lines",
  "type": "object"
}
```

### `delete_workspace_paths`

- Write action: `true`
- Description:

```text
Delete one or more paths from the repo mirror.  Schema: allow_missing:boolean=True, allow_recursive:boolean=False, full_name*:string, paths:any, ref:string=main

This tool exists because some environments can block patch-based file deletions.
Prefer this over embedding deletions into unified-diff patches.

Notes:
  - `paths` must be repo-relative paths.
  - Directories require `allow_recursive=true` (for non-empty directories).

Tool metadata:
- name: delete_workspace_paths
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- allow_missing (boolean; optional, default=True)
- allow_recursive (boolean; optional, default=False)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "allow_missing": {
      "default": true,
      "title": "Allow Missing",
      "type": "boolean"
    },
    "allow_recursive": {
      "default": false,
      "title": "Allow Recursive",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Delete Workspace Paths",
  "type": "object"
}
```

### `delete_workspace_word`

- Write action: `true`
- Description:

```text
Delete a word (or substring) from a workspace file.  Schema: case_sensitive:boolean=True, create_parents:boolean=True, full_name*:string, occurrence:integer=1, path:string=, ref:string=main, replace_all:boolean=False, whole_word:boolean=True, +1 more

- occurrence is 1-indexed (ignored when replace_all=True)
- when whole_word=True, word boundaries () are used

Tool metadata:
- name: delete_workspace_word
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- case_sensitive (boolean; optional, default=True)
- create_parents (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- occurrence (integer; optional, default=1)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- replace_all (boolean; optional, default=False)
- whole_word (boolean; optional, default=True)
- word (string; optional, default='')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "case_sensitive": {
      "default": true,
      "title": "Case Sensitive",
      "type": "boolean"
    },
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "occurrence": {
      "default": 1,
      "title": "Occurrence",
      "type": "integer"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "replace_all": {
      "default": false,
      "title": "Replace All",
      "type": "boolean"
    },
    "whole_word": {
      "default": true,
      "title": "Whole Word",
      "type": "boolean"
    },
    "word": {
      "default": "",
      "title": "Word",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Delete Workspace Word",
  "type": "object"
}
```

### `describe_tool`

- Write action: `false`
- Description:

```text
Return optional schema for one or more tools. Prefer this over manually scanning list_all_actions in long sessions.  Schema: include_parameters:boolean=True, name:any, names:any

Tool metadata:
- name: describe_tool
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- include_parameters (boolean; optional, default=True)
- name (unknown; optional)
- names (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "include_parameters": {
      "default": true,
      "title": "Include Parameters",
      "type": "boolean"
    },
    "name": {
      "default": null,
      "title": "Name"
    },
    "names": {
      "default": null,
      "title": "Names"
    }
  },
  "title": "Describe Tool",
  "type": "object"
}
```

### `download_user_content`

- Write action: `false`
- Description:

```text
Download user-provided content (sandbox/local/http) with base64 encoding.  Schema: content_url*:string

Tool metadata:
- name: download_user_content
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- content_url (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "content_url": {
      "title": "Content Url",
      "type": "string"
    }
  },
  "required": [
    "content_url"
  ],
  "title": "Download User Content",
  "type": "object"
}
```

### `edit_workspace_line`

- Write action: `true`
- Description:

```text
Edit a single line in a workspace file.  Schema: create_parents:boolean=True, full_name*:string, line_number:integer=1, operation:string=replace, path:string=, ref:string=main, text:string=

Operations:
  - replace: replace the target line's content (preserves its line ending).
  - insert_before / insert_after: insert a new line adjacent to line_number.
  - delete: delete the target line.

Line numbers are 1-indexed.

Tool metadata:
- name: edit_workspace_line
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- create_parents (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- line_number (integer; optional, default=1)
- operation (string; optional, default='replace')
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- text (string; optional, default='')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "line_number": {
      "default": 1,
      "title": "Line Number",
      "type": "integer"
    },
    "operation": {
      "default": "replace",
      "title": "Operation",
      "type": "string"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "text": {
      "default": "",
      "title": "Text",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Edit Workspace Line",
  "type": "object"
}
```

### `edit_workspace_text_range`

- Write action: `true`
- Description:

```text
Edit a file by replacing a precise (line, column) text range.  Schema: create_parents:boolean=True, end_col:integer=1, end_line:integer=1, full_name*:string, path:string=, ref:string=main, replacement:string=, start_col:integer=1, +1 more

This is the most granular edit primitive:
  - Single-character edit: start=(L,C), end=(L,C+1)
  - Word edit: start/end wrap the word
  - Line edit: start=(L,1), end=(L+1,1) (includes the newline)

Positions are 1-indexed. The end position is *exclusive* (Python-slice
semantics).

Tool metadata:
- name: edit_workspace_text_range
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- create_parents (boolean; optional, default=True)
- end_col (integer; optional, default=1)
- end_line (integer; optional, default=1)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- replacement (string; optional, default='')
- start_col (integer; optional, default=1)
- start_line (integer; optional, default=1)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "end_col": {
      "default": 1,
      "title": "End Col",
      "type": "integer"
    },
    "end_line": {
      "default": 1,
      "title": "End Line",
      "type": "integer"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "replacement": {
      "default": "",
      "title": "Replacement",
      "type": "string"
    },
    "start_col": {
      "default": 1,
      "title": "Start Col",
      "type": "integer"
    },
    "start_line": {
      "default": 1,
      "title": "Start Line",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Edit Workspace Text Range",
  "type": "object"
}
```

### `ensure_branch`

- Write action: `true`
- Description:

```text
Ensure branch. Signature: ensure_branch(full_name: str, branch: str, from_ref: str = 'main') -> dict[str, typing.Any].  Schema: branch*:string, from_ref:string=main, full_name*:string

Tool metadata:
- name: ensure_branch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- branch (string; required)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- from_ref (string; optional, default='main')
  Ref to create the new branch from (branch/tag/SHA).
  Examples: 'main'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "from_ref": {
      "default": "main",
      "description": "Ref to create the new branch from (branch/tag/SHA).",
      "examples": [
        "main"
      ],
      "title": "From Ref",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Ensure Branch",
  "type": "object"
}
```

### `ensure_workspace_clone`

- Write action: `true`
- Description:

```text
Ensure a persistent workspace mirror exists for a repo/ref.  Schema: full_name:any, ref:any=main, reset:any=False

Tool metadata:
- name: ensure_workspace_clone
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- reset (unknown; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "reset": {
      "default": false,
      "title": "Reset"
    }
  },
  "title": "Ensure Workspace Clone",
  "type": "object"
}
```

### `fetch_files`

- Write action: `false`
- Description:

```text
Fetch files. Signature: fetch_files(full_name: str, paths: list[str], ref: str = 'main') -> dict[str, typing.Any].  Schema: full_name*:string, paths*:array, ref:string=main

Tool metadata:
- name: fetch_files
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (array; required)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "paths": {
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "items": {},
      "title": "Paths",
      "type": "array"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "paths"
  ],
  "title": "Fetch Files",
  "type": "object"
}
```

### `fetch_issue`

- Write action: `false`
- Description:

```text
Fetch issue. Signature: fetch_issue(full_name: str, issue_number: int) -> dict[str, typing.Any].  Schema: full_name*:string, issue_number*:integer

Tool metadata:
- name: fetch_issue
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "issue_number": {
      "title": "Issue Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Fetch Issue",
  "type": "object"
}
```

### `fetch_issue_comments`

- Write action: `false`
- Description:

```text
Fetch issue comments. Signature: fetch_issue_comments(full_name: str, issue_number: int, per_page: int = 30, page: int = 1) -> dict[str, typing.Any].  Schema: full_name*:string, issue_number*:integer, page:integer=1, per_page:integer=30

Tool metadata:
- name: fetch_issue_comments
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "issue_number": {
      "title": "Issue Number",
      "type": "integer"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Fetch Issue Comments",
  "type": "object"
}
```

### `fetch_pr`

- Write action: `false`
- Description:

```text
Fetch pull request. Signature: fetch_pr(full_name: str, pull_number: int) -> dict[str, typing.Any].  Schema: full_name*:string, pull_number*:integer

Tool metadata:
- name: fetch_pr
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- pull_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "pull_number": {
      "title": "Pull Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Fetch Pr",
  "type": "object"
}
```

### `fetch_pr_comments`

- Write action: `false`
- Description:

```text
Fetch pull request comments. Signature: fetch_pr_comments(full_name: str, pull_number: int, per_page: int = 30, page: int = 1) -> dict[str, typing.Any].  Schema: full_name*:string, page:integer=1, per_page:integer=30, pull_number*:integer

Tool metadata:
- name: fetch_pr_comments
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- pull_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "pull_number": {
      "title": "Pull Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Fetch Pr Comments",
  "type": "object"
}
```

### `fetch_url`

- Write action: `false`
- Description:

```text
Fetch URL. Signature: fetch_url(url: str) -> dict[str, typing.Any].  Schema: url*:string

Tool metadata:
- name: fetch_url
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- url (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "url": {
      "title": "Url",
      "type": "string"
    }
  },
  "required": [
    "url"
  ],
  "title": "Fetch Url",
  "type": "object"
}
```

### `find_workspace_paths`

- Write action: `false`
- Description:

```text
Find paths in the workspace by matching names.  Schema: cursor:integer=0, full_name:any, include_dirs:boolean=True, include_files:boolean=True, include_hidden:boolean=True, include_metadata:boolean=False, max_depth:integer=25, max_results:integer=500, +4 more

`pattern_type`:
  - "glob" (default): fnmatch-style glob applied to the basename.
  - "regex": Python regex applied to the repo-relative path.
  - "substring": simple substring match applied to the repo-relative path.

Returns paths in a stable lexicographic traversal order and supports offset
pagination via `cursor`.

Tool metadata:
- name: find_workspace_paths
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (integer; optional, default=0)
  Pagination cursor returned by the previous call.
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_dirs (boolean; optional, default=True)
- include_files (boolean; optional, default=True)
- include_hidden (boolean; optional, default=True)
- include_metadata (boolean; optional, default=False)
- max_depth (integer; optional, default=25)
- max_results (integer; optional, default=500)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- pattern (string; optional, default='')
- pattern_type (string; optional, default='glob')
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": 0,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor",
      "type": "integer"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "include_dirs": {
      "default": true,
      "title": "Include Dirs",
      "type": "boolean"
    },
    "include_files": {
      "default": true,
      "title": "Include Files",
      "type": "boolean"
    },
    "include_hidden": {
      "default": true,
      "title": "Include Hidden",
      "type": "boolean"
    },
    "include_metadata": {
      "default": false,
      "title": "Include Metadata",
      "type": "boolean"
    },
    "max_depth": {
      "default": 25,
      "title": "Max Depth",
      "type": "integer"
    },
    "max_results": {
      "default": 500,
      "title": "Max Results",
      "type": "integer"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "pattern": {
      "default": "",
      "title": "Pattern",
      "type": "string"
    },
    "pattern_type": {
      "default": "glob",
      "title": "Pattern Type",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "title": "Find Workspace Paths",
  "type": "object"
}
```

### `get_branch_summary`

- Write action: `false`
- Description:

```text
Get branch summary. Signature: get_branch_summary(full_name: str, branch: str, base: str = 'main') -> dict[str, typing.Any].  Schema: base:string=main, branch*:string, full_name*:string

Tool metadata:
- name: get_branch_summary
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- base (string; optional, default='main')
- branch (string; required)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base": {
      "default": "main",
      "title": "Base",
      "type": "string"
    },
    "branch": {
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Get Branch Summary",
  "type": "object"
}
```

### `get_cached_files`

- Write action: `false`
- Description:

```text
Return cached file payloads for a repository/ref without re-fetching from GitHub. Entries persist for the lifetime of the server process until evicted by size or entry caps.  Schema: full_name*:string, paths*:array, ref:string=main

Tool metadata:
- name: get_cached_files
- visibility: public
- write_action: false
- write_allowed: true
- tags: cache, files, github

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (array; required)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "paths": {
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "items": {},
      "title": "Paths",
      "type": "array"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "paths"
  ],
  "title": "Get Cached Files",
  "type": "object"
}
```

### `get_commit_combined_status`

- Write action: `false`
- Description:

```text
Get commit combined status. Signature: get_commit_combined_status(full_name: str, ref: str) -> dict[str, typing.Any].  Schema: full_name*:string, ref*:string

Tool metadata:
- name: get_commit_combined_status
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (string; required)
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "ref": {
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "ref"
  ],
  "title": "Get Commit Combined Status",
  "type": "object"
}
```

### `get_file_contents`

- Write action: `false`
- Description:

```text
Fetch a single file from GitHub and decode base64 to UTF-8 text.  Schema: full_name*:string, path*:string, ref:string=main

Tool metadata:
- name: get_file_contents
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- path (string; required)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "path": {
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "path"
  ],
  "title": "Get File Contents",
  "type": "object"
}
```

### `get_file_excerpt`

- Write action: `false`
- Description:

```text
Get file excerpt. Signature: get_file_excerpt(full_name: str, path: str, ref: str = 'main', start_byte: int | None = None, max_bytes: int = 65536, tail_bytes: int | None = None, as_text: bool = True, max_text_chars: int = 200000, numbered_lines: bool = True) -> dict[str, typing.Any].  Schema: as_text:boolean=True, full_name*:string, max_bytes:integer=65536, max_text_chars:integer=200000, numbered_lines:boolean=True, path*:string, ref:string=main, start_byte:any, +1 more

Tool metadata:
- name: get_file_excerpt
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- as_text (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_bytes (integer; optional, default=65536)
- max_text_chars (integer; optional, default=200000)
- numbered_lines (boolean; optional, default=True)
- path (string; required)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- start_byte (unknown; optional)
- tail_bytes (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "as_text": {
      "default": true,
      "title": "As Text",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_bytes": {
      "default": 65536,
      "title": "Max Bytes",
      "type": "integer"
    },
    "max_text_chars": {
      "default": 200000,
      "title": "Max Text Chars",
      "type": "integer"
    },
    "numbered_lines": {
      "default": true,
      "title": "Numbered Lines",
      "type": "boolean"
    },
    "path": {
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "start_byte": {
      "default": null,
      "title": "Start Byte"
    },
    "tail_bytes": {
      "default": null,
      "title": "Tail Bytes"
    }
  },
  "required": [
    "full_name",
    "path"
  ],
  "title": "Get File Excerpt",
  "type": "object"
}
```

### `get_issue_comment_reactions`

- Write action: `false`
- Description:

```text
Get issue comment reactions. Signature: get_issue_comment_reactions(full_name: str, comment_id: int, per_page: int = 30, page: int = 1) -> dict[str, typing.Any].  Schema: comment_id*:integer, full_name*:string, page:integer=1, per_page:integer=30

Tool metadata:
- name: get_issue_comment_reactions
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- comment_id (integer; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "comment_id": {
      "title": "Comment Id",
      "type": "integer"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "comment_id"
  ],
  "title": "Get Issue Comment Reactions",
  "type": "object"
}
```

### `get_issue_overview`

- Write action: `false`
- Description:

```text
Return a high-level overview of an issue, including related branches, pull requests, and checklist items.  Schema: full_name*:string, issue_number*:integer

Tool metadata:
- name: get_issue_overview
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "issue_number": {
      "title": "Issue Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Get Issue Overview",
  "type": "object"
}
```

### `get_job_logs`

- Write action: `false`
- Description:

```text
Fetch raw logs for a GitHub Actions job without truncation.  Schema: full_name*:string, job_id*:integer

Tool metadata:
- name: get_job_logs
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- job_id (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "job_id": {
      "title": "Job Id",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "job_id"
  ],
  "title": "Get Job Logs",
  "type": "object"
}
```

### `get_latest_branch_status`

- Write action: `false`
- Description:

```text
Get latest branch status. Signature: get_latest_branch_status(full_name: str, branch: str, base: str = 'main') -> dict[str, typing.Any].  Schema: base:string=main, branch*:string, full_name*:string

Tool metadata:
- name: get_latest_branch_status
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- base (string; optional, default='main')
- branch (string; required)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base": {
      "default": "main",
      "title": "Base",
      "type": "string"
    },
    "branch": {
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Get Latest Branch Status",
  "type": "object"
}
```

### `get_pr_info`

- Write action: `false`
- Description:

```text
Get pull request info. Signature: get_pr_info(full_name: str, pull_number: int) -> dict[str, typing.Any].  Schema: full_name*:string, pull_number*:integer

Tool metadata:
- name: get_pr_info
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- pull_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "pull_number": {
      "title": "Pull Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Get Pr Info",
  "type": "object"
}
```

### `get_pr_overview`

- Write action: `false`
- Description:

```text
Return a compact overview of a pull request, including files and CI status.  Schema: full_name*:string, pull_number*:integer

Tool metadata:
- name: get_pr_overview
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- pull_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "pull_number": {
      "title": "Pull Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Get Pr Overview",
  "type": "object"
}
```

### `get_pr_reactions`

- Write action: `false`
- Description:

```text
Fetch reactions for a GitHub pull request.  Schema: full_name*:string, page:integer=1, per_page:integer=30, pull_number*:integer

Tool metadata:
- name: get_pr_reactions
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- pull_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "pull_number": {
      "title": "Pull Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Get Pr Reactions",
  "type": "object"
}
```

### `get_pr_review_comment_reactions`

- Write action: `false`
- Description:

```text
Fetch reactions for a pull request review comment.  Schema: comment_id*:integer, full_name*:string, page:integer=1, per_page:integer=30

Tool metadata:
- name: get_pr_review_comment_reactions
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- comment_id (integer; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "comment_id": {
      "title": "Comment Id",
      "type": "integer"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "comment_id"
  ],
  "title": "Get Pr Review Comment Reactions",
  "type": "object"
}
```

### `get_rate_limit`

- Write action: `false`
- Description:

```text
Get rate limit. Signature: get_rate_limit() -> dict[str, typing.Any].

Tool metadata:
- name: get_rate_limit
- visibility: public
- write_action: false
- write_allowed: true

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {},
  "title": "Get Rate Limit",
  "type": "object"
}
```

### `get_render_deploy`

- Write action: `false`
- Description:

```text
Fetch a specific deploy for a service.  Schema: deploy_id*:string, service_id*:string

Tool metadata:
- name: get_render_deploy
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "deploy_id": {
      "description": "Render deploy id (example: dpl-...).",
      "title": "Deploy Id",
      "type": "string"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Get Render Deploy",
  "type": "object"
}
```

### `get_render_logs`

- Write action: `false`
- Description:

```text
Fetch logs for a Render resource.  Schema: end_time:any, limit:integer=200, resource_id*:string, resource_type*:string, start_time:any

Tool metadata:
- name: get_render_logs
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- end_time (unknown; optional)
  Optional ISO8601 timestamp for the end of a log query window.
  Examples: '2026-01-14T13:34:56Z'
- limit (integer; optional, default=200)
  Maximum number of results to return.
  Examples: 20, 50, 200
- resource_id (string; required)
  Render log resource id corresponding to resource_type.
- resource_type (string; required)
  Render log resource type (service or job).
  Examples: 'service', 'job'
- start_time (unknown; optional)
  Optional ISO8601 timestamp for the start of a log query window.
  Examples: '2026-01-14T12:34:56Z'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "end_time": {
      "default": null,
      "description": "Optional ISO8601 timestamp for the end of a log query window.",
      "examples": [
        "2026-01-14T13:34:56Z"
      ],
      "title": "End Time"
    },
    "limit": {
      "default": 200,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    },
    "resource_id": {
      "description": "Render log resource id corresponding to resource_type.",
      "title": "Resource Id",
      "type": "string"
    },
    "resource_type": {
      "description": "Render log resource type (service or job).",
      "examples": [
        "service",
        "job"
      ],
      "title": "Resource Type",
      "type": "string"
    },
    "start_time": {
      "default": null,
      "description": "Optional ISO8601 timestamp for the start of a log query window.",
      "examples": [
        "2026-01-14T12:34:56Z"
      ],
      "title": "Start Time"
    }
  },
  "required": [
    "resource_type",
    "resource_id"
  ],
  "title": "Get Render Logs",
  "type": "object"
}
```

### `get_render_service`

- Write action: `false`
- Description:

```text
Fetch a Render service by id.  Schema: service_id*:string

Tool metadata:
- name: get_render_service
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "Get Render Service",
  "type": "object"
}
```

### `get_repo_dashboard`

- Write action: `false`
- Description:

```text
Return a compact, multi-signal dashboard for a repository.  Schema: branch:any, full_name*:string

This helper aggregates several lower-level tools into a single call so
callers can quickly understand the current state of a repo. It is
intentionally read-only.

Args:
full_name:
"owner/repo" string.
branch:
Optional branch name. When omitted, the repository's default
branch is used via the same normalization logic as other tools.

Returns:
A dict with high-level fields such as:

- repo: core metadata about the repository (description, visibility,
default branch, topics, open issue count when available).
- branch: the effective branch used for lookups.
- pull_requests: a small window of open pull requests (up to 10).
- issues: a small window of open issues (up to 10, excluding PRs).
- workflows: recent GitHub Actions workflow runs on the branch
(up to 5).
- top_level_tree: compact listing of top-level files/directories
on the branch to show the project layout.

Individual sections degrade gracefully: if one underlying call fails,
its corresponding "*_error" field is populated instead of raising.

Tool metadata:
- name: get_repo_dashboard
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- branch (unknown; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": null,
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Get Repo Dashboard",
  "type": "object"
}
```

### `get_repo_dashboard_graphql`

- Write action: `false`
- Description:

```text
Return a compact dashboard using GraphQL as a fallback.  Schema: branch:any, full_name*:string

Tool metadata:
- name: get_repo_dashboard_graphql
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- branch (unknown; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": null,
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Get Repo Dashboard Graphql",
  "type": "object"
}
```

### `get_repo_defaults`

- Write action: `false`
- Description:

```text
Get repository defaults. Signature: get_repo_defaults(full_name: str | None = None) -> dict[str, typing.Any].  Schema: full_name:any

Tool metadata:
- name: get_repo_defaults
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    }
  },
  "title": "Get Repo Defaults",
  "type": "object"
}
```

### `get_repository`

- Write action: `false`
- Description:

```text
Look up repository metadata (topics, default branch, permissions).  Schema: full_name*:string

Tool metadata:
- name: get_repository
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Get Repository",
  "type": "object"
}
```

### `get_server_config`

- Write action: `false`
- Description:

```text
Get server config. Signature: get_server_config() -> dict[str, typing.Any].

Tool metadata:
- name: get_server_config
- visibility: public
- write_action: false
- write_allowed: true

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {},
  "title": "Get Server Config",
  "type": "object"
}
```

### `get_user_login`

- Write action: `false`
- Description:

```text
Get user login. Signature: get_user_login() -> dict[str, typing.Any].

Tool metadata:
- name: get_user_login
- visibility: public
- write_action: false
- write_allowed: true

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {},
  "title": "Get User Login",
  "type": "object"
}
```

### `get_workflow_run`

- Write action: `false`
- Description:

```text
Retrieve a specific workflow run including timing and conclusion.  Schema: full_name*:string, run_id*:integer

Tool metadata:
- name: get_workflow_run
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- run_id (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "run_id": {
      "title": "Run Id",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "run_id"
  ],
  "title": "Get Workflow Run",
  "type": "object"
}
```

### `get_workflow_run_overview`

- Write action: `false`
- Description:

```text
Summarize a GitHub Actions workflow run for CI triage.  Schema: full_name*:string, max_jobs:integer=500, run_id*:integer

This helper is read-only and safe to call before any write actions. It
aggregates run metadata, jobs (with optional pagination up to max_jobs),
failed jobs, and the longest jobs by duration to provide a single-call
summary of run status.

Tool metadata:
- name: get_workflow_run_overview
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_jobs (integer; optional, default=500)
- run_id (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_jobs": {
      "default": 500,
      "title": "Max Jobs",
      "type": "integer"
    },
    "run_id": {
      "title": "Run Id",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "run_id"
  ],
  "title": "Get Workflow Run Overview",
  "type": "object"
}
```

### `get_workspace_changes_summary`

- Write action: `false`
- Description:

```text
Summarize modified, added, deleted, renamed, and untracked files in the repo mirror.  Schema: full_name*:string, max_files:integer=200, path_prefix:any, ref:string=main

Tool metadata:
- name: get_workspace_changes_summary
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_files (integer; optional, default=200)
- path_prefix (unknown; optional)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_files": {
      "default": 200,
      "title": "Max Files",
      "type": "integer"
    },
    "path_prefix": {
      "default": null,
      "title": "Path Prefix"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Get Workspace Changes Summary",
  "type": "object"
}
```

### `get_workspace_file_contents`

- Write action: `false`
- Description:

```text
Read a file from the persistent repo mirror (no shell).  Schema: full_name*:string, max_bytes:integer=2000000, max_chars:integer=300000, path:string=, ref:string=main

Args:
  path: Repo-relative path (POSIX-style). Must resolve inside the repo mirror.

Returns:
  A dict with keys like: exists, path, text, encoding, size_bytes.

Tool metadata:
- name: get_workspace_file_contents
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_bytes (integer; optional, default=2000000)
- max_chars (integer; optional, default=300000)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_bytes": {
      "default": 2000000,
      "title": "Max Bytes",
      "type": "integer"
    },
    "max_chars": {
      "default": 300000,
      "title": "Max Chars",
      "type": "integer"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Get Workspace File Contents",
  "type": "object"
}
```

### `get_workspace_files_contents`

- Write action: `false`
- Description:

```text
Read multiple files from the persistent repo mirror in one call.  Schema: expand_globs:boolean=True, full_name*:string, include_missing:boolean=True, max_chars_per_file:integer=20000, max_total_chars:integer=120000, paths:any, ref:string=main

This tool is optimized for examination workflows where a client wants to
inspect several files (optionally via glob patterns) without issuing many
per-file calls.

Notes:
  - All paths are repository-relative.
  - When expand_globs is true, glob patterns (e.g. "src/**/*.py") are
    expanded relative to the repo root.
  - max_chars_per_file and max_total_chars are accepted for compatibility
    but are not enforced as truncation limits.

Tool metadata:
- name: get_workspace_files_contents
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- expand_globs (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_missing (boolean; optional, default=True)
- max_chars_per_file (integer; optional, default=20000)
- max_total_chars (integer; optional, default=120000)
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "expand_globs": {
      "default": true,
      "title": "Expand Globs",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "include_missing": {
      "default": true,
      "title": "Include Missing",
      "type": "boolean"
    },
    "max_chars_per_file": {
      "default": 20000,
      "title": "Max Chars Per File",
      "type": "integer"
    },
    "max_total_chars": {
      "default": 120000,
      "title": "Max Total Chars",
      "type": "integer"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Get Workspace Files Contents",
  "type": "object"
}
```

### `graphql_query`

- Write action: `false`
- Description:

```text
Graphql Query. Signature: graphql_query(query: str, variables: dict[str, typing.Any] | None = None) -> dict[str, typing.Any].  Schema: query*:string, variables:any

Tool metadata:
- name: graphql_query
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- query (string; required)
  Search query string.
  Examples: 'def main', 'import os', 'async def'
- variables (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "query": {
      "description": "Search query string.",
      "examples": [
        "def main",
        "import os",
        "async def"
      ],
      "title": "Query",
      "type": "string"
    },
    "variables": {
      "default": null,
      "title": "Variables"
    }
  },
  "required": [
    "query"
  ],
  "title": "Graphql Query",
  "type": "object"
}
```

### `list_all_actions`

- Write action: `false`
- Description:

```text
Enumerate every available MCP tool with optional schemas.

    Canonical “schema registry” used by clients.
    - Inherent tool classification is always reported as write_action (True/False).
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "compact": {
      "default": null,
      "title": "Compact"
    },
    "include_parameters": {
      "default": false,
      "title": "Include Parameters"
    }
  },
  "title": "List All Actions",
  "type": "object"
}
```

### `list_branches`

- Write action: `false`
- Description:

```text
Enumerate branches for a repository with GitHub-style pagination.  Schema: full_name*:string, page:integer=1, per_page:integer=100

Tool metadata:
- name: list_branches
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=100)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 100,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "List Branches",
  "type": "object"
}
```

### `list_open_issues_graphql`

- Write action: `false`
- Description:

```text
List issues (excluding PRs) using GraphQL, with cursor-based pagination.  Schema: cursor:any, full_name*:string, per_page:integer=30, state:string=open

Tool metadata:
- name: list_open_issues_graphql
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (unknown; optional)
  Pagination cursor returned by the previous call.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- state (string; optional, default='open')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": null,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "state": {
      "default": "open",
      "title": "State",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "List Open Issues Graphql",
  "type": "object"
}
```

### `list_pr_changed_filenames`

- Write action: `false`
- Description:

```text
List pull request changed filenames. Signature: list_pr_changed_filenames(full_name: str, pull_number: int, per_page: int = 100, page: int = 1) -> dict[str, typing.Any].  Schema: full_name*:string, page:integer=1, per_page:integer=100, pull_number*:integer

Tool metadata:
- name: list_pr_changed_filenames
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=100)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- pull_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 100,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "pull_number": {
      "title": "Pull Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "List Pr Changed Filenames",
  "type": "object"
}
```

### `list_pull_requests`

- Write action: `false`
- Description:

```text
List pull requests. Signature: list_pull_requests(full_name: str, state: Literal['open', 'closed', 'all'] = 'open', head: str | None = None, base: str | None = None, per_page: int = 30, page: int = 1) -> dict[str, typing.Any].  Schema: base:any, full_name*:string, head:any, page:integer=1, per_page:integer=30, state:string=open

Tool metadata:
- name: list_pull_requests
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- base (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- head (unknown; optional)
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- state (string; optional, default='open')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base": {
      "default": null,
      "title": "Base"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "head": {
      "default": null,
      "title": "Head"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "state": {
      "default": "open",
      "title": "State",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "List Pull Requests",
  "type": "object"
}
```

### `list_recent_failures`

- Write action: `false`
- Description:

```text
List recent failed or cancelled GitHub Actions workflow runs.  Schema: branch:any, full_name*:string, limit:integer=10

This helper composes ``list_workflow_runs`` and filters to runs whose
conclusion indicates a non-successful outcome (for example failure,
cancelled, or timed out). It is intended as a navigation helper for CI
debugging flows.

Tool metadata:
- name: list_recent_failures
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- branch (unknown; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- limit (integer; optional, default=10)
  Maximum number of results to return.
  Examples: 20, 50, 200

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": null,
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "limit": {
      "default": 10,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "List Recent Failures",
  "type": "object"
}
```

### `list_recent_failures_graphql`

- Write action: `false`
- Description:

```text
List recent workflow failures using GraphQL as a fallback.  Schema: branch:any, full_name*:string, limit:integer=10

Tool metadata:
- name: list_recent_failures_graphql
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- branch (unknown; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- limit (integer; optional, default=10)
  Maximum number of results to return.
  Examples: 20, 50, 200

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": null,
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "limit": {
      "default": 10,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "List Recent Failures Graphql",
  "type": "object"
}
```

### `list_recent_issues`

- Write action: `false`
- Description:

```text
List recent issues. Signature: list_recent_issues(filter: str = 'assigned', state: str = 'open', per_page: int = 30, page: int = 1) -> dict[str, typing.Any].  Schema: filter:string=assigned, page:integer=1, per_page:integer=30, state:string=open

Tool metadata:
- name: list_recent_issues
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- filter (string; optional, default='assigned')
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- state (string; optional, default='open')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "filter": {
      "default": "assigned",
      "title": "Filter",
      "type": "string"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "state": {
      "default": "open",
      "title": "State",
      "type": "string"
    }
  },
  "title": "List Recent Issues",
  "type": "object"
}
```

### `list_render_deploys`

- Write action: `false`
- Description:

```text
List deploys for a Render service.  Schema: cursor:any, limit:integer=20, service_id*:string

Tool metadata:
- name: list_render_deploys
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (unknown; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": null,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor"
    },
    "limit": {
      "default": 20,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "List Render Deploys",
  "type": "object"
}
```

### `list_render_logs`

- Write action: `false`
- Description:

```text
List logs for one or more Render resources.  Schema: direction:string=backward, end_time:any, host:any, instance:any, level:any, limit:integer=200, log_type:any, method:any, +6 more

This maps to Render's public /v1/logs API which requires an owner_id and one
or more resource ids.

Tool metadata:
- name: list_render_logs
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- direction (string; optional, default='backward')
- end_time (unknown; optional)
  Optional ISO8601 timestamp for the end of a log query window.
  Examples: '2026-01-14T13:34:56Z'
- host (unknown; optional)
- instance (unknown; optional)
- level (unknown; optional)
- limit (integer; optional, default=200)
  Maximum number of results to return.
  Examples: 20, 50, 200
- log_type (unknown; optional)
- method (unknown; optional)
- owner_id (string; required)
  Render owner id (workspace or personal owner). list_render_owners returns discoverable values.
- path (unknown; optional)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- resources (array; required)
- start_time (unknown; optional)
  Optional ISO8601 timestamp for the start of a log query window.
  Examples: '2026-01-14T12:34:56Z'
- status_code (unknown; optional)
- text (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "direction": {
      "default": "backward",
      "title": "Direction",
      "type": "string"
    },
    "end_time": {
      "default": null,
      "description": "Optional ISO8601 timestamp for the end of a log query window.",
      "examples": [
        "2026-01-14T13:34:56Z"
      ],
      "title": "End Time"
    },
    "host": {
      "default": null,
      "title": "Host"
    },
    "instance": {
      "default": null,
      "title": "Instance"
    },
    "level": {
      "default": null,
      "title": "Level"
    },
    "limit": {
      "default": 200,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    },
    "log_type": {
      "default": null,
      "title": "Log Type"
    },
    "method": {
      "default": null,
      "title": "Method"
    },
    "owner_id": {
      "description": "Render owner id (workspace or personal owner). list_render_owners returns discoverable values.",
      "title": "Owner Id",
      "type": "string"
    },
    "path": {
      "default": null,
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    },
    "resources": {
      "items": {},
      "title": "Resources",
      "type": "array"
    },
    "start_time": {
      "default": null,
      "description": "Optional ISO8601 timestamp for the start of a log query window.",
      "examples": [
        "2026-01-14T12:34:56Z"
      ],
      "title": "Start Time"
    },
    "status_code": {
      "default": null,
      "title": "Status Code"
    },
    "text": {
      "default": null,
      "title": "Text"
    }
  },
  "required": [
    "owner_id",
    "resources"
  ],
  "title": "List Render Logs",
  "type": "object"
}
```

### `list_render_owners`

- Write action: `false`
- Description:

```text
List Render owners (workspaces + personal owners).  Schema: cursor:any, limit:integer=20

Tool metadata:
- name: list_render_owners
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (unknown; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": null,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor"
    },
    "limit": {
      "default": 20,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    }
  },
  "title": "List Render Owners",
  "type": "object"
}
```

### `list_render_service_env_vars`

- Write action: `false`
- Description:

```text
List environment variables configured for a Render service.  Schema: service_id*:string

Tool metadata:
- name: list_render_service_env_vars
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "List Render Service Env Vars",
  "type": "object"
}
```

### `list_render_services`

- Write action: `false`
- Description:

```text
List Render services (optionally filtered by owner_id).  Schema: cursor:any, limit:integer=20, owner_id:any

Tool metadata:
- name: list_render_services
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (unknown; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200
- owner_id (unknown; optional)
  Render owner id (workspace or personal owner). list_render_owners returns discoverable values.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": null,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor"
    },
    "limit": {
      "default": 20,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    },
    "owner_id": {
      "default": null,
      "description": "Render owner id (workspace or personal owner). list_render_owners returns discoverable values.",
      "title": "Owner Id"
    }
  },
  "title": "List Render Services",
  "type": "object"
}
```

### `list_repositories`

- Write action: `false`
- Description:

```text
List repositories. Signature: list_repositories(affiliation: str | None = None, visibility: str | None = None, per_page: int = 30, page: int = 1) -> dict[str, typing.Any].  Schema: affiliation:any, page:integer=1, per_page:integer=30, visibility:any

Tool metadata:
- name: list_repositories
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- affiliation (unknown; optional)
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- visibility (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "affiliation": {
      "default": null,
      "title": "Affiliation"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "visibility": {
      "default": null,
      "title": "Visibility"
    }
  },
  "title": "List Repositories",
  "type": "object"
}
```

### `list_repositories_by_installation`

- Write action: `false`
- Description:

```text
List repositories by installation. Signature: list_repositories_by_installation(installation_id: int, per_page: int = 30, page: int = 1) -> dict[str, typing.Any].  Schema: installation_id*:integer, page:integer=1, per_page:integer=30

Tool metadata:
- name: list_repositories_by_installation
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- installation_id (integer; required)
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "installation_id": {
      "title": "Installation Id",
      "type": "integer"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    }
  },
  "required": [
    "installation_id"
  ],
  "title": "List Repositories By Installation",
  "type": "object"
}
```

### `list_repository_issues`

- Write action: `false`
- Description:

```text
List repository issues. Signature: list_repository_issues(full_name: str, state: str = 'open', labels: list[str] | None = None, assignee: str | None = None, per_page: int = 30, page: int = 1) -> dict[str, typing.Any].  Schema: assignee:any, full_name*:string, labels:any, page:integer=1, per_page:integer=30, state:string=open

Tool metadata:
- name: list_repository_issues
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- assignee (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- labels (unknown; optional)
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- state (string; optional, default='open')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "assignee": {
      "default": null,
      "title": "Assignee"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "labels": {
      "default": null,
      "title": "Labels"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "state": {
      "default": "open",
      "title": "State",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "List Repository Issues",
  "type": "object"
}
```

### `list_repository_tree`

- Write action: `false`
- Description:

```text
List repository tree. Signature: list_repository_tree(full_name: str, ref: str = 'main', path_prefix: str | None = None, recursive: bool = True, max_entries: int = 1000, include_blobs: bool = True, include_trees: bool = True) -> dict[str, typing.Any].  Schema: full_name*:string, include_blobs:boolean=True, include_trees:boolean=True, max_entries:integer=1000, path_prefix:any, recursive:boolean=True, ref:string=main

Tool metadata:
- name: list_repository_tree
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_blobs (boolean; optional, default=True)
- include_trees (boolean; optional, default=True)
- max_entries (integer; optional, default=1000)
- path_prefix (unknown; optional)
- recursive (boolean; optional, default=True)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "include_blobs": {
      "default": true,
      "title": "Include Blobs",
      "type": "boolean"
    },
    "include_trees": {
      "default": true,
      "title": "Include Trees",
      "type": "boolean"
    },
    "max_entries": {
      "default": 1000,
      "title": "Max Entries",
      "type": "integer"
    },
    "path_prefix": {
      "default": null,
      "title": "Path Prefix"
    },
    "recursive": {
      "default": true,
      "title": "Recursive",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "List Repository Tree",
  "type": "object"
}
```

### `list_resources`

- Write action: `false`
- Description:

```text
Return a resource catalog derived from registered tools.

    This is intentionally lightweight and supports pagination.

    Args:
        base_path: Optional prefix prepended to each resource URI.
        include_parameters: When True, include the tool input schema for each
            returned resource. This can be expensive for very large catalogs;
            consider paginating via cursor/limit.
        compact: When True, shorten descriptions.
        cursor: Integer offset into the sorted resource list.
        limit: Maximum number of resources to return (bounded).
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base_path": {
      "default": null,
      "title": "Base Path"
    },
    "compact": {
      "default": null,
      "title": "Compact"
    },
    "cursor": {
      "default": 0,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor"
    },
    "include_parameters": {
      "default": false,
      "title": "Include Parameters"
    },
    "limit": {
      "default": 200,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit"
    }
  },
  "title": "List Resources",
  "type": "object"
}
```

### `list_tools`

- Write action: `false`
- Description:

```text
Lightweight tool catalog.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "name_prefix": {
      "default": null,
      "title": "Name Prefix"
    },
    "only_read": {
      "default": false,
      "title": "Only Read"
    },
    "only_write": {
      "default": false,
      "title": "Only Write"
    }
  },
  "title": "List Tools",
  "type": "object"
}
```

### `list_workflow_run_jobs`

- Write action: `false`
- Description:

```text
List jobs within a workflow run, useful for troubleshooting failures.  Schema: full_name*:string, page:integer=1, per_page:integer=30, run_id*:integer

Tool metadata:
- name: list_workflow_run_jobs
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- run_id (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "run_id": {
      "title": "Run Id",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "run_id"
  ],
  "title": "List Workflow Run Jobs",
  "type": "object"
}
```

### `list_workflow_runs`

- Write action: `false`
- Description:

```text
List recent GitHub Actions workflow runs with optional filters.  Schema: branch:any, event:any, full_name*:string, page:integer=1, per_page:integer=30, status:any

Tool metadata:
- name: list_workflow_runs
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- branch (unknown; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- event (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- status (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": null,
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch"
    },
    "event": {
      "default": null,
      "title": "Event"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "status": {
      "default": null,
      "title": "Status"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "List Workflow Runs",
  "type": "object"
}
```

### `list_workflow_runs_graphql`

- Write action: `false`
- Description:

```text
List recent workflow runs using GraphQL with cursor-based pagination.  Schema: branch:any, cursor:any, full_name*:string, per_page:integer=30

Tool metadata:
- name: list_workflow_runs_graphql
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- branch (unknown; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- cursor (unknown; optional)
  Pagination cursor returned by the previous call.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": null,
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch"
    },
    "cursor": {
      "default": null,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "List Workflow Runs Graphql",
  "type": "object"
}
```

### `list_workspace_files`

- Write action: `false`
- Description:

```text
List files in the repo mirror.  Schema: cursor:integer=0, full_name:any, include_dirs:boolean=False, include_hidden:boolean=True, max_depth:any, max_files:any, max_results:any, path:string=, +1 more

This endpoint is designed to work for very large repos:
- Enforces `max_files` and `max_depth` (unlike earlier versions).
- Supports simple pagination via `cursor` (an integer offset).

Tool metadata:
- name: list_workspace_files
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (integer; optional, default=0)
  Pagination cursor returned by the previous call.
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_dirs (boolean; optional, default=False)
- include_hidden (boolean; optional, default=True)
- max_depth (unknown; optional)
- max_files (unknown; optional)
- max_results (unknown; optional)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": 0,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor",
      "type": "integer"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "include_dirs": {
      "default": false,
      "title": "Include Dirs",
      "type": "boolean"
    },
    "include_hidden": {
      "default": true,
      "title": "Include Hidden",
      "type": "boolean"
    },
    "max_depth": {
      "default": null,
      "title": "Max Depth"
    },
    "max_files": {
      "default": null,
      "title": "Max Files"
    },
    "max_results": {
      "default": null,
      "title": "Max Results"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "title": "List Workspace Files",
  "type": "object"
}
```

### `list_write_actions`

- Write action: `false`
- Description:

```text
Enumerate write-capable MCP tools with optional schemas.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "compact": {
      "default": null,
      "title": "Compact"
    },
    "include_parameters": {
      "default": false,
      "title": "Include Parameters"
    }
  },
  "title": "List Write Actions",
  "type": "object"
}
```

### `list_write_tools`

- Write action: `false`
- Description:

```text
Describe write-capable tools exposed by this server.

    This is a lightweight summary that avoids scanning the full module.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {},
  "title": "List Write Tools",
  "type": "object"
}
```

### `make_diff`

- Write action: `false`
- Description:

```text
Backward-compatible alias for :func:`make_workspace_diff`.  Schema: after:any, before:any, context_lines:integer=3, fromfile:any, full_name*:string, max_chars_per_side:integer=200000, max_diff_chars:integer=200000, path:any, +3 more

Tool metadata:
- name: make_diff
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- after (unknown; optional)
- before (unknown; optional)
- context_lines (integer; optional, default=3)
- fromfile (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_chars_per_side (integer; optional, default=200000)
- max_diff_chars (integer; optional, default=200000)
- path (unknown; optional)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- tofile (unknown; optional)
- updated_content (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "after": {
      "default": null,
      "title": "After"
    },
    "before": {
      "default": null,
      "title": "Before"
    },
    "context_lines": {
      "default": 3,
      "title": "Context Lines",
      "type": "integer"
    },
    "fromfile": {
      "default": null,
      "title": "Fromfile"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_chars_per_side": {
      "default": 200000,
      "title": "Max Chars Per Side",
      "type": "integer"
    },
    "max_diff_chars": {
      "default": 200000,
      "title": "Max Diff Chars",
      "type": "integer"
    },
    "path": {
      "default": null,
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "tofile": {
      "default": null,
      "title": "Tofile"
    },
    "updated_content": {
      "default": null,
      "title": "Updated Content"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Make Diff",
  "type": "object"
}
```

### `make_patch`

- Write action: `false`
- Description:

```text
Backward-compatible alias for :func:`make_workspace_patch`.  Schema: after:any, before:any, context_lines:integer=3, fromfile:any, full_name*:string, max_chars_per_side:integer=200000, max_diff_chars:integer=200000, path:any, +3 more

Tool metadata:
- name: make_patch
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- after (unknown; optional)
- before (unknown; optional)
- context_lines (integer; optional, default=3)
- fromfile (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_chars_per_side (integer; optional, default=200000)
- max_diff_chars (integer; optional, default=200000)
- path (unknown; optional)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- tofile (unknown; optional)
- updated_content (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "after": {
      "default": null,
      "title": "After"
    },
    "before": {
      "default": null,
      "title": "Before"
    },
    "context_lines": {
      "default": 3,
      "title": "Context Lines",
      "type": "integer"
    },
    "fromfile": {
      "default": null,
      "title": "Fromfile"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_chars_per_side": {
      "default": 200000,
      "title": "Max Chars Per Side",
      "type": "integer"
    },
    "max_diff_chars": {
      "default": 200000,
      "title": "Max Diff Chars",
      "type": "integer"
    },
    "path": {
      "default": null,
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "tofile": {
      "default": null,
      "title": "Tofile"
    },
    "updated_content": {
      "default": null,
      "title": "Updated Content"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Make Patch",
  "type": "object"
}
```

### `make_workspace_diff`

- Write action: `false`
- Description:

```text
Build a unified diff from workspace content or provided text.  Schema: after:any, before:any, context_lines:integer=3, fromfile:any, full_name*:string, max_chars_per_side:integer=200000, max_diff_chars:integer=200000, path:any, +3 more

Tool metadata:
- name: make_workspace_diff
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- after (unknown; optional)
- before (unknown; optional)
- context_lines (integer; optional, default=3)
- fromfile (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_chars_per_side (integer; optional, default=200000)
- max_diff_chars (integer; optional, default=200000)
- path (unknown; optional)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- tofile (unknown; optional)
- updated_content (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "after": {
      "default": null,
      "title": "After"
    },
    "before": {
      "default": null,
      "title": "Before"
    },
    "context_lines": {
      "default": 3,
      "title": "Context Lines",
      "type": "integer"
    },
    "fromfile": {
      "default": null,
      "title": "Fromfile"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_chars_per_side": {
      "default": 200000,
      "title": "Max Chars Per Side",
      "type": "integer"
    },
    "max_diff_chars": {
      "default": 200000,
      "title": "Max Diff Chars",
      "type": "integer"
    },
    "path": {
      "default": null,
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "tofile": {
      "default": null,
      "title": "Tofile"
    },
    "updated_content": {
      "default": null,
      "title": "Updated Content"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Make Workspace Diff",
  "type": "object"
}
```

### `make_workspace_patch`

- Write action: `false`
- Description:

```text
Build a unified diff patch from workspace content or provided text.  Schema: after:any, before:any, context_lines:integer=3, fromfile:any, full_name*:string, max_chars_per_side:integer=200000, max_diff_chars:integer=200000, path:any, +3 more

Tool metadata:
- name: make_workspace_patch
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- after (unknown; optional)
- before (unknown; optional)
- context_lines (integer; optional, default=3)
- fromfile (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_chars_per_side (integer; optional, default=200000)
- max_diff_chars (integer; optional, default=200000)
- path (unknown; optional)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- tofile (unknown; optional)
- updated_content (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "after": {
      "default": null,
      "title": "After"
    },
    "before": {
      "default": null,
      "title": "Before"
    },
    "context_lines": {
      "default": 3,
      "title": "Context Lines",
      "type": "integer"
    },
    "fromfile": {
      "default": null,
      "title": "Fromfile"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_chars_per_side": {
      "default": 200000,
      "title": "Max Chars Per Side",
      "type": "integer"
    },
    "max_diff_chars": {
      "default": 200000,
      "title": "Max Diff Chars",
      "type": "integer"
    },
    "path": {
      "default": null,
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "tofile": {
      "default": null,
      "title": "Tofile"
    },
    "updated_content": {
      "default": null,
      "title": "Updated Content"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Make Workspace Patch",
  "type": "object"
}
```

### `merge_pull_request`

- Write action: `true`
- Description:

```text
Merge pull request. Signature: merge_pull_request(full_name: str, number: int, merge_method: Literal['merge', 'squash', 'rebase'] = 'squash', commit_title: str | None = None, commit_message: str | None = None) -> dict[str, typing.Any].  Schema: commit_message:any, commit_title:any, full_name*:string, merge_method:string=squash, number*:integer

Tool metadata:
- name: merge_pull_request
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- commit_message (unknown; optional)
- commit_title (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- merge_method (string; optional, default='squash')
- number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "commit_message": {
      "default": null,
      "title": "Commit Message"
    },
    "commit_title": {
      "default": null,
      "title": "Commit Title"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "merge_method": {
      "default": "squash",
      "title": "Merge Method",
      "type": "string"
    },
    "number": {
      "title": "Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "number"
  ],
  "title": "Merge Pull Request",
  "type": "object"
}
```

### `move_file`

- Write action: `true`
- Description:

```text
Move file. Signature: move_file(full_name: str, from_path: str, to_path: str, branch: str = 'main', message: str | None = None) -> dict[str, typing.Any].  Schema: branch:string=main, from_path*:string, full_name*:string, message:any, to_path*:string

Tool metadata:
- name: move_file
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- branch (string; optional, default='main')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- from_path (string; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (unknown; optional)
  Commit message.
  Examples: 'Refactor tool schemas'
- to_path (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": "main",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "from_path": {
      "title": "From Path",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "message": {
      "default": null,
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message"
    },
    "to_path": {
      "title": "To Path",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "from_path",
    "to_path"
  ],
  "title": "Move File",
  "type": "object"
}
```

### `move_workspace_paths`

- Write action: `true`
- Description:

```text
Move (rename) one or more workspace paths inside the repo mirror.  Schema: create_parents:boolean=True, full_name*:string, moves:any, overwrite:boolean=False, ref:string=main

Args:
  moves: list of {"src": "path", "dst": "path"}
  overwrite: if true, allow replacing an existing destination.

Tool metadata:
- name: move_workspace_paths
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- create_parents (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- moves (unknown; optional)
- overwrite (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "moves": {
      "default": null,
      "title": "Moves"
    },
    "overwrite": {
      "default": false,
      "title": "Overwrite",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Move Workspace Paths",
  "type": "object"
}
```

### `open_issue_context`

- Write action: `false`
- Description:

```text
Return an issue plus related branches and pull requests.  Schema: full_name*:string, issue_number*:integer

Tool metadata:
- name: open_issue_context
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "issue_number": {
      "title": "Issue Number",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Open Issue Context",
  "type": "object"
}
```

### `open_pr_for_existing_branch`

- Write action: `true`
- Description:

```text
Open a pull request for an existing branch into a base branch.  Schema: base:string=main, body:any, branch*:string, draft:boolean=False, full_name*:string, title:any

This helper is intentionally idempotent: if there is already an open PR for
the same head/base pair, it will return that existing PR instead of failing
or creating a duplicate.

Tool metadata:
- name: open_pr_for_existing_branch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- base (string; optional, default='main')
- body (unknown; optional)
- branch (string; required)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- draft (boolean; optional, default=False)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- title (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base": {
      "default": "main",
      "title": "Base",
      "type": "string"
    },
    "body": {
      "default": null,
      "title": "Body"
    },
    "branch": {
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "draft": {
      "default": false,
      "title": "Draft",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "title": {
      "default": null,
      "title": "Title"
    }
  },
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Open Pr For Existing Branch",
  "type": "object"
}
```

### `patch_render_service`

- Write action: `true`
- Description:

```text
Patch a Render service.  Schema: patch*:object, service_id*:string

Tool metadata:
- name: patch_render_service
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- patch (object; required)
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "patch": {
      "additionalProperties": true,
      "title": "Patch",
      "type": "object"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "patch"
  ],
  "title": "Patch Render Service",
  "type": "object"
}
```

### `ping_extensions`

- Write action: `false`
- Description:

```text
Ping the MCP server extensions surface.

Tool metadata:
- name: ping_extensions
- visibility: public
- write_action: false
- write_allowed: true
- tags: diagnostics, meta

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {},
  "title": "Ping Extensions",
  "type": "object"
}
```

### `pr_smoke_test`

- Write action: `true`
- Description:

```text
Pr Smoke Test. Signature: pr_smoke_test(full_name: str | None = None, base_branch: str | None = None, draft: bool = True) -> dict[str, typing.Any].  Schema: base_branch:any, draft:boolean=True, full_name:any

Tool metadata:
- name: pr_smoke_test
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- base_branch (unknown; optional)
- draft (boolean; optional, default=True)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base_branch": {
      "default": null,
      "title": "Base Branch"
    },
    "draft": {
      "default": true,
      "title": "Draft",
      "type": "boolean"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    }
  },
  "title": "Pr Smoke Test",
  "type": "object"
}
```

### `read_git_file_excerpt`

- Write action: `false`
- Description:

```text
Read an excerpt of a file as it exists at a git ref, with line numbers.  Schema: full_name*:string, git_ref:string=HEAD, max_chars:integer=80000, max_lines:integer=200, path:string=, ref:string=main, start_line:integer=1

Uses the local workspace mirror and `git show` so callers can inspect
historical versions without changing the checkout.

Line numbers are 1-indexed and correspond to the file at `git_ref`.

Tool metadata:
- name: read_git_file_excerpt
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- git_ref (string; optional, default='HEAD')
- max_chars (integer; optional, default=80000)
- max_lines (integer; optional, default=200)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- start_line (integer; optional, default=1)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "git_ref": {
      "default": "HEAD",
      "title": "Git Ref",
      "type": "string"
    },
    "max_chars": {
      "default": 80000,
      "title": "Max Chars",
      "type": "integer"
    },
    "max_lines": {
      "default": 200,
      "title": "Max Lines",
      "type": "integer"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "start_line": {
      "default": 1,
      "title": "Start Line",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Read Git File Excerpt",
  "type": "object"
}
```

### `read_git_file_sections`

- Write action: `false`
- Description:

```text
Read a file at a git ref as multiple parts with real line numbers.  Schema: full_name*:string, git_ref:string=HEAD, max_chars_per_section:integer=80000, max_lines_per_section:integer=200, max_sections:integer=5, overlap_lines:integer=20, path:string=, ref:string=main, +1 more

This is the multi-part companion to `read_git_file_excerpt`.
It uses `git show <git_ref>:<path>` streamed from the local workspace
mirror, so line numbers correspond to the file at `git_ref`.

Tool metadata:
- name: read_git_file_sections
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- git_ref (string; optional, default='HEAD')
- max_chars_per_section (integer; optional, default=80000)
- max_lines_per_section (integer; optional, default=200)
- max_sections (integer; optional, default=5)
- overlap_lines (integer; optional, default=20)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- start_line (integer; optional, default=1)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "git_ref": {
      "default": "HEAD",
      "title": "Git Ref",
      "type": "string"
    },
    "max_chars_per_section": {
      "default": 80000,
      "title": "Max Chars Per Section",
      "type": "integer"
    },
    "max_lines_per_section": {
      "default": 200,
      "title": "Max Lines Per Section",
      "type": "integer"
    },
    "max_sections": {
      "default": 5,
      "title": "Max Sections",
      "type": "integer"
    },
    "overlap_lines": {
      "default": 20,
      "title": "Overlap Lines",
      "type": "integer"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "start_line": {
      "default": 1,
      "title": "Start Line",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Read Git File Sections",
  "type": "object"
}
```

### `read_workspace_file_excerpt`

- Write action: `false`
- Description:

```text
Read an excerpt of a file with line numbers (safe for very large files).  Schema: full_name*:string, max_chars:integer=80000, max_lines:integer=200, path:string=, ref:string=main, start_line:integer=1

Unlike get_workspace_file_contents, this reads only the requested line range
and returns a structured list of {line, text} entries.

Tool metadata:
- name: read_workspace_file_excerpt
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_chars (integer; optional, default=80000)
- max_lines (integer; optional, default=200)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- start_line (integer; optional, default=1)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_chars": {
      "default": 80000,
      "title": "Max Chars",
      "type": "integer"
    },
    "max_lines": {
      "default": 200,
      "title": "Max Lines",
      "type": "integer"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "start_line": {
      "default": 1,
      "title": "Start Line",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Read Workspace File Excerpt",
  "type": "object"
}
```

### `read_workspace_file_sections`

- Write action: `false`
- Description:

```text
Read a file as multiple "parts" with real line numbers.  Schema: full_name*:string, max_chars_per_section:integer=80000, max_lines_per_section:integer=200, max_sections:integer=5, overlap_lines:integer=20, path:string=, ref:string=main, start_line:integer=1

This is the multi-part companion to `read_workspace_file_excerpt`.
It chunks a file into `max_sections` parts (each bounded by
`max_lines_per_section` and `max_chars_per_section`) starting at
`start_line`.

The response includes `next_start_line` when the file was truncated, so
callers can page.

Tool metadata:
- name: read_workspace_file_sections
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_chars_per_section (integer; optional, default=80000)
- max_lines_per_section (integer; optional, default=200)
- max_sections (integer; optional, default=5)
- overlap_lines (integer; optional, default=20)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- start_line (integer; optional, default=1)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "max_chars_per_section": {
      "default": 80000,
      "title": "Max Chars Per Section",
      "type": "integer"
    },
    "max_lines_per_section": {
      "default": 200,
      "title": "Max Lines Per Section",
      "type": "integer"
    },
    "max_sections": {
      "default": 5,
      "title": "Max Sections",
      "type": "integer"
    },
    "overlap_lines": {
      "default": 20,
      "title": "Overlap Lines",
      "type": "integer"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "start_line": {
      "default": 1,
      "title": "Start Line",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Read Workspace File Sections",
  "type": "object"
}
```

### `read_workspace_file_with_line_numbers`

- Write action: `false`
- Description:

```text
Read a line-numbered excerpt of a file with an optional text rendering.  Schema: end_line:any, full_name*:string, include_text:boolean=True, max_chars:integer=80000, max_lines:integer=200, path:string=, ref:string=main, separator:string=:, +1 more

This is a convenience wrapper over `read_workspace_file_excerpt` designed
for clients that want a ready-to-display string (similar to `nl -ba`).

It is safe for very large files: the implementation streams only the
requested portion and enforces max line and char budgets.

Pagination:
  - When truncated, `numbered.next_start_line` is set to the first line
    after the returned excerpt.

Args:
  end_line: Optional inclusive end line. When provided, it overrides
    max_lines.

Tool metadata:
- name: read_workspace_file_with_line_numbers
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- end_line (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_text (boolean; optional, default=True)
- max_chars (integer; optional, default=80000)
- max_lines (integer; optional, default=200)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- separator (string; optional, default=':')
- start_line (integer; optional, default=1)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "end_line": {
      "default": null,
      "title": "End Line"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "include_text": {
      "default": true,
      "title": "Include Text",
      "type": "boolean"
    },
    "max_chars": {
      "default": 80000,
      "title": "Max Chars",
      "type": "integer"
    },
    "max_lines": {
      "default": 200,
      "title": "Max Lines",
      "type": "integer"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "separator": {
      "default": ": ",
      "title": "Separator",
      "type": "string"
    },
    "start_line": {
      "default": 1,
      "title": "Start Line",
      "type": "integer"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Read Workspace File With Line Numbers",
  "type": "object"
}
```

### `recent_prs_for_branch`

- Write action: `false`
- Description:

```text
Return recent pull requests associated with a branch, grouped by state.  Schema: branch*:string, full_name*:string, include_closed:boolean=False, per_page_closed:integer=5, per_page_open:integer=20

Tool metadata:
- name: recent_prs_for_branch
- visibility: public
- write_action: false
- write_allowed: true
- tags: github, navigation, prs, read

Parameters:
- branch (string; required)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_closed (boolean; optional, default=False)
- per_page_closed (integer; optional, default=5)
- per_page_open (integer; optional, default=20)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "include_closed": {
      "default": false,
      "title": "Include Closed",
      "type": "boolean"
    },
    "per_page_closed": {
      "default": 5,
      "title": "Per Page Closed",
      "type": "integer"
    },
    "per_page_open": {
      "default": 20,
      "title": "Per Page Open",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Recent Prs For Branch",
  "type": "object"
}
```

### `render_cancel_deploy`

- Write action: `true`
- Description:

```text
Render Cancel Deploy. Signature: render_cancel_deploy(service_id: str, deploy_id: str) -> dict[str, typing.Any].  Schema: deploy_id*:string, service_id*:string

Tool metadata:
- name: render_cancel_deploy
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "deploy_id": {
      "description": "Render deploy id (example: dpl-...).",
      "title": "Deploy Id",
      "type": "string"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Render Cancel Deploy",
  "type": "object"
}
```

### `render_create_deploy`

- Write action: `true`
- Description:

```text
Render Create Deploy. Signature: render_create_deploy(service_id: str, clear_cache: bool = False, commit_id: str | None = None, image_url: str | None = None) -> dict[str, typing.Any].  Schema: clear_cache:boolean=False, commit_id:any, image_url:any, service_id*:string

Tool metadata:
- name: render_create_deploy
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- clear_cache (boolean; optional, default=False)
  When true, clears the build cache before deploying.
  Examples: True, False
- commit_id (unknown; optional)
  Optional git commit SHA to deploy (repo-backed services).
- image_url (unknown; optional)
  Optional container image URL to deploy (image-backed services).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "clear_cache": {
      "default": false,
      "description": "When true, clears the build cache before deploying.",
      "examples": [
        true,
        false
      ],
      "title": "Clear Cache",
      "type": "boolean"
    },
    "commit_id": {
      "default": null,
      "description": "Optional git commit SHA to deploy (repo-backed services).",
      "title": "Commit Id"
    },
    "image_url": {
      "default": null,
      "description": "Optional container image URL to deploy (image-backed services).",
      "title": "Image Url"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "Render Create Deploy",
  "type": "object"
}
```

### `render_create_service`

- Write action: `true`
- Description:

```text
Render Create Service. Signature: render_create_service(service_spec: dict[str, typing.Any]) -> dict[str, typing.Any].  Schema: service_spec*:object

Tool metadata:
- name: render_create_service
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- service_spec (object; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "service_spec": {
      "additionalProperties": true,
      "title": "Service Spec",
      "type": "object"
    }
  },
  "required": [
    "service_spec"
  ],
  "title": "Render Create Service",
  "type": "object"
}
```

### `render_get_deploy`

- Write action: `false`
- Description:

```text
Render Get Deploy. Signature: render_get_deploy(service_id: str, deploy_id: str) -> dict[str, typing.Any].  Schema: deploy_id*:string, service_id*:string

Tool metadata:
- name: render_get_deploy
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "deploy_id": {
      "description": "Render deploy id (example: dpl-...).",
      "title": "Deploy Id",
      "type": "string"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Render Get Deploy",
  "type": "object"
}
```

### `render_get_logs`

- Write action: `false`
- Description:

```text
Render Get Logs. Signature: render_get_logs(resource_type: str, resource_id: str, start_time: str | None = None, end_time: str | None = None, limit: int = 200) -> dict[str, typing.Any].  Schema: end_time:any, limit:integer=200, resource_id*:string, resource_type*:string, start_time:any

Tool metadata:
- name: render_get_logs
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- end_time (unknown; optional)
  Optional ISO8601 timestamp for the end of a log query window.
  Examples: '2026-01-14T13:34:56Z'
- limit (integer; optional, default=200)
  Maximum number of results to return.
  Examples: 20, 50, 200
- resource_id (string; required)
  Render log resource id corresponding to resource_type.
- resource_type (string; required)
  Render log resource type (service or job).
  Examples: 'service', 'job'
- start_time (unknown; optional)
  Optional ISO8601 timestamp for the start of a log query window.
  Examples: '2026-01-14T12:34:56Z'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "end_time": {
      "default": null,
      "description": "Optional ISO8601 timestamp for the end of a log query window.",
      "examples": [
        "2026-01-14T13:34:56Z"
      ],
      "title": "End Time"
    },
    "limit": {
      "default": 200,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    },
    "resource_id": {
      "description": "Render log resource id corresponding to resource_type.",
      "title": "Resource Id",
      "type": "string"
    },
    "resource_type": {
      "description": "Render log resource type (service or job).",
      "examples": [
        "service",
        "job"
      ],
      "title": "Resource Type",
      "type": "string"
    },
    "start_time": {
      "default": null,
      "description": "Optional ISO8601 timestamp for the start of a log query window.",
      "examples": [
        "2026-01-14T12:34:56Z"
      ],
      "title": "Start Time"
    }
  },
  "required": [
    "resource_type",
    "resource_id"
  ],
  "title": "Render Get Logs",
  "type": "object"
}
```

### `render_get_service`

- Write action: `false`
- Description:

```text
Render Get Service. Signature: render_get_service(service_id: str) -> dict[str, typing.Any].  Schema: service_id*:string

Tool metadata:
- name: render_get_service
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "Render Get Service",
  "type": "object"
}
```

### `render_list_deploys`

- Write action: `false`
- Description:

```text
Render List Deploys. Signature: render_list_deploys(service_id: str, cursor: str | None = None, limit: int = 20) -> dict[str, typing.Any].  Schema: cursor:any, limit:integer=20, service_id*:string

Tool metadata:
- name: render_list_deploys
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (unknown; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": null,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor"
    },
    "limit": {
      "default": 20,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "Render List Deploys",
  "type": "object"
}
```

### `render_list_env_vars`

- Write action: `false`
- Description:

```text
Render List Env Vars. Signature: render_list_env_vars(service_id: str) -> dict[str, typing.Any].  Schema: service_id*:string

Tool metadata:
- name: render_list_env_vars
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "Render List Env Vars",
  "type": "object"
}
```

### `render_list_logs`

- Write action: `false`
- Description:

```text
Render List Logs. Signature: render_list_logs(owner_id: str, resources: list[str], start_time: str | None = None, end_time: str | None = None, direction: str = 'backward', limit: int = 200, instance: str | None = None, host: str | None = None, level: str | None = None, method: str | None = None, status_code: int | None = None, path: str | None = None, text: str | None = None, log_type: str | None = None) -> dict[str, typing.Any].  Schema: direction:string=backward, end_time:any, host:any, instance:any, level:any, limit:integer=200, log_type:any, method:any, +6 more

Tool metadata:
- name: render_list_logs
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- direction (string; optional, default='backward')
- end_time (unknown; optional)
  Optional ISO8601 timestamp for the end of a log query window.
  Examples: '2026-01-14T13:34:56Z'
- host (unknown; optional)
- instance (unknown; optional)
- level (unknown; optional)
- limit (integer; optional, default=200)
  Maximum number of results to return.
  Examples: 20, 50, 200
- log_type (unknown; optional)
- method (unknown; optional)
- owner_id (string; required)
  Render owner id (workspace or personal owner). list_render_owners returns discoverable values.
- path (unknown; optional)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- resources (array; required)
- start_time (unknown; optional)
  Optional ISO8601 timestamp for the start of a log query window.
  Examples: '2026-01-14T12:34:56Z'
- status_code (unknown; optional)
- text (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "direction": {
      "default": "backward",
      "title": "Direction",
      "type": "string"
    },
    "end_time": {
      "default": null,
      "description": "Optional ISO8601 timestamp for the end of a log query window.",
      "examples": [
        "2026-01-14T13:34:56Z"
      ],
      "title": "End Time"
    },
    "host": {
      "default": null,
      "title": "Host"
    },
    "instance": {
      "default": null,
      "title": "Instance"
    },
    "level": {
      "default": null,
      "title": "Level"
    },
    "limit": {
      "default": 200,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    },
    "log_type": {
      "default": null,
      "title": "Log Type"
    },
    "method": {
      "default": null,
      "title": "Method"
    },
    "owner_id": {
      "description": "Render owner id (workspace or personal owner). list_render_owners returns discoverable values.",
      "title": "Owner Id",
      "type": "string"
    },
    "path": {
      "default": null,
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    },
    "resources": {
      "items": {},
      "title": "Resources",
      "type": "array"
    },
    "start_time": {
      "default": null,
      "description": "Optional ISO8601 timestamp for the start of a log query window.",
      "examples": [
        "2026-01-14T12:34:56Z"
      ],
      "title": "Start Time"
    },
    "status_code": {
      "default": null,
      "title": "Status Code"
    },
    "text": {
      "default": null,
      "title": "Text"
    }
  },
  "required": [
    "owner_id",
    "resources"
  ],
  "title": "Render List Logs",
  "type": "object"
}
```

### `render_list_owners`

- Write action: `false`
- Description:

```text
Render List Owners. Signature: render_list_owners(cursor: str | None = None, limit: int = 20) -> dict[str, typing.Any].  Schema: cursor:any, limit:integer=20

Tool metadata:
- name: render_list_owners
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (unknown; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": null,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor"
    },
    "limit": {
      "default": 20,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    }
  },
  "title": "Render List Owners",
  "type": "object"
}
```

### `render_list_services`

- Write action: `false`
- Description:

```text
Render List Services. Signature: render_list_services(owner_id: str | None = None, cursor: str | None = None, limit: int = 20) -> dict[str, typing.Any].  Schema: cursor:any, limit:integer=20, owner_id:any

Tool metadata:
- name: render_list_services
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (unknown; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200
- owner_id (unknown; optional)
  Render owner id (workspace or personal owner). list_render_owners returns discoverable values.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": null,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor"
    },
    "limit": {
      "default": 20,
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ],
      "title": "Limit",
      "type": "integer"
    },
    "owner_id": {
      "default": null,
      "description": "Render owner id (workspace or personal owner). list_render_owners returns discoverable values.",
      "title": "Owner Id"
    }
  },
  "title": "Render List Services",
  "type": "object"
}
```

### `render_patch_service`

- Write action: `true`
- Description:

```text
Render Patch Service. Signature: render_patch_service(service_id: str, patch: dict[str, typing.Any]) -> dict[str, typing.Any].  Schema: patch*:object, service_id*:string

Tool metadata:
- name: render_patch_service
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- patch (object; required)
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "patch": {
      "additionalProperties": true,
      "title": "Patch",
      "type": "object"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "patch"
  ],
  "title": "Render Patch Service",
  "type": "object"
}
```

### `render_restart_service`

- Write action: `true`
- Description:

```text
Render Restart Service. Signature: render_restart_service(service_id: str) -> dict[str, typing.Any].  Schema: service_id*:string

Tool metadata:
- name: render_restart_service
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "Render Restart Service",
  "type": "object"
}
```

### `render_rollback_deploy`

- Write action: `true`
- Description:

```text
Render Rollback Deploy. Signature: render_rollback_deploy(service_id: str, deploy_id: str) -> dict[str, typing.Any].  Schema: deploy_id*:string, service_id*:string

Tool metadata:
- name: render_rollback_deploy
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "deploy_id": {
      "description": "Render deploy id (example: dpl-...).",
      "title": "Deploy Id",
      "type": "string"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Render Rollback Deploy",
  "type": "object"
}
```

### `render_set_env_vars`

- Write action: `true`
- Description:

```text
Render Set Env Vars. Signature: render_set_env_vars(service_id: str, env_vars: list[dict[str, typing.Any]]) -> dict[str, typing.Any].  Schema: env_vars*:array, service_id*:string

Tool metadata:
- name: render_set_env_vars
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- env_vars (array; required)
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "env_vars": {
      "items": {},
      "title": "Env Vars",
      "type": "array"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "env_vars"
  ],
  "title": "Render Set Env Vars",
  "type": "object"
}
```

### `render_shell`

- Write action: `true`
- Description:

```text
Render-focused shell entry point for interacting with GitHub workspaces.  Schema: command:string=echo hello Render, command_lines:any, create_branch:any, full_name*:string, installing_dependencies:boolean=False, push_new_branch:boolean=True, ref:string=main, timeout_seconds:number=0, +2 more

This helper mirrors the Render deployment model by operating through the
server-side repo mirror. It ensures the repo mirror exists
for the default branch (or a provided ref), optionally creates a fresh
branch from that ref, and then executes the supplied shell command inside
the repo mirror.

Tool metadata:
- name: render_shell
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- command (string; optional, default='echo hello Render')
  Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (unknown; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- create_branch (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- push_new_branch (boolean; optional, default=True)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "command": {
      "default": "echo hello Render",
      "description": "Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ],
      "title": "Command",
      "type": "string"
    },
    "command_lines": {
      "default": null,
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.",
      "title": "Command Lines"
    },
    "create_branch": {
      "default": null,
      "title": "Create Branch"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies",
      "type": "boolean"
    },
    "push_new_branch": {
      "default": true,
      "title": "Push New Branch",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds",
      "type": "number"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv",
      "type": "boolean"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Render Shell",
  "type": "object"
}
```

### `replace_workspace_text`

- Write action: `true`
- Description:

```text
Replace text in a workspace file (single word/character or substring).  Schema: create_parents:boolean=True, full_name*:string, new:string=, occurrence:integer=1, old:string=, path:string=, ref:string=main, replace_all:boolean=False

By default, replaces the Nth occurrence (1-indexed). When replace_all=true,
all occurrences are replaced.

Tool metadata:
- name: replace_workspace_text
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- create_parents (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- new (string; optional, default='')
- occurrence (integer; optional, default=1)
- old (string; optional, default='')
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- replace_all (boolean; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "new": {
      "default": "",
      "title": "New",
      "type": "string"
    },
    "occurrence": {
      "default": 1,
      "title": "Occurrence",
      "type": "integer"
    },
    "old": {
      "default": "",
      "title": "Old",
      "type": "string"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "replace_all": {
      "default": false,
      "title": "Replace All",
      "type": "boolean"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Replace Workspace Text",
  "type": "object"
}
```

### `resolve_handle`

- Write action: `false`
- Description:

```text
Resolve handle. Signature: resolve_handle(full_name: str, handle: str) -> dict[str, typing.Any].  Schema: full_name*:string, handle*:string

Tool metadata:
- name: resolve_handle
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- handle (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "handle": {
      "title": "Handle",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "handle"
  ],
  "title": "Resolve Handle",
  "type": "object"
}
```

### `restart_render_service`

- Write action: `true`
- Description:

```text
Restart a Render service.  Schema: service_id*:string

Tool metadata:
- name: restart_render_service
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id"
  ],
  "title": "Restart Render Service",
  "type": "object"
}
```

### `rg_list_workspace_files`

- Write action: `false`
- Description:

```text
List files quickly (ripgrep `--files`) with an os.walk fallback.  Schema: exclude_glob:any, exclude_paths:any, full_name*:any, glob:any, include_hidden:any=True, include_paths:any, max_results:any=5000, path:any=, +1 more

Tool metadata:
- name: rg_list_workspace_files
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- exclude_glob (unknown; optional)
- exclude_paths (unknown; optional)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- glob (unknown; optional)
- include_hidden (unknown; optional, default=True)
- include_paths (unknown; optional)
- max_results (unknown; optional, default=5000)
- path (unknown; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "exclude_glob": {
      "default": null,
      "title": "Exclude Glob"
    },
    "exclude_paths": {
      "default": null,
      "title": "Exclude Paths"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "glob": {
      "default": null,
      "title": "Glob"
    },
    "include_hidden": {
      "default": true,
      "title": "Include Hidden"
    },
    "include_paths": {
      "default": null,
      "title": "Include Paths"
    },
    "max_results": {
      "default": 5000,
      "title": "Max Results"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Rg List Workspace Files",
  "type": "object"
}
```

### `rg_search_workspace`

- Write action: `false`
- Description:

```text
Search repository content and return match line numbers.  Schema: case_sensitive:any=True, context_lines:any=0, exclude_glob:any, exclude_paths:any, full_name*:any, glob:any, include_hidden:any=True, include_paths:any, +6 more

Returns structured matches with {path, line, column, text}. When
context_lines > 0, each match includes an `excerpt` object with surrounding
lines and line numbers.

Searches are always case-insensitive.

Tool metadata:
- name: rg_search_workspace
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- case_sensitive (unknown; optional, default=True)
- context_lines (unknown; optional, default=0)
- exclude_glob (unknown; optional)
- exclude_paths (unknown; optional)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- glob (unknown; optional)
- include_hidden (unknown; optional, default=True)
- include_paths (unknown; optional)
- max_file_bytes (unknown; optional)
- max_results (unknown; optional, default=200)
- path (unknown; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- query (unknown; required)
  Search query string.
  Examples: 'def main', 'import os', 'async def'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- regex (unknown; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "case_sensitive": {
      "default": true,
      "title": "Case Sensitive"
    },
    "context_lines": {
      "default": 0,
      "title": "Context Lines"
    },
    "exclude_glob": {
      "default": null,
      "title": "Exclude Glob"
    },
    "exclude_paths": {
      "default": null,
      "title": "Exclude Paths"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "glob": {
      "default": null,
      "title": "Glob"
    },
    "include_hidden": {
      "default": true,
      "title": "Include Hidden"
    },
    "include_paths": {
      "default": null,
      "title": "Include Paths"
    },
    "max_file_bytes": {
      "default": null,
      "title": "Max File Bytes"
    },
    "max_results": {
      "default": 200,
      "title": "Max Results"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    },
    "query": {
      "description": "Search query string.",
      "examples": [
        "def main",
        "import os",
        "async def"
      ],
      "title": "Query"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "regex": {
      "default": false,
      "title": "Regex"
    }
  },
  "required": [
    "full_name",
    "query"
  ],
  "title": "Rg Search Workspace",
  "type": "object"
}
```

### `rollback_render_deploy`

- Write action: `true`
- Description:

```text
Roll back a service to the specified deploy.  Schema: deploy_id*:string, service_id*:string

Tool metadata:
- name: rollback_render_deploy
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "deploy_id": {
      "description": "Render deploy id (example: dpl-...).",
      "title": "Deploy Id",
      "type": "string"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Rollback Render Deploy",
  "type": "object"
}
```

### `run_command`

- Write action: `true`
- Description:

```text
Backward-compatible alias for :func:`terminal_command`.  Schema: command:string=pytest, command_lines:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, timeout_seconds:number=0, use_temp_venv:boolean=True, workdir:any

This exists for older MCP clients that still invoke `run_command`.

Tool metadata:
- name: run_command
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- command (string; optional, default='pytest')
  Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (unknown; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "command": {
      "default": "pytest",
      "description": "Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ],
      "title": "Command",
      "type": "string"
    },
    "command_lines": {
      "default": null,
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.",
      "title": "Command Lines"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds",
      "type": "number"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv",
      "type": "boolean"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Run Command",
  "type": "object"
}
```

### `run_lint_suite`

- Write action: `false`
- Description:

```text
Run formatting + lint checks.  Schema: fail_fast:any=True, format_command:any=ruff format --check ., full_name*:any, include_format_check:any=True, include_raw_step_outputs:any=False, installing_dependencies:any=True, lint_command:any=ruff check ., ref:any=main, +3 more

Industry-standard default: include a formatting check alongside lint.

When using a temp venv + dependency installation, we run format+lint in a
single terminal_command invocation so dependencies are installed once.

Tool metadata:
- name: run_lint_suite
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- fail_fast (unknown; optional, default=True)
- format_command (unknown; optional, default='ruff format --check .')
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_format_check (unknown; optional, default=True)
- include_raw_step_outputs (unknown; optional, default=False)
- installing_dependencies (unknown; optional, default=True)
- lint_command (unknown; optional, default='ruff check .')
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (unknown; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (unknown; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "fail_fast": {
      "default": true,
      "title": "Fail Fast"
    },
    "format_command": {
      "default": "ruff format --check .",
      "title": "Format Command"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "include_format_check": {
      "default": true,
      "title": "Include Format Check"
    },
    "include_raw_step_outputs": {
      "default": false,
      "title": "Include Raw Step Outputs"
    },
    "installing_dependencies": {
      "default": true,
      "title": "Installing Dependencies"
    },
    "lint_command": {
      "default": "ruff check .",
      "title": "Lint Command"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Run Lint Suite",
  "type": "object"
}
```

### `run_python`

- Write action: `true`
- Description:

```text
Run an inline Python script inside the repo mirror.  Schema: args:any, cleanup:boolean=True, filename:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, script:string=, timeout_seconds:number=0, +2 more

The script content is written to a file within the workspace mirror and executed.
The tool exists to support multi-line scripts without relying on shell-special syntax.

Tool metadata:
- name: run_python
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- args (unknown; optional)
- cleanup (boolean; optional, default=True)
- filename (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- script (string; optional, default='')
- timeout_seconds (number; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "args": {
      "default": null,
      "title": "Args"
    },
    "cleanup": {
      "default": true,
      "title": "Cleanup",
      "type": "boolean"
    },
    "filename": {
      "default": null,
      "title": "Filename"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "script": {
      "default": "",
      "title": "Script",
      "type": "string"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds",
      "type": "number"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv",
      "type": "boolean"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Run Python",
  "type": "object"
}
```

### `run_quality_suite`

- Write action: `false`
- Description:

```text
Run quality suite. Signature: run_quality_suite(full_name: 'str', ref: 'str' = 'main', test_command: 'str' = 'pytest -q', timeout_seconds: 'float' = 0, workdir: 'str | None' = None, use_temp_venv: 'bool' = True, installing_dependencies: 'bool' = True, lint_command: 'str' = 'ruff check .', format_command: 'str | None' = None, typecheck_command: 'str | None' = None, security_command: 'str | None' = None, preflight: 'bool' = True, fail_fast: 'bool' = True, include_raw_step_outputs: 'bool' = False, *, developer_defaults: 'bool' = True, auto_fix: 'bool' = False, gate_optional_steps: 'bool' = False) -> 'dict[str, Any]'.  Schema: auto_fix:any=False, developer_defaults:any=True, fail_fast:any=True, format_command:any, full_name*:any, gate_optional_steps:any=False, include_raw_step_outputs:any=False, installing_dependencies:any=True, +9 more

Tool metadata:
- name: run_quality_suite
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- auto_fix (unknown; optional, default=False)
- developer_defaults (unknown; optional, default=True)
- fail_fast (unknown; optional, default=True)
- format_command (unknown; optional)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- gate_optional_steps (unknown; optional, default=False)
- include_raw_step_outputs (unknown; optional, default=False)
- installing_dependencies (unknown; optional, default=True)
- lint_command (unknown; optional, default='ruff check .')
- preflight (unknown; optional, default=True)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- security_command (unknown; optional)
- test_command (unknown; optional, default='pytest -q')
- timeout_seconds (unknown; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- typecheck_command (unknown; optional)
- use_temp_venv (unknown; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "auto_fix": {
      "default": false,
      "title": "Auto Fix"
    },
    "developer_defaults": {
      "default": true,
      "title": "Developer Defaults"
    },
    "fail_fast": {
      "default": true,
      "title": "Fail Fast"
    },
    "format_command": {
      "default": null,
      "title": "Format Command"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "gate_optional_steps": {
      "default": false,
      "title": "Gate Optional Steps"
    },
    "include_raw_step_outputs": {
      "default": false,
      "title": "Include Raw Step Outputs"
    },
    "installing_dependencies": {
      "default": true,
      "title": "Installing Dependencies"
    },
    "lint_command": {
      "default": "ruff check .",
      "title": "Lint Command"
    },
    "preflight": {
      "default": true,
      "title": "Preflight"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "security_command": {
      "default": null,
      "title": "Security Command"
    },
    "test_command": {
      "default": "pytest -q",
      "title": "Test Command"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds"
    },
    "typecheck_command": {
      "default": null,
      "title": "Typecheck Command"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Run Quality Suite",
  "type": "object"
}
```

### `run_shell`

- Write action: `true`
- Description:

```text
Backward-compatible alias for :func:`terminal_command`.  Schema: command:string=pytest, command_lines:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, timeout_seconds:number=0, use_temp_venv:boolean=True, workdir:any

Some integrations refer to the workspace command runner as `run_shell`.

Tool metadata:
- name: run_shell
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- command (string; optional, default='pytest')
  Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (unknown; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "command": {
      "default": "pytest",
      "description": "Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ],
      "title": "Command",
      "type": "string"
    },
    "command_lines": {
      "default": null,
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.",
      "title": "Command Lines"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds",
      "type": "number"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv",
      "type": "boolean"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Run Shell",
  "type": "object"
}
```

### `run_terminal_commands`

- Write action: `true`
- Description:

```text
Backward-compatible alias for :func:`terminal_command`.  Schema: command:string=pytest, command_lines:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, timeout_seconds:number=0, use_temp_venv:boolean=True, workdir:any

This name appears in some older controller-side tool catalogs.

Tool metadata:
- name: run_terminal_commands
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- command (string; optional, default='pytest')
  Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (unknown; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "command": {
      "default": "pytest",
      "description": "Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ],
      "title": "Command",
      "type": "string"
    },
    "command_lines": {
      "default": null,
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.",
      "title": "Command Lines"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds",
      "type": "number"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv",
      "type": "boolean"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Run Terminal Commands",
  "type": "object"
}
```

### `run_tests`

- Write action: `false`
- Description:

```text
Run tests in the repo mirror.  Schema: cov_fail_under:any, cov_report:any=term-missing:skip-covered, cov_target:any, coverage:any=False, full_name*:any, installing_dependencies:any=True, parallel:any=False, parallel_workers:any=auto, +6 more

Refactor note: uses the same step executor as the quality suite so outputs
(duration, stdout/stderr stats, etc.) are consistent across tools.

Extra knobs (coverage/parallel/timeouts) are opt-in to stay compatible with
repos that haven't adopted these plugins yet.

Tool metadata:
- name: run_tests
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cov_fail_under (unknown; optional)
- cov_report (unknown; optional, default='term-missing:skip-covered')
- cov_target (unknown; optional)
- coverage (unknown; optional, default=False)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (unknown; optional, default=True)
- parallel (unknown; optional, default=False)
- parallel_workers (unknown; optional, default='auto')
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- test_command (unknown; optional, default='pytest -q')
- timeout_per_test_seconds (unknown; optional)
- timeout_seconds (unknown; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (unknown; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cov_fail_under": {
      "default": null,
      "title": "Cov Fail Under"
    },
    "cov_report": {
      "default": "term-missing:skip-covered",
      "title": "Cov Report"
    },
    "cov_target": {
      "default": null,
      "title": "Cov Target"
    },
    "coverage": {
      "default": false,
      "title": "Coverage"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "installing_dependencies": {
      "default": true,
      "title": "Installing Dependencies"
    },
    "parallel": {
      "default": false,
      "title": "Parallel"
    },
    "parallel_workers": {
      "default": "auto",
      "title": "Parallel Workers"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "test_command": {
      "default": "pytest -q",
      "title": "Test Command"
    },
    "timeout_per_test_seconds": {
      "default": null,
      "title": "Timeout Per Test Seconds"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Run Tests",
  "type": "object"
}
```

### `scan_workspace_tree`

- Write action: `false`
- Description:

```text
Scan the workspace tree and return bounded metadata for files.  Schema: cursor:integer=0, full_name:any, hash_max_bytes:integer=200000, head_max_chars:integer=10000, head_max_lines:integer=20, include_dirs:boolean=False, include_hash:boolean=True, include_head:boolean=False, +11 more

Tool metadata:
- name: scan_workspace_tree
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- cursor (integer; optional, default=0)
  Pagination cursor returned by the previous call.
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- hash_max_bytes (integer; optional, default=200000)
- head_max_chars (integer; optional, default=10000)
- head_max_lines (integer; optional, default=20)
- include_dirs (boolean; optional, default=False)
- include_hash (boolean; optional, default=True)
- include_head (boolean; optional, default=False)
- include_hidden (boolean; optional, default=True)
- include_line_count (boolean; optional, default=True)
- line_count_max_bytes (integer; optional, default=200000)
- max_bytes (unknown; optional)
- max_chars (unknown; optional)
- max_depth (integer; optional, default=25)
- max_entries (integer; optional, default=2000)
- max_files (unknown; optional)
- max_lines (unknown; optional)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "cursor": {
      "default": 0,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor",
      "type": "integer"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "hash_max_bytes": {
      "default": 200000,
      "title": "Hash Max Bytes",
      "type": "integer"
    },
    "head_max_chars": {
      "default": 10000,
      "title": "Head Max Chars",
      "type": "integer"
    },
    "head_max_lines": {
      "default": 20,
      "title": "Head Max Lines",
      "type": "integer"
    },
    "include_dirs": {
      "default": false,
      "title": "Include Dirs",
      "type": "boolean"
    },
    "include_hash": {
      "default": true,
      "title": "Include Hash",
      "type": "boolean"
    },
    "include_head": {
      "default": false,
      "title": "Include Head",
      "type": "boolean"
    },
    "include_hidden": {
      "default": true,
      "title": "Include Hidden",
      "type": "boolean"
    },
    "include_line_count": {
      "default": true,
      "title": "Include Line Count",
      "type": "boolean"
    },
    "line_count_max_bytes": {
      "default": 200000,
      "title": "Line Count Max Bytes",
      "type": "integer"
    },
    "max_bytes": {
      "default": null,
      "title": "Max Bytes"
    },
    "max_chars": {
      "default": null,
      "title": "Max Chars"
    },
    "max_depth": {
      "default": 25,
      "title": "Max Depth",
      "type": "integer"
    },
    "max_entries": {
      "default": 2000,
      "title": "Max Entries",
      "type": "integer"
    },
    "max_files": {
      "default": null,
      "title": "Max Files"
    },
    "max_lines": {
      "default": null,
      "title": "Max Lines"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "title": "Scan Workspace Tree",
  "type": "object"
}
```

### `search`

- Write action: `false`
- Description:

```text
Search. Signature: search(query: str, search_type: Literal['code', 'repositories', 'issues', 'commits', 'users'] = 'code', per_page: int = 30, page: int = 1, sort: str | None = None, order: Optional[Literal['asc', 'desc']] = None) -> dict[str, typing.Any].  Schema: order:any, page:integer=1, per_page:integer=30, query*:string, search_type:string=code, sort:any

Tool metadata:
- name: search
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- order (unknown; optional)
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- query (string; required)
  Search query string.
  Examples: 'def main', 'import os', 'async def'
- search_type (string; optional, default='code')
- sort (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "order": {
      "default": null,
      "title": "Order"
    },
    "page": {
      "default": 1,
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ],
      "title": "Page",
      "type": "integer"
    },
    "per_page": {
      "default": 30,
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ],
      "title": "Per Page",
      "type": "integer"
    },
    "query": {
      "description": "Search query string.",
      "examples": [
        "def main",
        "import os",
        "async def"
      ],
      "title": "Query",
      "type": "string"
    },
    "search_type": {
      "default": "code",
      "title": "Search Type",
      "type": "string"
    },
    "sort": {
      "default": null,
      "title": "Sort"
    }
  },
  "required": [
    "query"
  ],
  "title": "Search",
  "type": "object"
}
```

### `search_workspace`

- Write action: `false`
- Description:

```text
Search text files in the repo mirror (bounded, no shell).  Schema: case_sensitive:boolean=False, cursor:integer=0, full_name:any, include_hidden:boolean=True, max_file_bytes:any, max_results:any, path:string=, query*:string, +2 more

Searches are always case-insensitive.

Behavior for `query`:
- When regex=true, `query` is treated as a Python regular expression.
- Otherwise `query` is treated as a literal substring match.
- max_results is enforced as an output limit and supports offset pagination
  via `cursor` (cursor is the offset in the global match stream).
- max_file_bytes is enforced as a per-file safety limit.

Tool metadata:
- name: search_workspace
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- case_sensitive (boolean; optional, default=False)
- cursor (integer; optional, default=0)
  Pagination cursor returned by the previous call.
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_hidden (boolean; optional, default=True)
- max_file_bytes (unknown; optional)
- max_results (unknown; optional)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- query (string; required)
  Search query string.
  Examples: 'def main', 'import os', 'async def'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- regex (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "case_sensitive": {
      "default": false,
      "title": "Case Sensitive",
      "type": "boolean"
    },
    "cursor": {
      "default": 0,
      "description": "Pagination cursor returned by the previous call.",
      "title": "Cursor",
      "type": "integer"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "include_hidden": {
      "default": true,
      "title": "Include Hidden",
      "type": "boolean"
    },
    "max_file_bytes": {
      "default": null,
      "title": "Max File Bytes"
    },
    "max_results": {
      "default": null,
      "title": "Max Results"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "query": {
      "description": "Search query string.",
      "examples": [
        "def main",
        "import os",
        "async def"
      ],
      "title": "Query",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "regex": {
      "default": null,
      "title": "Regex"
    }
  },
  "required": [
    "query"
  ],
  "title": "Search Workspace",
  "type": "object"
}
```

### `set_render_service_env_vars`

- Write action: `true`
- Description:

```text
Replace environment variables for a Render service.  Schema: env_vars*:array, service_id*:string

Tool metadata:
- name: set_render_service_env_vars
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- env_vars (array; required)
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "env_vars": {
      "items": {},
      "title": "Env Vars",
      "type": "array"
    },
    "service_id": {
      "description": "Render service id (example: srv-...).",
      "title": "Service Id",
      "type": "string"
    }
  },
  "required": [
    "service_id",
    "env_vars"
  ],
  "title": "Set Render Service Env Vars",
  "type": "object"
}
```

### `set_workspace_file_contents`

- Write action: `true`
- Description:

```text
Replace a workspace file's contents by writing the full file text.  Schema: content:string=, create_parents:boolean=True, full_name*:string, path:string=, ref:string=main

This is a good fit for repo-mirror edits when you want to replace the full
contents of a file without relying on unified-diff patch application.

Tool metadata:
- name: set_workspace_file_contents
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- content (string; optional, default='')
- create_parents (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "content": {
      "default": "",
      "title": "Content",
      "type": "string"
    },
    "create_parents": {
      "default": true,
      "title": "Create Parents",
      "type": "boolean"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path",
      "type": "string"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Set Workspace File Contents",
  "type": "object"
}
```

### `terminal_command`

- Write action: `true`
- Description:

```text
Run a shell command inside the repo mirror and return its result.  Schema: command:string=pytest, command_lines:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, timeout_seconds:number=0, use_temp_venv:boolean=True, workdir:any

This supports tests, linters, and project scripts that need the real working
tree.

Execution model:

- The command runs within the server-side repo mirror (a persistent git
  working copy).
- If ``use_temp_venv=true`` (default), the server ensures a **persistent**
  workspace virtualenv exists at ``<repo_dir>/.venv-mcp`` and runs the
  command inside it.
- If ``installing_dependencies=true`` and ``use_temp_venv=true``, the tool
  will run a best-effort `pip install -r dev-requirements.txt` before
  executing the command.

The venv lifecycle can be managed explicitly via the workspace venv tools
(start/stop/status), but it is also safe to rely on this implicit
preparation.

The repo mirror persists across calls so file edits and git state are
preserved until explicitly reset.

Tool metadata:
- name: terminal_command
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- command (string; optional, default='pytest')
  Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (unknown; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "command": {
      "default": "pytest",
      "description": "Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ],
      "title": "Command",
      "type": "string"
    },
    "command_lines": {
      "default": null,
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.",
      "title": "Command Lines"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds",
      "type": "number"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv",
      "type": "boolean"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Terminal Command",
  "type": "object"
}
```

### `terminal_commands`

- Write action: `true`
- Description:

```text
Backward-compatible alias for :func:`terminal_command`.  Schema: command:string=pytest, command_lines:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, timeout_seconds:number=0, use_temp_venv:boolean=True, workdir:any

Some older tool catalogs refer to the terminal runner as `terminal_commands`.

Tool metadata:
- name: terminal_commands
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- command (string; optional, default='pytest')
  Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (unknown; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=0)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "command": {
      "default": "pytest",
      "description": "Shell command to execute in the repo mirror on the server. The repo mirror lives under MCP_WORKSPACE_BASE_DIR (defaults to ~/.cache/mcp-github-workspaces).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ],
      "title": "Command",
      "type": "string"
    },
    "command_lines": {
      "default": null,
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.",
      "title": "Command Lines"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "timeout_seconds": {
      "default": 0,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds",
      "type": "number"
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv",
      "type": "boolean"
    },
    "workdir": {
      "default": null,
      "description": "Working directory to run the command from. If relative, it is resolved within the server-side repo mirror.",
      "examples": [
        "",
        "src"
      ],
      "title": "Workdir"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Terminal Commands",
  "type": "object"
}
```

### `trigger_and_wait_for_workflow`

- Write action: `true`
- Description:

```text
Trigger a workflow and block until it completes or hits timeout.  Schema: full_name*:string, inputs:any, poll_interval_seconds:integer=10, ref*:string, timeout_seconds:integer=900, workflow*:string

Tool metadata:
- name: trigger_and_wait_for_workflow
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- inputs (unknown; optional)
- poll_interval_seconds (integer; optional, default=10)
- ref (string; required)
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (integer; optional, default=900)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- workflow (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "inputs": {
      "default": null,
      "title": "Inputs"
    },
    "poll_interval_seconds": {
      "default": 10,
      "title": "Poll Interval Seconds",
      "type": "integer"
    },
    "ref": {
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "timeout_seconds": {
      "default": 900,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds",
      "type": "integer"
    },
    "workflow": {
      "title": "Workflow",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "workflow",
    "ref"
  ],
  "title": "Trigger And Wait For Workflow",
  "type": "object"
}
```

### `trigger_workflow_dispatch`

- Write action: `true`
- Description:

```text
Trigger a workflow dispatch event on the given ref.  Schema: full_name*:string, inputs:any, ref*:string, workflow*:string

Args:
full_name: "owner/repo" string.
workflow: Workflow file name or ID (e.g. "ci.yml" or a numeric ID).
ref: Git ref (branch, tag, or SHA) to run the workflow on.
inputs: Optional input payload for workflows that declare inputs.

Tool metadata:
- name: trigger_workflow_dispatch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- inputs (unknown; optional)
- ref (string; required)
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- workflow (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "inputs": {
      "default": null,
      "title": "Inputs"
    },
    "ref": {
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "workflow": {
      "title": "Workflow",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "workflow",
    "ref"
  ],
  "title": "Trigger Workflow Dispatch",
  "type": "object"
}
```

### `update_file_from_workspace`

- Write action: `true`
- Description:

```text
Update a single file in a GitHub repository from the persistent workspace checkout. This pairs with workspace editing tools (for example, terminal_command) to modify a file and then write it back to the branch.  Schema: branch*:any, full_name*:any, message*:any, target_path*:any, workspace_path*:any

Tool metadata:
- name: update_file_from_workspace
- visibility: public
- write_action: true
- write_allowed: true
- tags: files, github, write

Parameters:
- branch (unknown; required)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (unknown; required)
  Commit message.
  Examples: 'Refactor tool schemas'
- target_path (unknown; required)
- workspace_path (unknown; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "message": {
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message"
    },
    "target_path": {
      "title": "Target Path"
    },
    "workspace_path": {
      "title": "Workspace Path"
    }
  },
  "required": [
    "full_name",
    "workspace_path",
    "target_path",
    "branch",
    "message"
  ],
  "title": "Update File From Workspace",
  "type": "object"
}
```

### `update_files_and_open_pr`

- Write action: `true`
- Description:

```text
Commit multiple files, verify each, then open a PR in one call.  Schema: base_branch:string=main, body:any, draft:boolean=False, files*:array, full_name*:string, new_branch:any, title*:string

Tool metadata:
- name: update_files_and_open_pr
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- base_branch (string; optional, default='main')
- body (unknown; optional)
- draft (boolean; optional, default=False)
- files (array; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- new_branch (unknown; optional)
  Name of the branch to create.
  Examples: 'simplify-tool-schemas'
- title (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base_branch": {
      "default": "main",
      "title": "Base Branch",
      "type": "string"
    },
    "body": {
      "default": null,
      "title": "Body"
    },
    "draft": {
      "default": false,
      "title": "Draft",
      "type": "boolean"
    },
    "files": {
      "items": {},
      "title": "Files",
      "type": "array"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "new_branch": {
      "default": null,
      "description": "Name of the branch to create.",
      "examples": [
        "simplify-tool-schemas"
      ],
      "title": "New Branch"
    },
    "title": {
      "title": "Title",
      "type": "string"
    }
  },
  "required": [
    "full_name",
    "title",
    "files"
  ],
  "title": "Update Files And Open Pr",
  "type": "object"
}
```

### `update_issue`

- Write action: `true`
- Description:

```text
Update fields on an existing GitHub issue.  Schema: assignees:any, body:any, full_name*:string, issue_number*:integer, labels:any, state:any, title:any

Tool metadata:
- name: update_issue
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- assignees (unknown; optional)
- body (unknown; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)
- labels (unknown; optional)
- state (unknown; optional)
- title (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "assignees": {
      "default": null,
      "title": "Assignees"
    },
    "body": {
      "default": null,
      "title": "Body"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "issue_number": {
      "title": "Issue Number",
      "type": "integer"
    },
    "labels": {
      "default": null,
      "title": "Labels"
    },
    "state": {
      "default": null,
      "title": "State"
    },
    "title": {
      "default": null,
      "title": "Title"
    }
  },
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Update Issue",
  "type": "object"
}
```

### `validate_environment`

- Write action: `false`
- Description:

```text
Check GitHub-related environment settings and report problems.

Tool metadata:
- name: validate_environment
- visibility: public
- write_action: false
- write_allowed: true

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {},
  "title": "Validate Environment",
  "type": "object"
}
```

### `wait_for_workflow_run`

- Write action: `false`
- Description:

```text
Poll a workflow run until completion or timeout.  Schema: full_name*:string, poll_interval_seconds:integer=10, run_id*:integer, timeout_seconds:integer=900

Tool metadata:
- name: wait_for_workflow_run
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- poll_interval_seconds (integer; optional, default=10)
- run_id (integer; required)
- timeout_seconds (integer; optional, default=900)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name",
      "type": "string"
    },
    "poll_interval_seconds": {
      "default": 10,
      "title": "Poll Interval Seconds",
      "type": "integer"
    },
    "run_id": {
      "title": "Run Id",
      "type": "integer"
    },
    "timeout_seconds": {
      "default": 900,
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ],
      "title": "Timeout Seconds",
      "type": "integer"
    }
  },
  "required": [
    "full_name",
    "run_id"
  ],
  "title": "Wait For Workflow Run",
  "type": "object"
}
```

### `workspace_apply_ops_and_open_pr`

- Write action: `true`
- Description:

```text
Apply workspace operations on a new branch and open a PR.  Schema: apply_ops_args:any, base_ref:any=main, commit_message:any=Apply workspace operations, create_branch_args:any, discard_local_changes:any=True, draft:any=False, feature_ref:any, full_name*:any, +11 more

This is a convenience workflow that chains together the common sequence:

  1) Optionally reset the base workspace mirror to match origin.
  2) Create a fresh feature branch (or reuse `feature_ref`).
  3) Apply a list of `apply_workspace_operations` edits.
  4) Optionally run the quality suite.
  5) Commit + push changes.
  6) Open a PR back to `base_ref`.

Returns a JSON payload with per-step logs for UI rendering.

Notes:
  - `operations` uses the same schema as `apply_workspace_operations`.
  - If `run_quality` is true and the quality suite fails, no commit/PR is created.

Tool metadata:
- name: workspace_apply_ops_and_open_pr
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- apply_ops_args (unknown; optional)
- base_ref (unknown; optional, default='main')
  Base ref used as the starting point (branch/tag/SHA).
  Examples: 'main'
- commit_message (unknown; optional, default='Apply workspace operations')
- create_branch_args (unknown; optional)
- discard_local_changes (unknown; optional, default=True)
- draft (unknown; optional, default=False)
- feature_ref (unknown; optional)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- lint_command (unknown; optional, default='ruff check .')
- operations (unknown; optional)
- pr_args (unknown; optional)
- pr_body (unknown; optional)
- pr_title (unknown; optional)
- quality_args (unknown; optional)
- quality_timeout_seconds (unknown; optional, default=0)
- run_quality (unknown; optional, default=True)
- sync_args (unknown; optional)
- sync_base_to_remote (unknown; optional, default=True)
- test_command (unknown; optional, default='pytest -q')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "apply_ops_args": {
      "default": null,
      "title": "Apply Ops Args"
    },
    "base_ref": {
      "default": "main",
      "description": "Base ref used as the starting point (branch/tag/SHA).",
      "examples": [
        "main"
      ],
      "title": "Base Ref"
    },
    "commit_message": {
      "default": "Apply workspace operations",
      "title": "Commit Message"
    },
    "create_branch_args": {
      "default": null,
      "title": "Create Branch Args"
    },
    "discard_local_changes": {
      "default": true,
      "title": "Discard Local Changes"
    },
    "draft": {
      "default": false,
      "title": "Draft"
    },
    "feature_ref": {
      "default": null,
      "title": "Feature Ref"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "lint_command": {
      "default": "ruff check .",
      "title": "Lint Command"
    },
    "operations": {
      "default": null,
      "title": "Operations"
    },
    "pr_args": {
      "default": null,
      "title": "Pr Args"
    },
    "pr_body": {
      "default": null,
      "title": "Pr Body"
    },
    "pr_title": {
      "default": null,
      "title": "Pr Title"
    },
    "quality_args": {
      "default": null,
      "title": "Quality Args"
    },
    "quality_timeout_seconds": {
      "default": 0,
      "title": "Quality Timeout Seconds"
    },
    "run_quality": {
      "default": true,
      "title": "Run Quality"
    },
    "sync_args": {
      "default": null,
      "title": "Sync Args"
    },
    "sync_base_to_remote": {
      "default": true,
      "title": "Sync Base To Remote"
    },
    "test_command": {
      "default": "pytest -q",
      "title": "Test Command"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Apply Ops And Open Pr",
  "type": "object"
}
```

### `workspace_batch`

- Write action: `true`
- Description:

```text
Execute multiple workspace plans (across multiple branches).  Schema: default_base_ref:any=main, fail_fast:any=True, full_name*:any, plans*:any

Each item in `plans` is a dict. Supported keys:

Branch selection:
  - ref: str (required)
  - base_ref: str (optional; default is `default_base_ref`)
  - create_branch_if_missing: bool

Content ops:
  - apply_ops: { operations: [...], preview_only?: bool }
    - operations schema matches `apply_workspace_operations` (write/replace_text/
      edit_range/delete_lines/delete_word/delete_chars/delete/move/apply_patch)

  - delete_paths: { paths: [...], allow_missing?: bool, allow_recursive?: bool }
  - move_paths:   { moves: [{src,dst},...], overwrite?: bool, create_parents?: bool }

Git ops:
  - stage:   { paths?: [...] }    (omit `paths` to stage all)
  - unstage: { paths?: [...] }    (omit `paths` to unstage all)
  - diff:    { staged?: bool, paths?: [...], left_ref?: str, right_ref?: str,
              context_lines?: int, max_chars?: int }
  - summary: { path_prefix?: str, max_files?: int }

Quality:
  - tests: { command?: str, timeout_seconds?: float, workdir?: str,
            use_temp_venv?: bool, installing_dependencies?: bool }

Commit:
  - commit: { message: str, push?: bool, add_all?: bool, files?: [...] }

Returns per-plan outputs.

Tool metadata:
- name: workspace_batch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- default_base_ref (unknown; optional, default='main')
- fail_fast (unknown; optional, default=True)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- plans (unknown; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "default_base_ref": {
      "default": "main",
      "title": "Default Base Ref"
    },
    "fail_fast": {
      "default": true,
      "title": "Fail Fast"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "plans": {
      "title": "Plans"
    }
  },
  "required": [
    "full_name",
    "plans"
  ],
  "title": "Workspace Batch",
  "type": "object"
}
```

### `workspace_change_report`

- Write action: `false`
- Description:

```text
Single-call "what changed" report between two refs.  Schema: base_ref:any=main, diff_context_lines:any=3, excerpt_args:any, excerpt_context_lines:any=8, excerpt_max_lines:any=160, full_name*:any, git_diff_args:any, head_ref:any, +6 more

Produces:
  - unified diff + numstat (bounded)
  - parsed hunk ranges per file
  - contextual excerpts around each hunk from both base and head versions

Tool metadata:
- name: workspace_change_report
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- base_ref (unknown; optional, default='main')
  Base ref used as the starting point (branch/tag/SHA).
  Examples: 'main'
- diff_context_lines (unknown; optional, default=3)
- excerpt_args (unknown; optional)
- excerpt_context_lines (unknown; optional, default=8)
- excerpt_max_lines (unknown; optional, default=160)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- git_diff_args (unknown; optional)
- head_ref (unknown; optional)
- include_diff (unknown; optional, default=True)
- max_diff_chars (unknown; optional, default=200000)
- max_excerpt_chars (unknown; optional, default=80000)
- max_files (unknown; optional, default=25)
- max_hunks_per_file (unknown; optional, default=3)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base_ref": {
      "default": "main",
      "description": "Base ref used as the starting point (branch/tag/SHA).",
      "examples": [
        "main"
      ],
      "title": "Base Ref"
    },
    "diff_context_lines": {
      "default": 3,
      "title": "Diff Context Lines"
    },
    "excerpt_args": {
      "default": null,
      "title": "Excerpt Args"
    },
    "excerpt_context_lines": {
      "default": 8,
      "title": "Excerpt Context Lines"
    },
    "excerpt_max_lines": {
      "default": 160,
      "title": "Excerpt Max Lines"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "git_diff_args": {
      "default": null,
      "title": "Git Diff Args"
    },
    "head_ref": {
      "default": null,
      "title": "Head Ref"
    },
    "include_diff": {
      "default": true,
      "title": "Include Diff"
    },
    "max_diff_chars": {
      "default": 200000,
      "title": "Max Diff Chars"
    },
    "max_excerpt_chars": {
      "default": 80000,
      "title": "Max Excerpt Chars"
    },
    "max_files": {
      "default": 25,
      "title": "Max Files"
    },
    "max_hunks_per_file": {
      "default": 3,
      "title": "Max Hunks Per File"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Change Report",
  "type": "object"
}
```

### `workspace_create_branch`

- Write action: `true`
- Description:

```text
Create a branch using the repo mirror, optionally pushing to origin.  Schema: base_ref:string=main, branch:any, full_name:any, new_branch:string=, push:boolean=True

This exists because some direct GitHub-API branch-creation calls can be unavailable in some environments.

Tool metadata:
- name: workspace_create_branch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- base_ref (string; optional, default='main')
  Base ref used as the starting point (branch/tag/SHA).
  Examples: 'main'
- branch (unknown; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- new_branch (string; optional, default='')
  Name of the branch to create.
  Examples: 'simplify-tool-schemas'
- push (boolean; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base_ref": {
      "default": "main",
      "description": "Base ref used as the starting point (branch/tag/SHA).",
      "examples": [
        "main"
      ],
      "title": "Base Ref",
      "type": "string"
    },
    "branch": {
      "default": null,
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "new_branch": {
      "default": "",
      "description": "Name of the branch to create.",
      "examples": [
        "simplify-tool-schemas"
      ],
      "title": "New Branch",
      "type": "string"
    },
    "push": {
      "default": true,
      "title": "Push",
      "type": "boolean"
    }
  },
  "title": "Workspace Create Branch",
  "type": "object"
}
```

### `workspace_delete_branch`

- Write action: `true`
- Description:

```text
Delete a non-default branch using the repo mirror.  Schema: branch:string=, full_name:any

This is the workspace counterpart to branch-creation helpers and is intended
for closing out ephemeral feature branches once their work has been merged.

Tool metadata:
- name: workspace_delete_branch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- branch (string; optional, default='')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "branch": {
      "default": "",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    }
  },
  "title": "Workspace Delete Branch",
  "type": "object"
}
```

### `workspace_git_blame`

- Write action: `false`
- Description:

```text
Return `git blame` output for a file range.  Schema: end_line:any, full_name:any, git_ref:any=HEAD, max_lines:any=200, path:any=, ref:any=main, start_line:any=1

This tool returns the human-friendly blame lines (not porcelain) so it can
be used quickly for debugging.

Tool metadata:
- name: workspace_git_blame
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- end_line (unknown; optional)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- git_ref (unknown; optional, default='HEAD')
- max_lines (unknown; optional, default=200)
- path (unknown; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- start_line (unknown; optional, default=1)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "end_line": {
      "default": null,
      "title": "End Line"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "git_ref": {
      "default": "HEAD",
      "title": "Git Ref"
    },
    "max_lines": {
      "default": 200,
      "title": "Max Lines"
    },
    "path": {
      "default": "",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ],
      "title": "Path"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "start_line": {
      "default": 1,
      "title": "Start Line"
    }
  },
  "title": "Workspace Git Blame",
  "type": "object"
}
```

### `workspace_git_branches`

- Write action: `false`
- Description:

```text
List branches available in the workspace mirror.  Schema: full_name:any, include_remote:any=False, ref:any=main

Tool metadata:
- name: workspace_git_branches
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_remote (unknown; optional, default=False)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "include_remote": {
      "default": false,
      "title": "Include Remote"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Branches",
  "type": "object"
}
```

### `workspace_git_checkout`

- Write action: `true`
- Description:

```text
Checkout a branch/ref in the workspace mirror.  Schema: create:any=False, force:any=False, full_name:any, push:any=False, ref:any=main, rekey_workspace:any=True, start_point:any, target:any=

Important: workspace mirrors are keyed by `ref`. If you checkout a different
branch inside the current mirror directory, subsequent calls using
`ref=<new-branch>` would otherwise operate on a different directory. When
`rekey_workspace=true` (default) this tool moves the working copy directory
to the new branch mirror path so future calls see a consistent worktree.

- If `create=true`, creates a new local branch (and optionally pushes).
- `target` must be a non-empty ref name.

Tool metadata:
- name: workspace_git_checkout
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- create (unknown; optional, default=False)
- force (unknown; optional, default=False)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- push (unknown; optional, default=False)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- rekey_workspace (unknown; optional, default=True)
- start_point (unknown; optional)
- target (unknown; optional, default='')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "create": {
      "default": false,
      "title": "Create"
    },
    "force": {
      "default": false,
      "title": "Force"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "push": {
      "default": false,
      "title": "Push"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "rekey_workspace": {
      "default": true,
      "title": "Rekey Workspace"
    },
    "start_point": {
      "default": null,
      "title": "Start Point"
    },
    "target": {
      "default": "",
      "title": "Target"
    }
  },
  "title": "Workspace Git Checkout",
  "type": "object"
}
```

### `workspace_git_cherry_pick`

- Write action: `true`
- Description:

```text
Cherry-pick commits in the workspace mirror.  Schema: action:any=pick, commits:any, full_name:any, mainline:any, ref:any=main

Tool metadata:
- name: workspace_git_cherry_pick
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- action (unknown; optional, default='pick')
- commits (unknown; optional)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- mainline (unknown; optional)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "action": {
      "default": "pick",
      "title": "Action"
    },
    "commits": {
      "default": null,
      "title": "Commits"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "mainline": {
      "default": null,
      "title": "Mainline"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Cherry Pick",
  "type": "object"
}
```

### `workspace_git_clean`

- Write action: `true`
- Description:

```text
Clean untracked files from the workspace mirror (git clean).  Schema: dry_run:any=True, full_name:any, include_ignored:any=False, ref:any=main, remove_directories:any=True

Tool metadata:
- name: workspace_git_clean
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- dry_run (unknown; optional, default=True)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_ignored (unknown; optional, default=False)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- remove_directories (unknown; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "dry_run": {
      "default": true,
      "title": "Dry Run"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "include_ignored": {
      "default": false,
      "title": "Include Ignored"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "remove_directories": {
      "default": true,
      "title": "Remove Directories"
    }
  },
  "title": "Workspace Git Clean",
  "type": "object"
}
```

### `workspace_git_commit`

- Write action: `true`
- Description:

```text
Create a commit in the workspace mirror.  Schema: allow_empty:any=False, amend:any=False, full_name:any, message:any=, no_edit:any=False, ref:any=main, stage_all:any=False

Tool metadata:
- name: workspace_git_commit
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- allow_empty (unknown; optional, default=False)
- amend (unknown; optional, default=False)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (unknown; optional, default='')
  Commit message.
  Examples: 'Refactor tool schemas'
- no_edit (unknown; optional, default=False)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- stage_all (unknown; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "allow_empty": {
      "default": false,
      "title": "Allow Empty"
    },
    "amend": {
      "default": false,
      "title": "Amend"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "message": {
      "default": "",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message"
    },
    "no_edit": {
      "default": false,
      "title": "No Edit"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "stage_all": {
      "default": false,
      "title": "Stage All"
    }
  },
  "title": "Workspace Git Commit",
  "type": "object"
}
```

### `workspace_git_diff`

- Write action: `false`
- Description:

```text
Return a git diff from the workspace mirror.  Schema: context_lines:integer=3, full_name:any, left_ref:any, max_chars:integer=200000, paths:any, ref:string=main, right_ref:any, staged:boolean=False

Supports:
  - comparing two refs (left_ref vs right_ref)
  - comparing a ref vs working tree (set one side)
  - comparing staged changes vs HEAD (staged=true)

The returned diff is unified and includes hunk headers with line ranges.

Tool metadata:
- name: workspace_git_diff
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- context_lines (integer; optional, default=3)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- left_ref (unknown; optional)
- max_chars (integer; optional, default=200000)
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- right_ref (unknown; optional)
- staged (boolean; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "context_lines": {
      "default": 3,
      "title": "Context Lines",
      "type": "integer"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "left_ref": {
      "default": null,
      "title": "Left Ref"
    },
    "max_chars": {
      "default": 200000,
      "title": "Max Chars",
      "type": "integer"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    },
    "right_ref": {
      "default": null,
      "title": "Right Ref"
    },
    "staged": {
      "default": false,
      "title": "Staged",
      "type": "boolean"
    }
  },
  "title": "Workspace Git Diff",
  "type": "object"
}
```

### `workspace_git_fetch`

- Write action: `true`
- Description:

```text
Fetch remote refs into the workspace mirror.  Schema: full_name:any, prune:any=True, ref:any=main, remote:any=origin, tags:any=False

Tool metadata:
- name: workspace_git_fetch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- prune (unknown; optional, default=True)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- remote (unknown; optional, default='origin')
- tags (unknown; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "prune": {
      "default": true,
      "title": "Prune"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "remote": {
      "default": "origin",
      "title": "Remote"
    },
    "tags": {
      "default": false,
      "title": "Tags"
    }
  },
  "title": "Workspace Git Fetch",
  "type": "object"
}
```

### `workspace_git_log`

- Write action: `false`
- Description:

```text
Return recent commits from the workspace mirror.  Schema: full_name:any, max_chars:any=120000, max_entries:any=50, paths:any, ref:any=main, rev_range:any=HEAD

Notes:
- `rev_range` can be any git revision range expression (e.g. "HEAD", "main..HEAD").
- When `paths` is provided, the log is limited to those paths.

Tool metadata:
- name: workspace_git_log
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_chars (unknown; optional, default=120000)
- max_entries (unknown; optional, default=50)
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- rev_range (unknown; optional, default='HEAD')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "max_chars": {
      "default": 120000,
      "title": "Max Chars"
    },
    "max_entries": {
      "default": 50,
      "title": "Max Entries"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "rev_range": {
      "default": "HEAD",
      "title": "Rev Range"
    }
  },
  "title": "Workspace Git Log",
  "type": "object"
}
```

### `workspace_git_merge`

- Write action: `true`
- Description:

```text
Merge a ref into the current workspace branch.  Schema: ff_only:any=False, full_name:any, message:any, no_ff:any=False, ref:any=main, squash:any=False, target:any=

Tool metadata:
- name: workspace_git_merge
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- ff_only (unknown; optional, default=False)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (unknown; optional)
  Commit message.
  Examples: 'Refactor tool schemas'
- no_ff (unknown; optional, default=False)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- squash (unknown; optional, default=False)
- target (unknown; optional, default='')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "ff_only": {
      "default": false,
      "title": "Ff Only"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "message": {
      "default": null,
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message"
    },
    "no_ff": {
      "default": false,
      "title": "No Ff"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "squash": {
      "default": false,
      "title": "Squash"
    },
    "target": {
      "default": "",
      "title": "Target"
    }
  },
  "title": "Workspace Git Merge",
  "type": "object"
}
```

### `workspace_git_pull`

- Write action: `true`
- Description:

```text
Pull remote changes into the workspace mirror.  Schema: full_name:any, ref:any=main, strategy:any=ff-only

strategy:
- "ff-only" (default): refuse merge commits.
- "merge": allow merge commits.
- "rebase": rebase local commits on top of remote.

Tool metadata:
- name: workspace_git_pull
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- strategy (unknown; optional, default='ff-only')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "strategy": {
      "default": "ff-only",
      "title": "Strategy"
    }
  },
  "title": "Workspace Git Pull",
  "type": "object"
}
```

### `workspace_git_push`

- Write action: `true`
- Description:

```text
Push the workspace mirror branch to origin.  Schema: force_with_lease:any=False, full_name:any, ref:any=main, set_upstream:any=True

Tool metadata:
- name: workspace_git_push
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- force_with_lease (unknown; optional, default=False)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- set_upstream (unknown; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "force_with_lease": {
      "default": false,
      "title": "Force With Lease"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "set_upstream": {
      "default": true,
      "title": "Set Upstream"
    }
  },
  "title": "Workspace Git Push",
  "type": "object"
}
```

### `workspace_git_rebase`

- Write action: `true`
- Description:

```text
Run or control a rebase in the workspace mirror.  Schema: action:any=rebase, full_name:any, onto:any, ref:any=main, upstream:any

action:
- rebase (default): starts a rebase; requires upstream.
- continue / abort / skip: control an in-progress rebase.

Tool metadata:
- name: workspace_git_rebase
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- action (unknown; optional, default='rebase')
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- onto (unknown; optional)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- upstream (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "action": {
      "default": "rebase",
      "title": "Action"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "onto": {
      "default": null,
      "title": "Onto"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "upstream": {
      "default": null,
      "title": "Upstream"
    }
  },
  "title": "Workspace Git Rebase",
  "type": "object"
}
```

### `workspace_git_reset`

- Write action: `true`
- Description:

```text
Reset the workspace mirror (git reset).  Schema: full_name:any, mode:any=mixed, paths:any, ref:any=main, target:any=HEAD

Tool metadata:
- name: workspace_git_reset
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- mode (unknown; optional, default='mixed')
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- target (unknown; optional, default='HEAD')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "mode": {
      "default": "mixed",
      "title": "Mode"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "target": {
      "default": "HEAD",
      "title": "Target"
    }
  },
  "title": "Workspace Git Reset",
  "type": "object"
}
```

### `workspace_git_restore`

- Write action: `true`
- Description:

```text
Restore files in the workspace mirror (git restore).  Schema: full_name:any, paths:any, ref:any=main, source_ref:any, staged:any=False, worktree:any=True

- By default restores working tree from HEAD.
- If staged=true, affects index; if worktree=true, affects working tree.

Tool metadata:
- name: workspace_git_restore
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- source_ref (unknown; optional)
- staged (unknown; optional, default=False)
- worktree (unknown; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "source_ref": {
      "default": null,
      "title": "Source Ref"
    },
    "staged": {
      "default": false,
      "title": "Staged"
    },
    "worktree": {
      "default": true,
      "title": "Worktree"
    }
  },
  "title": "Workspace Git Restore",
  "type": "object"
}
```

### `workspace_git_revert`

- Write action: `true`
- Description:

```text
Revert commits in the workspace mirror.  Schema: commits:any, full_name:any, mainline:any, no_edit:any=True, ref:any=main

Tool metadata:
- name: workspace_git_revert
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- commits (unknown; optional)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- mainline (unknown; optional)
- no_edit (unknown; optional, default=True)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "commits": {
      "default": null,
      "title": "Commits"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "mainline": {
      "default": null,
      "title": "Mainline"
    },
    "no_edit": {
      "default": true,
      "title": "No Edit"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Revert",
  "type": "object"
}
```

### `workspace_git_show`

- Write action: `false`
- Description:

```text
Show a commit (or any git object) from the workspace mirror.  Schema: full_name:any, git_ref:any=HEAD, include_patch:any=True, max_chars:any=200000, paths:any, ref:any=main

Tool metadata:
- name: workspace_git_show
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- git_ref (unknown; optional, default='HEAD')
- include_patch (unknown; optional, default=True)
- max_chars (unknown; optional, default=200000)
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "git_ref": {
      "default": "HEAD",
      "title": "Git Ref"
    },
    "include_patch": {
      "default": true,
      "title": "Include Patch"
    },
    "max_chars": {
      "default": 200000,
      "title": "Max Chars"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Show",
  "type": "object"
}
```

### `workspace_git_stage`

- Write action: `true`
- Description:

```text
Stage changes in the workspace mirror.  Schema: full_name:any, paths:any, ref:any=main

When `paths` is omitted (None), stages all changes (`git add -A`).

Tool metadata:
- name: workspace_git_stage
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Stage",
  "type": "object"
}
```

### `workspace_git_stash_apply`

- Write action: `true`
- Description:

```text
Apply a stash in the workspace mirror (git stash apply).  Schema: full_name:any, ref:any=main, stash_ref:any=stash@{0}

Tool metadata:
- name: workspace_git_stash_apply
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- stash_ref (unknown; optional, default='stash@{0}')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "stash_ref": {
      "default": "stash@{0}",
      "title": "Stash Ref"
    }
  },
  "title": "Workspace Git Stash Apply",
  "type": "object"
}
```

### `workspace_git_stash_drop`

- Write action: `true`
- Description:

```text
Drop a stash in the workspace mirror (git stash drop).  Schema: full_name:any, ref:any=main, stash_ref:any=stash@{0}

Tool metadata:
- name: workspace_git_stash_drop
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- stash_ref (unknown; optional, default='stash@{0}')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "stash_ref": {
      "default": "stash@{0}",
      "title": "Stash Ref"
    }
  },
  "title": "Workspace Git Stash Drop",
  "type": "object"
}
```

### `workspace_git_stash_list`

- Write action: `false`
- Description:

```text
List stashes in the workspace mirror.  Schema: full_name:any, max_entries:any=50, ref:any=main

Tool metadata:
- name: workspace_git_stash_list
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_entries (unknown; optional, default=50)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "max_entries": {
      "default": 50,
      "title": "Max Entries"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Stash List",
  "type": "object"
}
```

### `workspace_git_stash_pop`

- Write action: `true`
- Description:

```text
Pop a stash in the workspace mirror (git stash pop).  Schema: full_name:any, ref:any=main, stash_ref:any=stash@{0}

Tool metadata:
- name: workspace_git_stash_pop
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- stash_ref (unknown; optional, default='stash@{0}')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "stash_ref": {
      "default": "stash@{0}",
      "title": "Stash Ref"
    }
  },
  "title": "Workspace Git Stash Pop",
  "type": "object"
}
```

### `workspace_git_stash_save`

- Write action: `true`
- Description:

```text
Create a stash in the workspace mirror (git stash push).  Schema: full_name:any, include_untracked:any=False, keep_index:any=False, message:any, ref:any=main

Tool metadata:
- name: workspace_git_stash_save
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_untracked (unknown; optional, default=False)
- keep_index (unknown; optional, default=False)
- message (unknown; optional)
  Commit message.
  Examples: 'Refactor tool schemas'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "include_untracked": {
      "default": false,
      "title": "Include Untracked"
    },
    "keep_index": {
      "default": false,
      "title": "Keep Index"
    },
    "message": {
      "default": null,
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ],
      "title": "Message"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Stash Save",
  "type": "object"
}
```

### `workspace_git_status`

- Write action: `false`
- Description:

```text
Return a structured git status for the workspace mirror.  Schema: full_name:any, ref:any=main

Tool metadata:
- name: workspace_git_status
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Status",
  "type": "object"
}
```

### `workspace_git_tags`

- Write action: `false`
- Description:

```text
List tags in the workspace mirror (most recent first when possible).  Schema: full_name:any, max_entries:any=200, ref:any=main

Tool metadata:
- name: workspace_git_tags
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_entries (unknown; optional, default=200)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "max_entries": {
      "default": 200,
      "title": "Max Entries"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Tags",
  "type": "object"
}
```

### `workspace_git_unstage`

- Write action: `true`
- Description:

```text
Unstage changes in the workspace mirror (keeps working tree edits).  Schema: full_name:any, paths:any, ref:any=main

Tool metadata:
- name: workspace_git_unstage
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "title": "Workspace Git Unstage",
  "type": "object"
}
```

### `workspace_manage_folders_and_open_pr`

- Write action: `true`
- Description:

```text
Create/remove folders on a branch and open a PR.  Schema: allow_missing:any=True, allow_recursive:any=False, base_ref:any=main, commit_message:any=Manage workspace folders, create_paths:any, delete_paths:any, discard_local_changes:any=True, draft:any=False, +12 more

This workflow converts folder operations into `apply_workspace_operations`
steps, then delegates to `workspace_apply_ops_and_open_pr`.

Tool metadata:
- name: workspace_manage_folders_and_open_pr
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- allow_missing (unknown; optional, default=True)
- allow_recursive (unknown; optional, default=False)
- base_ref (unknown; optional, default='main')
  Base ref used as the starting point (branch/tag/SHA).
  Examples: 'main'
- commit_message (unknown; optional, default='Manage workspace folders')
- create_paths (unknown; optional)
  List of repository-relative folder paths to create.
  Examples: ['docs', 'tests/fixtures']
- delete_paths (unknown; optional)
  List of repository-relative folder paths to delete.
  Examples: ['docs/legacy', 'tmp']
- discard_local_changes (unknown; optional, default=True)
- draft (unknown; optional, default=False)
- feature_ref (unknown; optional)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- lint_command (unknown; optional, default='ruff check .')
- mkdir_args (unknown; optional)
- pr_body (unknown; optional)
- pr_title (unknown; optional)
- quality_timeout_seconds (unknown; optional, default=0)
- rmdir_args (unknown; optional)
- run_quality (unknown; optional, default=True)
- sync_base_to_remote (unknown; optional, default=True)
- test_command (unknown; optional, default='pytest -q')
- workflow_args (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "allow_missing": {
      "default": true,
      "title": "Allow Missing"
    },
    "allow_recursive": {
      "default": false,
      "title": "Allow Recursive"
    },
    "base_ref": {
      "default": "main",
      "description": "Base ref used as the starting point (branch/tag/SHA).",
      "examples": [
        "main"
      ],
      "title": "Base Ref"
    },
    "commit_message": {
      "default": "Manage workspace folders",
      "title": "Commit Message"
    },
    "create_paths": {
      "default": null,
      "description": "List of repository-relative folder paths to create.",
      "examples": [
        [
          "docs",
          "tests/fixtures"
        ]
      ],
      "title": "Create Paths"
    },
    "delete_paths": {
      "default": null,
      "description": "List of repository-relative folder paths to delete.",
      "examples": [
        [
          "docs/legacy",
          "tmp"
        ]
      ],
      "title": "Delete Paths"
    },
    "discard_local_changes": {
      "default": true,
      "title": "Discard Local Changes"
    },
    "draft": {
      "default": false,
      "title": "Draft"
    },
    "feature_ref": {
      "default": null,
      "title": "Feature Ref"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "lint_command": {
      "default": "ruff check .",
      "title": "Lint Command"
    },
    "mkdir_args": {
      "default": null,
      "title": "Mkdir Args"
    },
    "pr_body": {
      "default": null,
      "title": "Pr Body"
    },
    "pr_title": {
      "default": null,
      "title": "Pr Title"
    },
    "quality_timeout_seconds": {
      "default": 0,
      "title": "Quality Timeout Seconds"
    },
    "rmdir_args": {
      "default": null,
      "title": "Rmdir Args"
    },
    "run_quality": {
      "default": true,
      "title": "Run Quality"
    },
    "sync_base_to_remote": {
      "default": true,
      "title": "Sync Base To Remote"
    },
    "test_command": {
      "default": "pytest -q",
      "title": "Test Command"
    },
    "workflow_args": {
      "default": null,
      "title": "Workflow Args"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Manage Folders And Open Pr",
  "type": "object"
}
```

### `workspace_open_pr_from_workspace`

- Write action: `true`
- Description:

```text
Open (or reuse) a PR for the workspace branch into `base`.  Schema: base:any=main, body:any, draft:any=False, full_name*:any, ref:any=main, title:any

Tool metadata:
- name: workspace_open_pr_from_workspace
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- base (unknown; optional, default='main')
- body (unknown; optional)
- draft (unknown; optional, default=False)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- title (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base": {
      "default": "main",
      "title": "Base"
    },
    "body": {
      "default": null,
      "title": "Body"
    },
    "draft": {
      "default": false,
      "title": "Draft"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "title": {
      "default": null,
      "title": "Title"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Open Pr From Workspace",
  "type": "object"
}
```

### `workspace_read_files_in_sections`

- Write action: `false`
- Description:

```text
Read multiple workspace files as chunked sections with real line numbers.  Schema: full_name*:any, include_missing:any=True, max_chars_per_section:any=80000, max_lines_per_section:any=200, max_sections:any=5, overlap_lines:any=20, paths:any, ref:any=main, +1 more

Convenience wrapper around `read_workspace_file_sections`.

Tool metadata:
- name: workspace_read_files_in_sections
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_missing (unknown; optional, default=True)
- max_chars_per_section (unknown; optional, default=80000)
- max_lines_per_section (unknown; optional, default=200)
- max_sections (unknown; optional, default=5)
- overlap_lines (unknown; optional, default=20)
- paths (unknown; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- start_line (unknown; optional, default=1)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "include_missing": {
      "default": true,
      "title": "Include Missing"
    },
    "max_chars_per_section": {
      "default": 80000,
      "title": "Max Chars Per Section"
    },
    "max_lines_per_section": {
      "default": 200,
      "title": "Max Lines Per Section"
    },
    "max_sections": {
      "default": 5,
      "title": "Max Sections"
    },
    "overlap_lines": {
      "default": 20,
      "title": "Overlap Lines"
    },
    "paths": {
      "default": null,
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ],
      "title": "Paths"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "start_line": {
      "default": 1,
      "title": "Start Line"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Read Files In Sections",
  "type": "object"
}
```

### `workspace_self_heal_branch`

- Write action: `true`
- Description:

```text
Detect a mangled repo mirror branch and recover to a fresh branch.  Schema: base_ref:string=main, branch:string=, delete_mangled_branch:boolean=True, discard_uncommitted_changes:boolean=True, dry_run:boolean=False, enumerate_repo:boolean=True, full_name:any, new_branch:any, +1 more

This tool targets cases where a repo mirror becomes inconsistent (wrong
branch checked out, merge/rebase state, conflicts, etc.). When healing, it:

1) Diagnoses the repo mirror for ``branch``.
2) Optionally deletes the mangled branch (remote + best-effort local).
3) Resets the base branch repo mirror (default: ``main``).
4) Creates + pushes a new fresh branch.
5) Ensures a clean repo mirror for the new branch.
6) Optionally returns a small repo snapshot to rebuild context.

Returns plain-language step logs for UI rendering.

Tool metadata:
- name: workspace_self_heal_branch
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- base_ref (string; optional, default='main')
  Base ref used as the starting point (branch/tag/SHA).
  Examples: 'main'
- branch (string; optional, default='')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- delete_mangled_branch (boolean; optional, default=True)
- discard_uncommitted_changes (boolean; optional, default=True)
- dry_run (boolean; optional, default=False)
- enumerate_repo (boolean; optional, default=True)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- new_branch (unknown; optional)
  Name of the branch to create.
  Examples: 'simplify-tool-schemas'
- reset_base (boolean; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "base_ref": {
      "default": "main",
      "description": "Base ref used as the starting point (branch/tag/SHA).",
      "examples": [
        "main"
      ],
      "title": "Base Ref",
      "type": "string"
    },
    "branch": {
      "default": "",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ],
      "title": "Branch",
      "type": "string"
    },
    "delete_mangled_branch": {
      "default": true,
      "title": "Delete Mangled Branch",
      "type": "boolean"
    },
    "discard_uncommitted_changes": {
      "default": true,
      "title": "Discard Uncommitted Changes",
      "type": "boolean"
    },
    "dry_run": {
      "default": false,
      "title": "Dry Run",
      "type": "boolean"
    },
    "enumerate_repo": {
      "default": true,
      "title": "Enumerate Repo",
      "type": "boolean"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "new_branch": {
      "default": null,
      "description": "Name of the branch to create.",
      "examples": [
        "simplify-tool-schemas"
      ],
      "title": "New Branch"
    },
    "reset_base": {
      "default": true,
      "title": "Reset Base",
      "type": "boolean"
    }
  },
  "title": "Workspace Self Heal Branch",
  "type": "object"
}
```

### `workspace_sync_bidirectional`

- Write action: `true`
- Description:

```text
Sync repo mirror changes to the remote and refresh local state from GitHub.  Schema: add_all:boolean=True, commit_message:string=Sync workspace changes, discard_local_changes:boolean=False, full_name:any, push:boolean=True, ref:string=main

Tool metadata:
- name: workspace_sync_bidirectional
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- add_all (boolean; optional, default=True)
- commit_message (string; optional, default='Sync workspace changes')
- discard_local_changes (boolean; optional, default=False)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- push (boolean; optional, default=True)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "add_all": {
      "default": true,
      "title": "Add All",
      "type": "boolean"
    },
    "commit_message": {
      "default": "Sync workspace changes",
      "title": "Commit Message",
      "type": "string"
    },
    "discard_local_changes": {
      "default": false,
      "title": "Discard Local Changes",
      "type": "boolean"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "push": {
      "default": true,
      "title": "Push",
      "type": "boolean"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "title": "Workspace Sync Bidirectional",
  "type": "object"
}
```

### `workspace_sync_status`

- Write action: `false`
- Description:

```text
Report how a repo mirror differs from its remote branch.  Schema: full_name:any, ref:string=main

Tool metadata:
- name: workspace_sync_status
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "title": "Workspace Sync Status",
  "type": "object"
}
```

### `workspace_sync_to_remote`

- Write action: `true`
- Description:

```text
Reset a repo mirror to match the remote branch.  Schema: discard_local_changes:boolean=False, full_name:any, ref:string=main

Tool metadata:
- name: workspace_sync_to_remote
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- discard_local_changes (boolean; optional, default=False)
- full_name (unknown; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "discard_local_changes": {
      "default": false,
      "title": "Discard Local Changes",
      "type": "boolean"
    },
    "full_name": {
      "default": null,
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref",
      "type": "string"
    }
  },
  "title": "Workspace Sync To Remote",
  "type": "object"
}
```

### `workspace_task_apply_edits`

- Write action: `true`
- Description:

```text
Apply a list of workspace edit operations with task-friendly defaults.  Schema: apply_ops_args:any, fail_fast:any=True, full_name*:any, operations:any, preview_only:any=False, ref:any=main, rollback_on_error:any=True

Tool metadata:
- name: workspace_task_apply_edits
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- apply_ops_args (unknown; optional)
- fail_fast (unknown; optional, default=True)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- operations (unknown; optional)
- preview_only (unknown; optional, default=False)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- rollback_on_error (unknown; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "apply_ops_args": {
      "default": null,
      "title": "Apply Ops Args"
    },
    "fail_fast": {
      "default": true,
      "title": "Fail Fast"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "operations": {
      "default": null,
      "title": "Operations"
    },
    "preview_only": {
      "default": false,
      "title": "Preview Only"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    },
    "rollback_on_error": {
      "default": true,
      "title": "Rollback On Error"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Task Apply Edits",
  "type": "object"
}
```

### `workspace_task_execute`

- Write action: `true`
- Description:

```text
End-to-end task workflow: plan -> edit/implement -> test -> finalize.  Schema: apply_ops_args:any, base_ref:any=main, commit_args:any, commit_message:any=Task updates, create_branch_args:any, discard_local_changes:any=True, draft:any=False, feature_ref:any, +14 more

- Planning: optional rg searches for `plan_queries` on the base ref.
- Editing/implementing: applies `operations` onto a new feature branch.
- Testing: optional lint+tests suite.
- Finalizing: either opens a PR (`finalize_mode=pr`) or commits+pushes only.

Tool metadata:
- name: workspace_task_execute
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- apply_ops_args (unknown; optional)
- base_ref (unknown; optional, default='main')
  Base ref used as the starting point (branch/tag/SHA).
  Examples: 'main'
- commit_args (unknown; optional)
- commit_message (unknown; optional, default='Task updates')
- create_branch_args (unknown; optional)
- discard_local_changes (unknown; optional, default=True)
- draft (unknown; optional, default=False)
- feature_ref (unknown; optional)
- finalize_mode (unknown; optional, default='pr')
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- lint_command (unknown; optional, default='ruff check .')
- operations (unknown; optional)
- plan_queries (unknown; optional)
- pr_args (unknown; optional)
- pr_body (unknown; optional)
- pr_title (unknown; optional)
- quality_args (unknown; optional)
- quality_timeout_seconds (unknown; optional, default=0)
- run_quality (unknown; optional, default=True)
- sync_args (unknown; optional)
- sync_base_to_remote (unknown; optional, default=True)
- test_command (unknown; optional, default='pytest -q')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "apply_ops_args": {
      "default": null,
      "title": "Apply Ops Args"
    },
    "base_ref": {
      "default": "main",
      "description": "Base ref used as the starting point (branch/tag/SHA).",
      "examples": [
        "main"
      ],
      "title": "Base Ref"
    },
    "commit_args": {
      "default": null,
      "title": "Commit Args"
    },
    "commit_message": {
      "default": "Task updates",
      "title": "Commit Message"
    },
    "create_branch_args": {
      "default": null,
      "title": "Create Branch Args"
    },
    "discard_local_changes": {
      "default": true,
      "title": "Discard Local Changes"
    },
    "draft": {
      "default": false,
      "title": "Draft"
    },
    "feature_ref": {
      "default": null,
      "title": "Feature Ref"
    },
    "finalize_mode": {
      "default": "pr",
      "title": "Finalize Mode"
    },
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "lint_command": {
      "default": "ruff check .",
      "title": "Lint Command"
    },
    "operations": {
      "default": null,
      "title": "Operations"
    },
    "plan_queries": {
      "default": null,
      "title": "Plan Queries"
    },
    "pr_args": {
      "default": null,
      "title": "Pr Args"
    },
    "pr_body": {
      "default": null,
      "title": "Pr Body"
    },
    "pr_title": {
      "default": null,
      "title": "Pr Title"
    },
    "quality_args": {
      "default": null,
      "title": "Quality Args"
    },
    "quality_timeout_seconds": {
      "default": 0,
      "title": "Quality Timeout Seconds"
    },
    "run_quality": {
      "default": true,
      "title": "Run Quality"
    },
    "sync_args": {
      "default": null,
      "title": "Sync Args"
    },
    "sync_base_to_remote": {
      "default": true,
      "title": "Sync Base To Remote"
    },
    "test_command": {
      "default": "pytest -q",
      "title": "Test Command"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Task Execute",
  "type": "object"
}
```

### `workspace_task_plan`

- Write action: `false`
- Description:

```text
Gather planning context for a task.  Schema: full_name*:any, max_search_results:any=50, max_tree_bytes:any=200000, max_tree_files:any=400, queries:any, ref:any=main

This is a lightweight, read-only helper that aggregates:
- a bounded workspace tree scan
- optional ripgrep searches for provided queries
- a suggested task workflow template (tool names + intent)

Tool metadata:
- name: workspace_task_plan
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_search_results (unknown; optional, default=50)
- max_tree_bytes (unknown; optional, default=200000)
- max_tree_files (unknown; optional, default=400)
- queries (unknown; optional)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "max_search_results": {
      "default": 50,
      "title": "Max Search Results"
    },
    "max_tree_bytes": {
      "default": 200000,
      "title": "Max Tree Bytes"
    },
    "max_tree_files": {
      "default": 400,
      "title": "Max Tree Files"
    },
    "queries": {
      "default": null,
      "title": "Queries"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Task Plan",
  "type": "object"
}
```

### `workspace_venv_start`

- Write action: `true`
- Description:

```text
Start (create/repair) the workspace virtualenv.  Schema: full_name*:any, installing_dependencies:any=False, ref:any=main

When ``installing_dependencies`` is True, this will attempt to install
``dev-requirements.txt`` (if present) inside the virtualenv.

Tool metadata:
- name: workspace_venv_start
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (unknown; optional, default=False)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Venv Start",
  "type": "object"
}
```

### `workspace_venv_status`

- Write action: `false`
- Description:

```text
Get status information for the workspace virtualenv.  Schema: full_name*:any, ref:any=main

Tool metadata:
- name: workspace_venv_status
- visibility: public
- write_action: false
- write_allowed: true

Parameters:
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Venv Status",
  "type": "object"
}
```

### `workspace_venv_stop`

- Write action: `true`
- Description:

```text
Stop (delete) the workspace virtualenv.  Schema: full_name*:any, ref:any=main

Tool metadata:
- name: workspace_venv_stop
- visibility: public
- write_action: true
- write_allowed: true

Parameters:
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are stripped from client responses by default.
    Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=0 to preserve them.
  - The server returns the tool's raw JSON-serializable result; client UIs may render summaries.

Client invocation guidance:
  - If unsure about args/params/paths, call describe_tool first and follow the returned schema.

Returns:
  A JSON-serializable value defined by the tool implementation.
```
- Output: See **Common Output Payload Shapes** above and the tool description for any tool-specific return fields.
- Input schema:

```json
{
  "additionalProperties": true,
  "properties": {
    "full_name": {
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ],
      "title": "Full Name"
    },
    "ref": {
      "default": "main",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ],
      "title": "Ref"
    }
  },
  "required": [
    "full_name"
  ],
  "title": "Workspace Venv Stop",
  "type": "object"
}
```
