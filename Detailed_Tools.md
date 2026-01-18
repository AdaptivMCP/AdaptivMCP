# Detailed tools reference (generated)

This file is generated from the running tool registry via `main.list_all_actions(include_parameters=True, compact=False)`.

Regenerate via:

```bash
python scripts/generate_detailed_tools.py > Detailed_Tools.md
```

Total tools: 135

## apply_patch

Apply a unified diff patch to the persistent repo mirror.  Schema: full_name*:string, patch:string=, ref:string=main

Invoking Apply Patch…
Invoked Apply Patch.

Tool metadata:
- name: apply_patch
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🧩
- invoking: Invoking Apply Patch…
- invoked: Invoked Apply Patch.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- patch (string; optional, default='')
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "patch": {
      "type": "string",
      "default": "",
      "title": "Patch"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Apply Patch"
}
```

Example invocation:

```json
{
  "tool": "apply_patch",
  "args": {}
}
```

## apply_text_update_and_commit

Apply Text Update And Commit. Signature: apply_text_update_and_commit(full_name: str, path: str, updated_content: str, *, branch: str = 'main', message: Optional[str] = None, return_diff: bool = False) -> Dict[str, Any].  Schema: branch:string=main, full_name*:string, message:any, path*:string, return_diff:boolean=False, updated_content*:string

Invoking Apply Text Update And Commit…
Invoked Apply Text Update And Commit.

Tool metadata:
- name: apply_text_update_and_commit
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Apply Text Update And Commit…
- invoked: Invoked Apply Text Update And Commit.

Parameters:
- branch (string; optional, default='main')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (string | null; optional)
  Commit message.
  Examples: 'Refactor tool schemas'
- path (string; required)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- return_diff (boolean; optional, default=False)
- updated_content (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "path": {
      "type": "string",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "updated_content": {
      "type": "string",
      "title": "Updated Content"
    },
    "branch": {
      "type": "string",
      "default": "main",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "message": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Message",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ]
    },
    "return_diff": {
      "type": "boolean",
      "default": false,
      "title": "Return Diff"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "path",
    "updated_content"
  ],
  "title": "Apply Text Update And Commit"
}
```

Example invocation:

```json
{
  "tool": "apply_text_update_and_commit",
  "args": {}
}
```

## apply_workspace_operations

Apply multiple file operations in a single workspace clone.  Schema: create_parents:boolean=True, fail_fast:boolean=True, full_name*:string, operations:any, preview_only:boolean=False, ref:string=main, rollback_on_error:boolean=True

This is a higher-level, multi-file alternative to calling the single-file
primitives repeatedly.

Supported operations (each item in `operations`):
  - {"op": "write", "path": "...", "content": "..."}
  - {"op": "replace_text", "path": "...", "old": "...", "new": "...", "replace_all": bool, "occurrence": int}
  - {"op": "edit_range", "path": "...", "start": {"line": int, "col": int}, "end": {"line": int, "col": int}, "replacement": "..."}
  - {"op": "delete", "path": "...", "allow_missing": bool}
  - {"op": "move", "src": "...", "dst": "...", "overwrite": bool}
  - {"op": "apply_patch", "patch": "..."}

Invoking Apply Workspace Operations…
Invoked Apply Workspace Operations.

Tool metadata:
- name: apply_workspace_operations
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🧩
- invoking: Invoking Apply Workspace Operations…
- invoked: Invoked Apply Workspace Operations.

Parameters:
- create_parents (boolean; optional, default=True)
- fail_fast (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- operations (array | null; optional)
- preview_only (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- rollback_on_error (boolean; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "operations": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": {}
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Operations"
    },
    "fail_fast": {
      "type": "boolean",
      "default": true,
      "title": "Fail Fast"
    },
    "rollback_on_error": {
      "type": "boolean",
      "default": true,
      "title": "Rollback On Error"
    },
    "preview_only": {
      "type": "boolean",
      "default": false,
      "title": "Preview Only"
    },
    "create_parents": {
      "type": "boolean",
      "default": true,
      "title": "Create Parents"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Apply Workspace Operations"
}
```

Example invocation:

```json
{
  "tool": "apply_workspace_operations",
  "args": {}
}
```

## build_pr_summary

Build a normalized JSON summary for a pull request description.  Schema: body*:string, breaking_changes:any, changed_files:any, full_name*:string, lint_status:any, ref*:string, tests_status:any, title*:string

Invoking Build Pr Summary…
Invoked Build Pr Summary.

Tool metadata:
- name: build_pr_summary
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Build Pr Summary…
- invoked: Invoked Build Pr Summary.

Parameters:
- body (string; required)
- breaking_changes (boolean | null; optional)
- changed_files (array | null; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- lint_status (string | null; optional)
- ref (string; required)
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- tests_status (string | null; optional)
- title (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "title": {
      "type": "string",
      "title": "Title"
    },
    "body": {
      "type": "string",
      "title": "Body"
    },
    "changed_files": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Changed Files"
    },
    "tests_status": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Tests Status"
    },
    "lint_status": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Lint Status"
    },
    "breaking_changes": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Breaking Changes"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "ref",
    "title",
    "body"
  ],
  "title": "Build Pr Summary"
}
```

Example invocation:

```json
{
  "tool": "build_pr_summary",
  "args": {}
}
```

## cache_files

Fetch one or more files and persist them in the server-side cache so callers can reuse them without repeating GitHub reads. refresh=true bypasses existing cache entries.  Schema: full_name*:string, paths*:array, ref:string=main, refresh:boolean=False

Invoking Cache Files…
Invoked Cache Files.

Tool metadata:
- name: cache_files
- visibility: public
- write_action: false
- write_allowed: true
- tags: cache, files, github

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Cache Files…
- invoked: Invoked Cache Files.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "paths": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "title": "Paths",
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "refresh": {
      "type": "boolean",
      "default": false,
      "title": "Refresh"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "paths"
  ],
  "title": "Cache Files"
}
```

Example invocation:

```json
{
  "tool": "cache_files",
  "args": {}
}
```

## cancel_render_deploy

Cancel an in-progress Render deploy.  Schema: deploy_id*:string, service_id*:string

Invoking Cancel Render Deploy…
Invoked Cancel Render Deploy.

Tool metadata:
- name: cancel_render_deploy
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Cancel Render Deploy…
- invoked: Invoked Cancel Render Deploy.

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "deploy_id": {
      "type": "string",
      "title": "Deploy Id",
      "description": "Render deploy id (example: dpl-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Cancel Render Deploy"
}
```

Example invocation:

```json
{
  "tool": "cancel_render_deploy",
  "args": {}
}
```

## close_pull_request

Close Pull Request. Signature: close_pull_request(full_name: str, number: int) -> Dict[str, Any].  Schema: full_name*:string, number*:integer

Invoking Close Pull Request…
Invoked Close Pull Request.

Tool metadata:
- name: close_pull_request
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Close Pull Request…
- invoked: Invoked Close Pull Request.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "number": {
      "type": "integer",
      "title": "Number"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "number"
  ],
  "title": "Close Pull Request"
}
```

Example invocation:

```json
{
  "tool": "close_pull_request",
  "args": {}
}
```

## comment_on_issue

Post a comment on an issue.  Schema: body*:string, full_name*:string, issue_number*:integer

Invoking Comment On Issue…
Invoked Comment On Issue.

Tool metadata:
- name: comment_on_issue
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Comment On Issue…
- invoked: Invoked Comment On Issue.

Parameters:
- body (string; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "issue_number": {
      "type": "integer",
      "title": "Issue Number"
    },
    "body": {
      "type": "string",
      "title": "Body"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "issue_number",
    "body"
  ],
  "title": "Comment On Issue"
}
```

Example invocation:

```json
{
  "tool": "comment_on_issue",
  "args": {}
}
```

## comment_on_pull_request

Comment On Pull Request. Signature: comment_on_pull_request(full_name: str, number: int, body: str) -> Dict[str, Any].  Schema: body*:string, full_name*:string, number*:integer

Invoking Comment On Pull Request…
Invoked Comment On Pull Request.

Tool metadata:
- name: comment_on_pull_request
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Comment On Pull Request…
- invoked: Invoked Comment On Pull Request.

Parameters:
- body (string; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "number": {
      "type": "integer",
      "title": "Number"
    },
    "body": {
      "type": "string",
      "title": "Body"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "number",
    "body"
  ],
  "title": "Comment On Pull Request"
}
```

Example invocation:

```json
{
  "tool": "comment_on_pull_request",
  "args": {}
}
```

## commit_and_open_pr_from_workspace

Commit repo mirror changes on `ref` and open a PR into `base`.  Schema: base:any=main, body:any, commit_message:any=Commit workspace changes, draft:any=False, full_name*:any, lint_command:any=ruff check ., quality_timeout_seconds:any=600, ref:any=main, +3 more

This helper is intended for the common "edit in repo mirror -> commit/push -> open PR" flow.

Notes:
- This tool only pushes to the current `ref` (feature branch). It does not mutate the base branch.
- When `run_quality` is enabled, lint/tests run before the commit is created.

Invoking Commit And Open Pr From Workspace…
Invoked Commit And Open Pr From Workspace.

Tool metadata:
- name: commit_and_open_pr_from_workspace
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Commit And Open Pr From Workspace…
- invoked: Invoked Commit And Open Pr From Workspace.

Parameters:
- base (unknown; optional, default='main')
- body (unknown; optional)
- commit_message (unknown; optional, default='Commit workspace changes')
- draft (unknown; optional, default=False)
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- lint_command (unknown; optional, default='ruff check .')
- quality_timeout_seconds (unknown; optional, default=600)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- run_quality (unknown; optional, default=False)
- test_command (unknown; optional, default='pytest')
- title (unknown; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "base": {
      "default": "main",
      "title": "Base"
    },
    "title": {
      "default": null,
      "title": "Title"
    },
    "body": {
      "default": null,
      "title": "Body"
    },
    "draft": {
      "default": false,
      "title": "Draft"
    },
    "commit_message": {
      "default": "Commit workspace changes",
      "title": "Commit Message"
    },
    "run_quality": {
      "default": false,
      "title": "Run Quality"
    },
    "quality_timeout_seconds": {
      "default": 600,
      "title": "Quality Timeout Seconds"
    },
    "test_command": {
      "default": "pytest",
      "title": "Test Command"
    },
    "lint_command": {
      "default": "ruff check .",
      "title": "Lint Command"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Commit And Open Pr From Workspace"
}
```

Example invocation:

```json
{
  "tool": "commit_and_open_pr_from_workspace",
  "args": {}
}
```

## commit_workspace

Commit repo mirror changes and optionally push them.  Schema: add_all:boolean=True, full_name:any, message:string=Commit workspace changes, push:boolean=True, ref:string=main

Invoking Commit Workspace…
Invoked Commit Workspace.

Tool metadata:
- name: commit_workspace
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Commit Workspace…
- invoked: Invoked Commit Workspace.

Parameters:
- add_all (boolean; optional, default=True)
- full_name (string | null; optional)
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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "message": {
      "type": "string",
      "default": "Commit workspace changes",
      "title": "Message",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ]
    },
    "add_all": {
      "type": "boolean",
      "default": true,
      "title": "Add All"
    },
    "push": {
      "type": "boolean",
      "default": true,
      "title": "Push"
    }
  },
  "additionalProperties": true,
  "title": "Commit Workspace"
}
```

Example invocation:

```json
{
  "tool": "commit_workspace",
  "args": {}
}
```

## commit_workspace_files

Commit and optionally push specific files from the persistent repo mirror.  Schema: files*:array, full_name*:any, message:string=Commit selected workspa…, push:boolean=True, ref:string=main

Invoking Commit Workspace Files…
Invoked Commit Workspace Files.

Tool metadata:
- name: commit_workspace_files
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Commit Workspace Files…
- invoked: Invoked Commit Workspace Files.

Parameters:
- files (array; required)
- full_name (string | null; required)
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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "files": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "title": "Files"
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "message": {
      "type": "string",
      "default": "Commit selected workspace changes",
      "title": "Message",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ]
    },
    "push": {
      "type": "boolean",
      "default": true,
      "title": "Push"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "files"
  ],
  "title": "Commit Workspace Files"
}
```

Example invocation:

```json
{
  "tool": "commit_workspace_files",
  "args": {}
}
```

## compare_workspace_files

Compare multiple file pairs or ref/path variants and return diffs.  Schema: comparisons:any, context_lines:integer=3, full_name*:string, include_stats:boolean=False, max_chars_per_side:integer=200000, max_diff_chars:integer=200000, ref:string=main

Each entry in `comparisons` supports one of the following shapes:
  1) {"left_path": "a.txt", "right_path": "b.txt"}
     Compares two workspace paths.
  2) {"path": "a.txt", "base_ref": "main"}
     Compares the workspace file at `path` (current checkout) to the file
     content at `base_ref:path` via `git show`.
  3) {"left_ref": "main", "left_path": "a.txt", "right_ref": "feature", "right_path": "a.txt"}
     Compares two git object versions without changing checkout.

Returned diffs are unified diffs and may be truncated.

If include_stats is true, each comparison result includes a "stats" object
with {added, removed} line counts derived from the full (pre-truncation)
unified diff.

Invoking Compare Workspace Files…
Invoked Compare Workspace Files.

Tool metadata:
- name: compare_workspace_files
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Compare Workspace Files…
- invoked: Invoked Compare Workspace Files.

Parameters:
- comparisons (array | null; optional)
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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "comparisons": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": {}
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Comparisons"
    },
    "context_lines": {
      "type": "integer",
      "default": 3,
      "title": "Context Lines"
    },
    "max_chars_per_side": {
      "type": "integer",
      "default": 200000,
      "title": "Max Chars Per Side"
    },
    "max_diff_chars": {
      "type": "integer",
      "default": 200000,
      "title": "Max Diff Chars"
    },
    "include_stats": {
      "type": "boolean",
      "default": false,
      "title": "Include Stats"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Compare Workspace Files"
}
```

Example invocation:

```json
{
  "tool": "compare_workspace_files",
  "args": {}
}
```

## create_branch

Create Branch. Signature: create_branch(full_name: str, branch: str, from_ref: str = 'main') -> Dict[str, Any].  Schema: branch*:string, from_ref:string=main, full_name*:string

Invoking Create Branch…
Invoked Create Branch.

Tool metadata:
- name: create_branch
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Create Branch…
- invoked: Invoked Create Branch.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "type": "string",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "from_ref": {
      "type": "string",
      "default": "main",
      "title": "From Ref",
      "description": "Ref to create the new branch from (branch/tag/SHA).",
      "examples": [
        "main"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Create Branch"
}
```

Example invocation:

```json
{
  "tool": "create_branch",
  "args": {}
}
```

## create_file

Create File. Signature: create_file(full_name: str, path: str, content: str, *, branch: str = 'main', message: Optional[str] = None) -> Dict[str, Any].  Schema: branch:string=main, content*:string, full_name*:string, message:any, path*:string

Invoking Create File…
Invoked Create File.

Tool metadata:
- name: create_file
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Create File…
- invoked: Invoked Create File.

Parameters:
- branch (string; optional, default='main')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- content (string; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (string | null; optional)
  Commit message.
  Examples: 'Refactor tool schemas'
- path (string; required)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "path": {
      "type": "string",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "content": {
      "type": "string",
      "title": "Content"
    },
    "branch": {
      "type": "string",
      "default": "main",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "message": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Message",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "path",
    "content"
  ],
  "title": "Create File"
}
```

Example invocation:

```json
{
  "tool": "create_file",
  "args": {}
}
```

## create_issue

Create a GitHub issue in the given repository.  Schema: assignees:any, body:any, full_name*:string, labels:any, title*:string

Invoking Create Issue…
Invoked Create Issue.

Tool metadata:
- name: create_issue
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Create Issue…
- invoked: Invoked Create Issue.

Parameters:
- assignees (array | null; optional)
- body (string | null; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- labels (array | null; optional)
- title (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "title": {
      "type": "string",
      "title": "Title"
    },
    "body": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Body"
    },
    "labels": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Labels"
    },
    "assignees": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Assignees"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "title"
  ],
  "title": "Create Issue"
}
```

Example invocation:

```json
{
  "tool": "create_issue",
  "args": {}
}
```

## create_pull_request

Open a pull request from ``head`` into ``base``.  Schema: base:string=main, body:any, draft:boolean=False, full_name*:string, head*:string, title*:string

The base branch is normalized via ``_effective_ref_for_repo`` so that
controller repos honor the configured default branch even when callers
supply a simple base name like "main".

Invoking Create Pull Request…
Invoked Create Pull Request.

Tool metadata:
- name: create_pull_request
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Create Pull Request…
- invoked: Invoked Create Pull Request.

Parameters:
- base (string; optional, default='main')
- body (string | null; optional)
- draft (boolean; optional, default=False)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- head (string; required)
- title (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "title": {
      "type": "string",
      "title": "Title"
    },
    "head": {
      "type": "string",
      "title": "Head"
    },
    "base": {
      "type": "string",
      "default": "main",
      "title": "Base"
    },
    "body": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Body"
    },
    "draft": {
      "type": "boolean",
      "default": false,
      "title": "Draft"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "title",
    "head"
  ],
  "title": "Create Pull Request"
}
```

Example invocation:

```json
{
  "tool": "create_pull_request",
  "args": {}
}
```

## create_render_deploy

Trigger a new deploy for a Render service.  Schema: clear_cache:boolean=False, commit_id:any, image_url:any, service_id*:string

Invoking Create Render Deploy…
Invoked Create Render Deploy.

Tool metadata:
- name: create_render_deploy
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Create Render Deploy…
- invoked: Invoked Create Render Deploy.

Parameters:
- clear_cache (boolean; optional, default=False)
  When true, clears the build cache before deploying.
  Examples: True, False
- commit_id (string | null; optional)
  Optional git commit SHA to deploy (repo-backed services).
- image_url (string | null; optional)
  Optional container image URL to deploy (image-backed services).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "clear_cache": {
      "type": "boolean",
      "default": false,
      "title": "Clear Cache",
      "description": "When true, clears the build cache before deploying.",
      "examples": [
        true,
        false
      ]
    },
    "commit_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Commit Id",
      "description": "Optional git commit SHA to deploy (repo-backed services)."
    },
    "image_url": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Image Url",
      "description": "Optional container image URL to deploy (image-backed services)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id"
  ],
  "title": "Create Render Deploy"
}
```

Example invocation:

```json
{
  "tool": "create_render_deploy",
  "args": {}
}
```

## create_render_service

Create a new Render service.  Schema: service_spec*:object

Invoking Create Render Service…
Invoked Create Render Service.

Tool metadata:
- name: create_render_service
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Create Render Service…
- invoked: Invoked Create Render Service.

Parameters:
- service_spec (object; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_spec": {
      "type": "object",
      "additionalProperties": {},
      "title": "Service Spec"
    }
  },
  "additionalProperties": true,
  "required": [
    "service_spec"
  ],
  "title": "Create Render Service"
}
```

Example invocation:

```json
{
  "tool": "create_render_service",
  "args": {}
}
```

## create_repository

Create Repository. Signature: create_repository(name: str, owner: Optional[str] = None, owner_type: Literal['auto', 'user', 'org'] = 'auto', description: Optional[str] = None, homepage: Optional[str] = None, visibility: Optional[Literal['public', 'private', 'internal']] = None, private: Optional[bool] = None, auto_init: bool = True, gitignore_template: Optional[str] = None, license_template: Optional[str] = None, is_template: bool = False, has_issues: bool = True, has_projects: Optional[bool] = None, has_wiki: bool = True, has_discussions: Optional[bool] = None, team_id: Optional[int] = None, security_and_analysis: Optional[Dict[str, Any]] = None, template_full_name: Optional[str] = None, include_all_branches: bool = False, topics: Optional[List[str]] = None, create_payload_overrides: Optional[Dict[str, Any]] = None, update_payload_overrides: Optional[Dict[str, Any]] = None, clone_to_workspace: bool = False, clone_ref: Optional[str] = None) -> Dict[str, Any].  Schema: auto_init:boolean=True, clone_ref:any, clone_to_workspace:boolean=False, create_payload_overrides:any, description:any, gitignore_template:any, has_discussions:any, has_issues:boolean=True, +16 more

Invoking Create Repository…
Invoked Create Repository.

Tool metadata:
- name: create_repository
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Create Repository…
- invoked: Invoked Create Repository.

Parameters:
- auto_init (boolean; optional, default=True)
- clone_ref (string | null; optional)
- clone_to_workspace (boolean; optional, default=False)
- create_payload_overrides (object | null; optional)
- description (string | null; optional)
- gitignore_template (string | null; optional)
- has_discussions (boolean | null; optional)
- has_issues (boolean; optional, default=True)
- has_projects (boolean | null; optional)
- has_wiki (boolean; optional, default=True)
- homepage (string | null; optional)
- include_all_branches (boolean; optional, default=False)
- is_template (boolean; optional, default=False)
- license_template (string | null; optional)
- name (string; required)
- owner (string | null; optional)
- owner_type (string; optional, default='auto')
- private (boolean | null; optional)
- security_and_analysis (object | null; optional)
- team_id (integer | null; optional)
- template_full_name (string | null; optional)
- topics (array | null; optional)
- update_payload_overrides (object | null; optional)
- visibility (string | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "title": "Name"
    },
    "owner": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Owner"
    },
    "owner_type": {
      "enum": [
        "auto",
        "user",
        "org"
      ],
      "type": "string",
      "default": "auto",
      "title": "Owner Type"
    },
    "description": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Description"
    },
    "homepage": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Homepage"
    },
    "visibility": {
      "anyOf": [
        {
          "enum": [
            "public",
            "private",
            "internal"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Visibility"
    },
    "private": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Private"
    },
    "auto_init": {
      "type": "boolean",
      "default": true,
      "title": "Auto Init"
    },
    "gitignore_template": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Gitignore Template"
    },
    "license_template": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "License Template"
    },
    "is_template": {
      "type": "boolean",
      "default": false,
      "title": "Is Template"
    },
    "has_issues": {
      "type": "boolean",
      "default": true,
      "title": "Has Issues"
    },
    "has_projects": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Has Projects"
    },
    "has_wiki": {
      "type": "boolean",
      "default": true,
      "title": "Has Wiki"
    },
    "has_discussions": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Has Discussions"
    },
    "team_id": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Team Id"
    },
    "security_and_analysis": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": {}
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Security And Analysis"
    },
    "template_full_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Template Full Name"
    },
    "include_all_branches": {
      "type": "boolean",
      "default": false,
      "title": "Include All Branches"
    },
    "topics": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Topics"
    },
    "create_payload_overrides": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": {}
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Create Payload Overrides"
    },
    "update_payload_overrides": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": {}
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Update Payload Overrides"
    },
    "clone_to_workspace": {
      "type": "boolean",
      "default": false,
      "title": "Clone To Workspace"
    },
    "clone_ref": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Clone Ref"
    }
  },
  "additionalProperties": true,
  "required": [
    "name"
  ],
  "title": "Create Repository"
}
```

Example invocation:

```json
{
  "tool": "create_repository",
  "args": {}
}
```

## delete_file

Delete a file from a GitHub repository using the Contents API. Often used in combination with branch management helpers.  Schema: branch:any=main, full_name*:any, if_missing:any=error, message:any=Delete file via MCP Git…, path*:any

Invoking Delete File…
Invoked Delete File.

Tool metadata:
- name: delete_file
- visibility: public
- write_action: true
- write_allowed: true
- tags: delete, files, github, write

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Delete File…
- invoked: Invoked Delete File.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "path": {
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "message": {
      "default": "Delete file via MCP GitHub connector",
      "title": "Message",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ]
    },
    "branch": {
      "default": "main",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "if_missing": {
      "default": "error",
      "title": "If Missing"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "path"
  ],
  "title": "Delete File"
}
```

Example invocation:

```json
{
  "tool": "delete_file",
  "args": {}
}
```

## delete_workspace_paths

Delete one or more paths from the repo mirror.  Schema: allow_missing:boolean=True, allow_recursive:boolean=False, full_name*:string, paths:any, ref:string=main

This tool exists because some environments can block patch-based file deletions.
Prefer this over embedding deletions into unified-diff patches.

Notes:
  - `paths` must be repo-relative paths.
  - Directories require `allow_recursive=true` (for non-empty directories).

Invoking Delete Workspace Paths…
Invoked Delete Workspace Paths.

Tool metadata:
- name: delete_workspace_paths
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Delete Workspace Paths…
- invoked: Invoked Delete Workspace Paths.

Parameters:
- allow_missing (boolean; optional, default=True)
- allow_recursive (boolean; optional, default=False)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- paths (array | null; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "paths": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Paths",
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ]
    },
    "allow_missing": {
      "type": "boolean",
      "default": true,
      "title": "Allow Missing"
    },
    "allow_recursive": {
      "type": "boolean",
      "default": false,
      "title": "Allow Recursive"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Delete Workspace Paths"
}
```

Example invocation:

```json
{
  "tool": "delete_workspace_paths",
  "args": {}
}
```

## describe_tool

Return optional schema for one or more tools. Prefer this over manually scanning list_all_actions in long sessions.  Schema: include_parameters:boolean=True, name:any, names:any

Invoking Describe Tool…
Invoked Describe Tool.

Tool metadata:
- name: describe_tool
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Describe Tool…
- invoked: Invoked Describe Tool.

Parameters:
- include_parameters (boolean; optional, default=True)
- name (string | null; optional)
- names (array | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Name"
    },
    "names": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Names"
    },
    "include_parameters": {
      "type": "boolean",
      "default": true,
      "title": "Include Parameters"
    }
  },
  "additionalProperties": true,
  "title": "Describe Tool"
}
```

Example invocation:

```json
{
  "tool": "describe_tool",
  "args": {}
}
```

## download_user_content

Download user-provided content (sandbox/local/http) with base64 encoding.  Schema: content_url*:string

Invoking Download User Content…
Invoked Download User Content.

Tool metadata:
- name: download_user_content
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Download User Content…
- invoked: Invoked Download User Content.

Parameters:
- content_url (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "content_url": {
      "type": "string",
      "title": "Content Url"
    }
  },
  "additionalProperties": true,
  "required": [
    "content_url"
  ],
  "title": "Download User Content"
}
```

Example invocation:

```json
{
  "tool": "download_user_content",
  "args": {}
}
```

## edit_workspace_line

Edit a single line in a workspace file.  Schema: create_parents:boolean=True, full_name*:string, line_number:integer=1, operation:string=replace, path:string=, ref:string=main, text:string=

Operations:
  - replace: replace the target line's content (preserves its line ending).
  - insert_before / insert_after: insert a new line adjacent to line_number.
  - delete: delete the target line.

Line numbers are 1-indexed.

Invoking Edit Workspace Line…
Invoked Edit Workspace Line.

Tool metadata:
- name: edit_workspace_line
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Edit Workspace Line…
- invoked: Invoked Edit Workspace Line.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "path": {
      "type": "string",
      "default": "",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "operation": {
      "enum": [
        "replace",
        "insert_before",
        "insert_after",
        "delete"
      ],
      "type": "string",
      "default": "replace",
      "title": "Operation"
    },
    "line_number": {
      "type": "integer",
      "default": 1,
      "title": "Line Number"
    },
    "text": {
      "type": "string",
      "default": "",
      "title": "Text"
    },
    "create_parents": {
      "type": "boolean",
      "default": true,
      "title": "Create Parents"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Edit Workspace Line"
}
```

Example invocation:

```json
{
  "tool": "edit_workspace_line",
  "args": {}
}
```

## edit_workspace_text_range

Edit a file by replacing a precise (line, column) text range.  Schema: create_parents:boolean=True, end_col:integer=1, end_line:integer=1, full_name*:string, path:string=, ref:string=main, replacement:string=, start_col:integer=1, +1 more

This is the most granular edit primitive:
  - Single-character edit: start=(L,C), end=(L,C+1)
  - Word edit: start/end wrap the word
  - Line edit: start=(L,1), end=(L+1,1) (includes the newline)

Positions are 1-indexed. The end position is *exclusive* (Python-slice
semantics).

Invoking Edit Workspace Text Range…
Invoked Edit Workspace Text Range.

Tool metadata:
- name: edit_workspace_text_range
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Edit Workspace Text Range…
- invoked: Invoked Edit Workspace Text Range.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "path": {
      "type": "string",
      "default": "",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "start_line": {
      "type": "integer",
      "default": 1,
      "title": "Start Line"
    },
    "start_col": {
      "type": "integer",
      "default": 1,
      "title": "Start Col"
    },
    "end_line": {
      "type": "integer",
      "default": 1,
      "title": "End Line"
    },
    "end_col": {
      "type": "integer",
      "default": 1,
      "title": "End Col"
    },
    "replacement": {
      "type": "string",
      "default": "",
      "title": "Replacement"
    },
    "create_parents": {
      "type": "boolean",
      "default": true,
      "title": "Create Parents"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Edit Workspace Text Range"
}
```

Example invocation:

```json
{
  "tool": "edit_workspace_text_range",
  "args": {}
}
```

## ensure_branch

Ensure Branch. Signature: ensure_branch(full_name: str, branch: str, from_ref: str = 'main') -> Dict[str, Any].  Schema: branch*:string, from_ref:string=main, full_name*:string

Invoking Ensure Branch…
Invoked Ensure Branch.

Tool metadata:
- name: ensure_branch
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Ensure Branch…
- invoked: Invoked Ensure Branch.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "type": "string",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "from_ref": {
      "type": "string",
      "default": "main",
      "title": "From Ref",
      "description": "Ref to create the new branch from (branch/tag/SHA).",
      "examples": [
        "main"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Ensure Branch"
}
```

Example invocation:

```json
{
  "tool": "ensure_branch",
  "args": {}
}
```

## ensure_workspace_clone

Ensure a persistent repo mirror (workspace clone) exists for a repo/ref.  Schema: full_name*:any, ref:any=main, reset:any=False

Invoking Ensure Workspace Clone…
Invoked Ensure Workspace Clone.

Tool metadata:
- name: ensure_workspace_clone
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Ensure Workspace Clone…
- invoked: Invoked Ensure Workspace Clone.

Parameters:
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- reset (unknown; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "reset": {
      "default": false,
      "title": "Reset"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Ensure Workspace Clone"
}
```

Example invocation:

```json
{
  "tool": "ensure_workspace_clone",
  "args": {}
}
```

## fetch_files

Fetch Files. Signature: fetch_files(full_name: str, paths: List[str], ref: str = 'main') -> Dict[str, Any].  Schema: full_name*:string, paths*:array, ref:string=main

Invoking Fetch Files…
Invoked Fetch Files.

Tool metadata:
- name: fetch_files
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Fetch Files…
- invoked: Invoked Fetch Files.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "paths": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "title": "Paths",
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "paths"
  ],
  "title": "Fetch Files"
}
```

Example invocation:

```json
{
  "tool": "fetch_files",
  "args": {}
}
```

## fetch_issue

Fetch Issue. Signature: fetch_issue(full_name: str, issue_number: int) -> Dict[str, Any].  Schema: full_name*:string, issue_number*:integer

Invoking Fetch Issue…
Invoked Fetch Issue.

Tool metadata:
- name: fetch_issue
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Fetch Issue…
- invoked: Invoked Fetch Issue.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "issue_number": {
      "type": "integer",
      "title": "Issue Number"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Fetch Issue"
}
```

Example invocation:

```json
{
  "tool": "fetch_issue",
  "args": {}
}
```

## fetch_issue_comments

Fetch Issue Comments. Signature: fetch_issue_comments(full_name: str, issue_number: int, per_page: int = 30, page: int = 1) -> Dict[str, Any].  Schema: full_name*:string, issue_number*:integer, page:integer=1, per_page:integer=30

Invoking Fetch Issue Comments…
Invoked Fetch Issue Comments.

Tool metadata:
- name: fetch_issue_comments
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Fetch Issue Comments…
- invoked: Invoked Fetch Issue Comments.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "issue_number": {
      "type": "integer",
      "title": "Issue Number"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Fetch Issue Comments"
}
```

Example invocation:

```json
{
  "tool": "fetch_issue_comments",
  "args": {}
}
```

## fetch_pr

Fetch Pr. Signature: fetch_pr(full_name: str, pull_number: int) -> Dict[str, Any].  Schema: full_name*:string, pull_number*:integer

Invoking Fetch Pr…
Invoked Fetch Pr.

Tool metadata:
- name: fetch_pr
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Fetch Pr…
- invoked: Invoked Fetch Pr.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- pull_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "pull_number": {
      "type": "integer",
      "title": "Pull Number"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Fetch Pr"
}
```

Example invocation:

```json
{
  "tool": "fetch_pr",
  "args": {}
}
```

## fetch_pr_comments

Fetch Pr Comments. Signature: fetch_pr_comments(full_name: str, pull_number: int, per_page: int = 30, page: int = 1) -> Dict[str, Any].  Schema: full_name*:string, page:integer=1, per_page:integer=30, pull_number*:integer

Invoking Fetch Pr Comments…
Invoked Fetch Pr Comments.

Tool metadata:
- name: fetch_pr_comments
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Fetch Pr Comments…
- invoked: Invoked Fetch Pr Comments.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "pull_number": {
      "type": "integer",
      "title": "Pull Number"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Fetch Pr Comments"
}
```

Example invocation:

```json
{
  "tool": "fetch_pr_comments",
  "args": {}
}
```

## fetch_url

Fetch Url. Signature: fetch_url(url: str) -> Dict[str, Any].  Schema: url*:string

Invoking Fetch Url…
Invoked Fetch Url.

Tool metadata:
- name: fetch_url
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Fetch Url…
- invoked: Invoked Fetch Url.

Parameters:
- url (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "url": {
      "type": "string",
      "title": "Url"
    }
  },
  "additionalProperties": true,
  "required": [
    "url"
  ],
  "title": "Fetch Url"
}
```

Example invocation:

```json
{
  "tool": "fetch_url",
  "args": {}
}
```

## get_branch_summary

Get Branch Summary. Signature: get_branch_summary(full_name: str, branch: str, base: str = 'main') -> Dict[str, Any].  Schema: base:string=main, branch*:string, full_name*:string

Invoking Get Branch Summary…
Invoked Get Branch Summary.

Tool metadata:
- name: get_branch_summary
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Branch Summary…
- invoked: Invoked Get Branch Summary.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "type": "string",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "base": {
      "type": "string",
      "default": "main",
      "title": "Base"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Get Branch Summary"
}
```

Example invocation:

```json
{
  "tool": "get_branch_summary",
  "args": {}
}
```

## get_cached_files

Return cached file payloads for a repository/ref without re-fetching from GitHub. Entries persist for the lifetime of the server process until evicted by size or entry caps.  Schema: full_name*:string, paths*:array, ref:string=main

Invoking Get Cached Files…
Invoked Get Cached Files.

Tool metadata:
- name: get_cached_files
- visibility: public
- write_action: false
- write_allowed: true
- tags: cache, files, github

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Cached Files…
- invoked: Invoked Get Cached Files.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "paths": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "title": "Paths",
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "paths"
  ],
  "title": "Get Cached Files"
}
```

Example invocation:

```json
{
  "tool": "get_cached_files",
  "args": {}
}
```

## get_commit_combined_status

Get Commit Combined Status. Signature: get_commit_combined_status(full_name: str, ref: str) -> Dict[str, Any].  Schema: full_name*:string, ref*:string

Invoking Get Commit Combined Status…
Invoked Get Commit Combined Status.

Tool metadata:
- name: get_commit_combined_status
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Commit Combined Status…
- invoked: Invoked Get Commit Combined Status.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (string; required)
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "ref"
  ],
  "title": "Get Commit Combined Status"
}
```

Example invocation:

```json
{
  "tool": "get_commit_combined_status",
  "args": {}
}
```

## get_file_contents

Fetch a single file from GitHub and decode base64 to UTF-8 text.  Schema: full_name*:string, path*:string, ref:string=main

Invoking Get File Contents…
Invoked Get File Contents.

Tool metadata:
- name: get_file_contents
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get File Contents…
- invoked: Invoked Get File Contents.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "path": {
      "type": "string",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "path"
  ],
  "title": "Get File Contents"
}
```

Example invocation:

```json
{
  "tool": "get_file_contents",
  "args": {}
}
```

## get_file_excerpt

Get File Excerpt. Signature: get_file_excerpt(full_name: str, path: str, ref: str = 'main', start_byte: Optional[int] = None, max_bytes: int = 65536, tail_bytes: Optional[int] = None, as_text: bool = True, max_text_chars: int = 200000, numbered_lines: bool = True) -> Dict[str, Any].  Schema: as_text:boolean=True, full_name*:string, max_bytes:integer=65536, max_text_chars:integer=200000, numbered_lines:boolean=True, path*:string, ref:string=main, start_byte:any, +1 more

Invoking Get File Excerpt…
Invoked Get File Excerpt.

Tool metadata:
- name: get_file_excerpt
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get File Excerpt…
- invoked: Invoked Get File Excerpt.

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
- start_byte (integer | null; optional)
- tail_bytes (integer | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "path": {
      "type": "string",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "start_byte": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Start Byte"
    },
    "max_bytes": {
      "type": "integer",
      "default": 65536,
      "title": "Max Bytes"
    },
    "tail_bytes": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Tail Bytes"
    },
    "as_text": {
      "type": "boolean",
      "default": true,
      "title": "As Text"
    },
    "max_text_chars": {
      "type": "integer",
      "default": 200000,
      "title": "Max Text Chars"
    },
    "numbered_lines": {
      "type": "boolean",
      "default": true,
      "title": "Numbered Lines"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "path"
  ],
  "title": "Get File Excerpt"
}
```

Example invocation:

```json
{
  "tool": "get_file_excerpt",
  "args": {}
}
```

## get_issue_comment_reactions

Get Issue Comment Reactions. Signature: get_issue_comment_reactions(full_name: str, comment_id: int, per_page: int = 30, page: int = 1) -> Dict[str, Any].  Schema: comment_id*:integer, full_name*:string, page:integer=1, per_page:integer=30

Invoking Get Issue Comment Reactions…
Invoked Get Issue Comment Reactions.

Tool metadata:
- name: get_issue_comment_reactions
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Issue Comment Reactions…
- invoked: Invoked Get Issue Comment Reactions.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "comment_id": {
      "type": "integer",
      "title": "Comment Id"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "comment_id"
  ],
  "title": "Get Issue Comment Reactions"
}
```

Example invocation:

```json
{
  "tool": "get_issue_comment_reactions",
  "args": {}
}
```

## get_issue_overview

Return a high-level overview of an issue, including related branches, pull requests, and checklist items.  Schema: full_name*:string, issue_number*:integer

Invoking Get Issue Overview…
Invoked Get Issue Overview.

Tool metadata:
- name: get_issue_overview
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Issue Overview…
- invoked: Invoked Get Issue Overview.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "issue_number": {
      "type": "integer",
      "title": "Issue Number"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Get Issue Overview"
}
```

Example invocation:

```json
{
  "tool": "get_issue_overview",
  "args": {}
}
```

## get_job_logs

Fetch raw logs for a GitHub Actions job without truncation.  Schema: full_name*:string, job_id*:integer

Invoking Get Job Logs…
Invoked Get Job Logs.

Tool metadata:
- name: get_job_logs
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Job Logs…
- invoked: Invoked Get Job Logs.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- job_id (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "job_id": {
      "type": "integer",
      "title": "Job Id"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "job_id"
  ],
  "title": "Get Job Logs"
}
```

Example invocation:

```json
{
  "tool": "get_job_logs",
  "args": {}
}
```

## get_latest_branch_status

Get Latest Branch Status. Signature: get_latest_branch_status(full_name: str, branch: str, base: str = 'main') -> Dict[str, Any].  Schema: base:string=main, branch*:string, full_name*:string

Invoking Get Latest Branch Status…
Invoked Get Latest Branch Status.

Tool metadata:
- name: get_latest_branch_status
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Latest Branch Status…
- invoked: Invoked Get Latest Branch Status.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "type": "string",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "base": {
      "type": "string",
      "default": "main",
      "title": "Base"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Get Latest Branch Status"
}
```

Example invocation:

```json
{
  "tool": "get_latest_branch_status",
  "args": {}
}
```

## get_pr_info

Get Pr Info. Signature: get_pr_info(full_name: str, pull_number: int) -> Dict[str, Any].  Schema: full_name*:string, pull_number*:integer

Invoking Get Pr Info…
Invoked Get Pr Info.

Tool metadata:
- name: get_pr_info
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Pr Info…
- invoked: Invoked Get Pr Info.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- pull_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "pull_number": {
      "type": "integer",
      "title": "Pull Number"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Get Pr Info"
}
```

Example invocation:

```json
{
  "tool": "get_pr_info",
  "args": {}
}
```

## get_pr_overview

Return a compact overview of a pull request, including files and CI status.  Schema: full_name*:string, pull_number*:integer

Invoking Get Pr Overview…
Invoked Get Pr Overview.

Tool metadata:
- name: get_pr_overview
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Pr Overview…
- invoked: Invoked Get Pr Overview.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- pull_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "pull_number": {
      "type": "integer",
      "title": "Pull Number"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Get Pr Overview"
}
```

Example invocation:

```json
{
  "tool": "get_pr_overview",
  "args": {}
}
```

## get_pr_reactions

Fetch reactions for a GitHub pull request.  Schema: full_name*:string, page:integer=1, per_page:integer=30, pull_number*:integer

Invoking Get Pr Reactions…
Invoked Get Pr Reactions.

Tool metadata:
- name: get_pr_reactions
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Pr Reactions…
- invoked: Invoked Get Pr Reactions.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "pull_number": {
      "type": "integer",
      "title": "Pull Number"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "Get Pr Reactions"
}
```

Example invocation:

```json
{
  "tool": "get_pr_reactions",
  "args": {}
}
```

## get_pr_review_comment_reactions

Fetch reactions for a pull request review comment.  Schema: comment_id*:integer, full_name*:string, page:integer=1, per_page:integer=30

Invoking Get Pr Review Comment Reactions…
Invoked Get Pr Review Comment Reactions.

Tool metadata:
- name: get_pr_review_comment_reactions
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Pr Review Comment Reactions…
- invoked: Invoked Get Pr Review Comment Reactions.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "comment_id": {
      "type": "integer",
      "title": "Comment Id"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "comment_id"
  ],
  "title": "Get Pr Review Comment Reactions"
}
```

Example invocation:

```json
{
  "tool": "get_pr_review_comment_reactions",
  "args": {}
}
```

## get_rate_limit

Get Rate Limit. Signature: get_rate_limit() -> Dict[str, Any].

Invoking Get Rate Limit…
Invoked Get Rate Limit.

Tool metadata:
- name: get_rate_limit
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Rate Limit…
- invoked: Invoked Get Rate Limit.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": true,
  "title": "Get Rate Limit"
}
```

Example invocation:

```json
{
  "tool": "get_rate_limit",
  "args": {}
}
```

## get_render_deploy

Fetch a specific deploy for a service.  Schema: deploy_id*:string, service_id*:string

Invoking Get Render Deploy…
Invoked Get Render Deploy.

Tool metadata:
- name: get_render_deploy
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Render Deploy…
- invoked: Invoked Get Render Deploy.

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "deploy_id": {
      "type": "string",
      "title": "Deploy Id",
      "description": "Render deploy id (example: dpl-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Get Render Deploy"
}
```

Example invocation:

```json
{
  "tool": "get_render_deploy",
  "args": {}
}
```

## get_render_logs

Fetch logs for a Render resource.  Schema: end_time:any, limit:integer=200, resource_id*:string, resource_type*:string, start_time:any

Invoking Get Render Logs…
Invoked Get Render Logs.

Tool metadata:
- name: get_render_logs
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Render Logs…
- invoked: Invoked Get Render Logs.

Parameters:
- end_time (string | null; optional)
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
- start_time (string | null; optional)
  Optional ISO8601 timestamp for the start of a log query window.
  Examples: '2026-01-14T12:34:56Z'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "resource_type": {
      "type": "string",
      "title": "Resource Type",
      "description": "Render log resource type (service or job).",
      "examples": [
        "service",
        "job"
      ]
    },
    "resource_id": {
      "type": "string",
      "title": "Resource Id",
      "description": "Render log resource id corresponding to resource_type."
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Start Time",
      "description": "Optional ISO8601 timestamp for the start of a log query window.",
      "examples": [
        "2026-01-14T12:34:56Z"
      ]
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "End Time",
      "description": "Optional ISO8601 timestamp for the end of a log query window.",
      "examples": [
        "2026-01-14T13:34:56Z"
      ]
    },
    "limit": {
      "type": "integer",
      "default": 200,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "resource_type",
    "resource_id"
  ],
  "title": "Get Render Logs"
}
```

Example invocation:

```json
{
  "tool": "get_render_logs",
  "args": {}
}
```

## get_render_service

Fetch a Render service by id.  Schema: service_id*:string

Invoking Get Render Service…
Invoked Get Render Service.

Tool metadata:
- name: get_render_service
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Render Service…
- invoked: Invoked Get Render Service.

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id"
  ],
  "title": "Get Render Service"
}
```

Example invocation:

```json
{
  "tool": "get_render_service",
  "args": {}
}
```

## get_repo_dashboard

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

Raises:
ToolPreflightValidationError: If the branch/path combination fails server-side normalization.

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

Invoking Get Repo Dashboard…
Invoked Get Repo Dashboard.

Tool metadata:
- name: get_repo_dashboard
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Repo Dashboard…
- invoked: Invoked Get Repo Dashboard.

Parameters:
- branch (string | null; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Get Repo Dashboard"
}
```

Example invocation:

```json
{
  "tool": "get_repo_dashboard",
  "args": {}
}
```

## get_repo_dashboard_graphql

Return a compact dashboard using GraphQL as a fallback.  Schema: branch:any, full_name*:string

Invoking Get Repo Dashboard Graphql…
Invoked Get Repo Dashboard Graphql.

Tool metadata:
- name: get_repo_dashboard_graphql
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Repo Dashboard Graphql…
- invoked: Invoked Get Repo Dashboard Graphql.

Parameters:
- branch (string | null; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Get Repo Dashboard Graphql"
}
```

Example invocation:

```json
{
  "tool": "get_repo_dashboard_graphql",
  "args": {}
}
```

## get_repo_defaults

Get Repo Defaults. Signature: get_repo_defaults(full_name: Optional[str] = None) -> Dict[str, Any].  Schema: full_name:any

Invoking Get Repo Defaults…
Invoked Get Repo Defaults.

Tool metadata:
- name: get_repo_defaults
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Repo Defaults…
- invoked: Invoked Get Repo Defaults.

Parameters:
- full_name (string | null; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    }
  },
  "additionalProperties": true,
  "title": "Get Repo Defaults"
}
```

Example invocation:

```json
{
  "tool": "get_repo_defaults",
  "args": {}
}
```

## get_repository

Look up repository metadata (topics, default branch, permissions).  Schema: full_name*:string

Invoking Get Repository…
Invoked Get Repository.

Tool metadata:
- name: get_repository
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Repository…
- invoked: Invoked Get Repository.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Get Repository"
}
```

Example invocation:

```json
{
  "tool": "get_repository",
  "args": {}
}
```

## get_server_config

Get Server Config. Signature: get_server_config() -> Dict[str, Any].

Invoking Get Server Config…
Invoked Get Server Config.

Tool metadata:
- name: get_server_config
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Server Config…
- invoked: Invoked Get Server Config.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": true,
  "title": "Get Server Config"
}
```

Example invocation:

```json
{
  "tool": "get_server_config",
  "args": {}
}
```

## get_user_login

Get User Login. Signature: get_user_login() -> Dict[str, Any].

Invoking Get User Login…
Invoked Get User Login.

Tool metadata:
- name: get_user_login
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get User Login…
- invoked: Invoked Get User Login.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": true,
  "title": "Get User Login"
}
```

Example invocation:

```json
{
  "tool": "get_user_login",
  "args": {}
}
```

## get_workflow_run

Retrieve a specific workflow run including timing and conclusion.  Schema: full_name*:string, run_id*:integer

Invoking Get Workflow Run…
Invoked Get Workflow Run.

Tool metadata:
- name: get_workflow_run
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Workflow Run…
- invoked: Invoked Get Workflow Run.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- run_id (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "run_id": {
      "type": "integer",
      "title": "Run Id"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "run_id"
  ],
  "title": "Get Workflow Run"
}
```

Example invocation:

```json
{
  "tool": "get_workflow_run",
  "args": {}
}
```

## get_workflow_run_overview

Summarize a GitHub Actions workflow run for CI triage.  Schema: full_name*:string, max_jobs:integer=500, run_id*:integer

This helper is read-only and safe to call before any write actions. It
aggregates run metadata, jobs (with optional pagination up to max_jobs),
failed jobs, and the longest jobs by duration to provide a single-call
summary of run status.

Invoking Get Workflow Run Overview…
Invoked Get Workflow Run Overview.

Tool metadata:
- name: get_workflow_run_overview
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Workflow Run Overview…
- invoked: Invoked Get Workflow Run Overview.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_jobs (integer; optional, default=500)
- run_id (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "run_id": {
      "type": "integer",
      "title": "Run Id"
    },
    "max_jobs": {
      "type": "integer",
      "default": 500,
      "title": "Max Jobs"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "run_id"
  ],
  "title": "Get Workflow Run Overview"
}
```

Example invocation:

```json
{
  "tool": "get_workflow_run_overview",
  "args": {}
}
```

## get_workspace_changes_summary

Summarize modified, added, deleted, renamed, and untracked files in the repo mirror.  Schema: full_name*:string, max_files:integer=200, path_prefix:any, ref:string=main

Invoking Get Workspace Changes Summary…
Invoked Get Workspace Changes Summary.

Tool metadata:
- name: get_workspace_changes_summary
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Workspace Changes Summary…
- invoked: Invoked Get Workspace Changes Summary.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- max_files (integer; optional, default=200)
- path_prefix (string | null; optional)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "path_prefix": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Path Prefix"
    },
    "max_files": {
      "type": "integer",
      "default": 200,
      "title": "Max Files"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Get Workspace Changes Summary"
}
```

Example invocation:

```json
{
  "tool": "get_workspace_changes_summary",
  "args": {}
}
```

## get_workspace_file_contents

Read a file from the persistent repo mirror (no shell).  Schema: full_name*:string, path:string=, ref:string=main

Args:
  path: Repo-relative path (POSIX-style). Must resolve inside the repo mirror.

Returns:
  A dict with keys like: exists, path, text, encoding, size_bytes.

Invoking Get Workspace File Contents…
Invoked Get Workspace File Contents.

Tool metadata:
- name: get_workspace_file_contents
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Workspace File Contents…
- invoked: Invoked Get Workspace File Contents.

Parameters:
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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "path": {
      "type": "string",
      "default": "",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Get Workspace File Contents"
}
```

Example invocation:

```json
{
  "tool": "get_workspace_file_contents",
  "args": {}
}
```

## get_workspace_files_contents

Read multiple files from the persistent repo mirror in one call.  Schema: expand_globs:boolean=True, full_name*:string, include_missing:boolean=True, max_chars_per_file:integer=20000, max_total_chars:integer=120000, paths:any, ref:string=main

This tool is optimized for examination workflows where a client wants to
inspect several files (optionally via glob patterns) without issuing many
per-file calls.

Notes:
  - All paths are repository-relative.
  - When expand_globs is true, glob patterns (e.g. "src/**/*.py") are
    expanded relative to the repo root.
  - Returned text is truncated by max_chars_per_file and max_total_chars.

Invoking Get Workspace Files Contents…
Invoked Get Workspace Files Contents.

Tool metadata:
- name: get_workspace_files_contents
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking Get Workspace Files Contents…
- invoked: Invoked Get Workspace Files Contents.

Parameters:
- expand_globs (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_missing (boolean; optional, default=True)
- max_chars_per_file (integer; optional, default=20000)
- max_total_chars (integer; optional, default=120000)
- paths (array | null; optional)
  List of repository-relative paths.
  Examples: ['README.md', 'src/app.py']
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "paths": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Paths",
      "description": "List of repository-relative paths.",
      "examples": [
        [
          "README.md",
          "src/app.py"
        ]
      ]
    },
    "expand_globs": {
      "type": "boolean",
      "default": true,
      "title": "Expand Globs"
    },
    "max_chars_per_file": {
      "type": "integer",
      "default": 20000,
      "title": "Max Chars Per File"
    },
    "max_total_chars": {
      "type": "integer",
      "default": 120000,
      "title": "Max Total Chars"
    },
    "include_missing": {
      "type": "boolean",
      "default": true,
      "title": "Include Missing"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Get Workspace Files Contents"
}
```

Example invocation:

```json
{
  "tool": "get_workspace_files_contents",
  "args": {}
}
```

## graphql_query

Graphql Query. Signature: graphql_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any].  Schema: query*:string, variables:any

Invoking Graphql Query…
Invoked Graphql Query.

Tool metadata:
- name: graphql_query
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Graphql Query…
- invoked: Invoked Graphql Query.

Parameters:
- query (string; required)
  Search query string.
  Examples: 'def main', 'import os', 'async def'
- variables (object | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "title": "Query",
      "description": "Search query string.",
      "examples": [
        "def main",
        "import os",
        "async def"
      ]
    },
    "variables": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": {}
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Variables"
    }
  },
  "additionalProperties": true,
  "required": [
    "query"
  ],
  "title": "Graphql Query"
}
```

Example invocation:

```json
{
  "tool": "graphql_query",
  "args": {}
}
```

## list_all_actions

Enumerate every available MCP tool with optional schemas.  Schema: compact:any, include_parameters:boolean=False

This helper exposes a structured catalog of all tools so clients can see
the full command surface without reading this file. It is read-only and
remains available even when write actions are disabled.

Args:
include_parameters: When ``True``, include the serialized input schema
for each tool to clarify argument names and types.
compact: When ``True`` (or when ``GITHUB_MCP_COMPACT_METADATA_DEFAULT=1`` is
set), shorten descriptions and omit tag metadata to keep responses
compact.

Invoking List All Actions…
Invoked List All Actions.

Tool metadata:
- name: list_all_actions
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List All Actions…
- invoked: Invoked List All Actions.

Parameters:
- compact (boolean | null; optional)
- include_parameters (boolean; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "include_parameters": {
      "type": "boolean",
      "default": false,
      "title": "Include Parameters"
    },
    "compact": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Compact"
    }
  },
  "additionalProperties": true,
  "title": "List All Actions"
}
```

Example invocation:

```json
{
  "tool": "list_all_actions",
  "args": {}
}
```

## list_branches

Enumerate branches for a repository with GitHub-style pagination.  Schema: full_name*:string, page:integer=1, per_page:integer=100

Invoking List Branches…
Invoked List Branches.

Tool metadata:
- name: list_branches
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Branches…
- invoked: Invoked List Branches.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "per_page": {
      "type": "integer",
      "default": 100,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "List Branches"
}
```

Example invocation:

```json
{
  "tool": "list_branches",
  "args": {}
}
```

## list_open_issues_graphql

List issues (excluding PRs) using GraphQL, with cursor-based pagination.  Schema: cursor:any, full_name*:string, per_page:integer=30, state:string=open

Invoking List Open Issues Graphql…
Invoked List Open Issues Graphql.

Tool metadata:
- name: list_open_issues_graphql
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Open Issues Graphql…
- invoked: Invoked List Open Issues Graphql.

Parameters:
- cursor (string | null; optional)
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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "state": {
      "enum": [
        "open",
        "closed",
        "all"
      ],
      "type": "string",
      "default": "open",
      "title": "State"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "cursor": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cursor",
      "description": "Pagination cursor returned by the previous call."
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "List Open Issues Graphql"
}
```

Example invocation:

```json
{
  "tool": "list_open_issues_graphql",
  "args": {}
}
```

## list_pr_changed_filenames

List Pr Changed Filenames. Signature: list_pr_changed_filenames(full_name: str, pull_number: int, per_page: int = 100, page: int = 1) -> Dict[str, Any].  Schema: full_name*:string, page:integer=1, per_page:integer=100, pull_number*:integer

Invoking List Pr Changed Filenames…
Invoked List Pr Changed Filenames.

Tool metadata:
- name: list_pr_changed_filenames
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Pr Changed Filenames…
- invoked: Invoked List Pr Changed Filenames.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "pull_number": {
      "type": "integer",
      "title": "Pull Number"
    },
    "per_page": {
      "type": "integer",
      "default": 100,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "pull_number"
  ],
  "title": "List Pr Changed Filenames"
}
```

Example invocation:

```json
{
  "tool": "list_pr_changed_filenames",
  "args": {}
}
```

## list_pull_requests

List Pull Requests. Signature: list_pull_requests(full_name: str, state: Literal['open', 'closed', 'all'] = 'open', head: Optional[str] = None, base: Optional[str] = None, per_page: int = 30, page: int = 1) -> Dict[str, Any].  Schema: base:any, full_name*:string, head:any, page:integer=1, per_page:integer=30, state:string=open

Invoking List Pull Requests…
Invoked List Pull Requests.

Tool metadata:
- name: list_pull_requests
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Pull Requests…
- invoked: Invoked List Pull Requests.

Parameters:
- base (string | null; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- head (string | null; optional)
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- state (string; optional, default='open')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "state": {
      "enum": [
        "open",
        "closed",
        "all"
      ],
      "type": "string",
      "default": "open",
      "title": "State"
    },
    "head": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Head"
    },
    "base": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Base"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "List Pull Requests"
}
```

Example invocation:

```json
{
  "tool": "list_pull_requests",
  "args": {}
}
```

## list_recent_failures

List recent failed or cancelled GitHub Actions workflow runs.  Schema: branch:any, full_name*:string, limit:integer=10

This helper composes ``list_workflow_runs`` and filters to runs whose
conclusion indicates a non-successful outcome (for example failure,
cancelled, or timed out). It is intended as a navigation helper for CI
debugging flows.

Invoking List Recent Failures…
Invoked List Recent Failures.

Tool metadata:
- name: list_recent_failures
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Recent Failures…
- invoked: Invoked List Recent Failures.

Parameters:
- branch (string | null; optional)
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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "limit": {
      "type": "integer",
      "default": 10,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "List Recent Failures"
}
```

Example invocation:

```json
{
  "tool": "list_recent_failures",
  "args": {}
}
```

## list_recent_failures_graphql

List recent workflow failures using GraphQL as a fallback.  Schema: branch:any, full_name*:string, limit:integer=10

Invoking List Recent Failures Graphql…
Invoked List Recent Failures Graphql.

Tool metadata:
- name: list_recent_failures_graphql
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Recent Failures Graphql…
- invoked: Invoked List Recent Failures Graphql.

Parameters:
- branch (string | null; optional)
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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "limit": {
      "type": "integer",
      "default": 10,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "List Recent Failures Graphql"
}
```

Example invocation:

```json
{
  "tool": "list_recent_failures_graphql",
  "args": {}
}
```

## list_recent_issues

List Recent Issues. Signature: list_recent_issues(filter: str = 'assigned', state: str = 'open', per_page: int = 30, page: int = 1) -> Dict[str, Any].  Schema: filter:string=assigned, page:integer=1, per_page:integer=30, state:string=open

Invoking List Recent Issues…
Invoked List Recent Issues.

Tool metadata:
- name: list_recent_issues
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Recent Issues…
- invoked: Invoked List Recent Issues.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "filter": {
      "type": "string",
      "default": "assigned",
      "title": "Filter"
    },
    "state": {
      "type": "string",
      "default": "open",
      "title": "State"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "title": "List Recent Issues"
}
```

Example invocation:

```json
{
  "tool": "list_recent_issues",
  "args": {}
}
```

## list_render_deploys

List deploys for a Render service.  Schema: cursor:any, limit:integer=20, service_id*:string

Invoking List Render Deploys…
Invoked List Render Deploys.

Tool metadata:
- name: list_render_deploys
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Render Deploys…
- invoked: Invoked List Render Deploys.

Parameters:
- cursor (string | null; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "cursor": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cursor",
      "description": "Pagination cursor returned by the previous call."
    },
    "limit": {
      "type": "integer",
      "default": 20,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id"
  ],
  "title": "List Render Deploys"
}
```

Example invocation:

```json
{
  "tool": "list_render_deploys",
  "args": {}
}
```

## list_render_logs

List logs for one or more Render resources.  Schema: direction:string=backward, end_time:any, host:any, instance:any, level:any, limit:integer=200, log_type:any, method:any, +6 more

This maps to Render's public /v1/logs API which requires an owner_id and one
or more resource ids.

Invoking List Render Logs…
Invoked List Render Logs.

Tool metadata:
- name: list_render_logs
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Render Logs…
- invoked: Invoked List Render Logs.

Parameters:
- direction (string; optional, default='backward')
- end_time (string | null; optional)
  Optional ISO8601 timestamp for the end of a log query window.
  Examples: '2026-01-14T13:34:56Z'
- host (string | null; optional)
- instance (string | null; optional)
- level (string | null; optional)
- limit (integer; optional, default=200)
  Maximum number of results to return.
  Examples: 20, 50, 200
- log_type (string | null; optional)
- method (string | null; optional)
- owner_id (string; required)
  Render owner id (workspace or personal owner). Use list_render_owners to discover values.
- path (string | null; optional)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- resources (array; required)
- start_time (string | null; optional)
  Optional ISO8601 timestamp for the start of a log query window.
  Examples: '2026-01-14T12:34:56Z'
- status_code (integer | null; optional)
- text (string | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "owner_id": {
      "type": "string",
      "title": "Owner Id",
      "description": "Render owner id (workspace or personal owner). Use list_render_owners to discover values."
    },
    "resources": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "title": "Resources"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Start Time",
      "description": "Optional ISO8601 timestamp for the start of a log query window.",
      "examples": [
        "2026-01-14T12:34:56Z"
      ]
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "End Time",
      "description": "Optional ISO8601 timestamp for the end of a log query window.",
      "examples": [
        "2026-01-14T13:34:56Z"
      ]
    },
    "direction": {
      "type": "string",
      "default": "backward",
      "title": "Direction"
    },
    "limit": {
      "type": "integer",
      "default": 200,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    },
    "instance": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Instance"
    },
    "host": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Host"
    },
    "level": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Level"
    },
    "method": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Method"
    },
    "status_code": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Status Code"
    },
    "path": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "text": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Text"
    },
    "log_type": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Log Type"
    }
  },
  "additionalProperties": true,
  "required": [
    "owner_id",
    "resources"
  ],
  "title": "List Render Logs"
}
```

Example invocation:

```json
{
  "tool": "list_render_logs",
  "args": {}
}
```

## list_render_owners

List Render owners (workspaces + personal owners).  Schema: cursor:any, limit:integer=20

Invoking List Render Owners…
Invoked List Render Owners.

Tool metadata:
- name: list_render_owners
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Render Owners…
- invoked: Invoked List Render Owners.

Parameters:
- cursor (string | null; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "cursor": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cursor",
      "description": "Pagination cursor returned by the previous call."
    },
    "limit": {
      "type": "integer",
      "default": 20,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "title": "List Render Owners"
}
```

Example invocation:

```json
{
  "tool": "list_render_owners",
  "args": {}
}
```

## list_render_services

List Render services (optionally filtered by owner_id).  Schema: cursor:any, limit:integer=20, owner_id:any

Invoking List Render Services…
Invoked List Render Services.

Tool metadata:
- name: list_render_services
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Render Services…
- invoked: Invoked List Render Services.

Parameters:
- cursor (string | null; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200
- owner_id (string | null; optional)
  Render owner id (workspace or personal owner). Use list_render_owners to discover values.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "owner_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Owner Id",
      "description": "Render owner id (workspace or personal owner). Use list_render_owners to discover values."
    },
    "cursor": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cursor",
      "description": "Pagination cursor returned by the previous call."
    },
    "limit": {
      "type": "integer",
      "default": 20,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "title": "List Render Services"
}
```

Example invocation:

```json
{
  "tool": "list_render_services",
  "args": {}
}
```

## list_repositories

List Repositories. Signature: list_repositories(affiliation: Optional[str] = None, visibility: Optional[str] = None, per_page: int = 30, page: int = 1) -> Dict[str, Any].  Schema: affiliation:any, page:integer=1, per_page:integer=30, visibility:any

Invoking List Repositories…
Invoked List Repositories.

Tool metadata:
- name: list_repositories
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Repositories…
- invoked: Invoked List Repositories.

Parameters:
- affiliation (string | null; optional)
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- visibility (string | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "affiliation": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Affiliation"
    },
    "visibility": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Visibility"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "title": "List Repositories"
}
```

Example invocation:

```json
{
  "tool": "list_repositories",
  "args": {}
}
```

## list_repositories_by_installation

List Repositories By Installation. Signature: list_repositories_by_installation(installation_id: int, per_page: int = 30, page: int = 1) -> Dict[str, Any].  Schema: installation_id*:integer, page:integer=1, per_page:integer=30

Invoking List Repositories By Installation…
Invoked List Repositories By Installation.

Tool metadata:
- name: list_repositories_by_installation
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Repositories By Installation…
- invoked: Invoked List Repositories By Installation.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "installation_id": {
      "type": "integer",
      "title": "Installation Id"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "installation_id"
  ],
  "title": "List Repositories By Installation"
}
```

Example invocation:

```json
{
  "tool": "list_repositories_by_installation",
  "args": {}
}
```

## list_repository_issues

List Repository Issues. Signature: list_repository_issues(full_name: str, state: str = 'open', labels: Optional[List[str]] = None, assignee: Optional[str] = None, per_page: int = 30, page: int = 1) -> Dict[str, Any].  Schema: assignee:any, full_name*:string, labels:any, page:integer=1, per_page:integer=30, state:string=open

Invoking List Repository Issues…
Invoked List Repository Issues.

Tool metadata:
- name: list_repository_issues
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Repository Issues…
- invoked: Invoked List Repository Issues.

Parameters:
- assignee (string | null; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- labels (array | null; optional)
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- state (string; optional, default='open')

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "state": {
      "type": "string",
      "default": "open",
      "title": "State"
    },
    "labels": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Labels"
    },
    "assignee": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Assignee"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "List Repository Issues"
}
```

Example invocation:

```json
{
  "tool": "list_repository_issues",
  "args": {}
}
```

## list_repository_tree

List Repository Tree. Signature: list_repository_tree(full_name: str, ref: str = 'main', path_prefix: Optional[str] = None, recursive: bool = True, max_entries: int = 1000, include_blobs: bool = True, include_trees: bool = True) -> Dict[str, Any].  Schema: full_name*:string, include_blobs:boolean=True, include_trees:boolean=True, max_entries:integer=1000, path_prefix:any, recursive:boolean=True, ref:string=main

Invoking List Repository Tree…
Invoked List Repository Tree.

Tool metadata:
- name: list_repository_tree
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Repository Tree…
- invoked: Invoked List Repository Tree.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_blobs (boolean; optional, default=True)
- include_trees (boolean; optional, default=True)
- max_entries (integer; optional, default=1000)
- path_prefix (string | null; optional)
- recursive (boolean; optional, default=True)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "path_prefix": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Path Prefix"
    },
    "recursive": {
      "type": "boolean",
      "default": true,
      "title": "Recursive"
    },
    "max_entries": {
      "type": "integer",
      "default": 1000,
      "title": "Max Entries"
    },
    "include_blobs": {
      "type": "boolean",
      "default": true,
      "title": "Include Blobs"
    },
    "include_trees": {
      "type": "boolean",
      "default": true,
      "title": "Include Trees"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "List Repository Tree"
}
```

Example invocation:

```json
{
  "tool": "list_repository_tree",
  "args": {}
}
```

## list_tools

List available MCP tools with a compact description. Full schemas are available via describe_tool (or list_all_actions with include_parameters=true).  Schema: name_prefix:any, only_read:boolean=False, only_write:boolean=False

Invoking List Tools…
Invoked List Tools.

Tool metadata:
- name: list_tools
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Tools…
- invoked: Invoked List Tools.

Parameters:
- name_prefix (string | null; optional)
- only_read (boolean; optional, default=False)
- only_write (boolean; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "only_write": {
      "type": "boolean",
      "default": false,
      "title": "Only Write"
    },
    "only_read": {
      "type": "boolean",
      "default": false,
      "title": "Only Read"
    },
    "name_prefix": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Name Prefix"
    }
  },
  "additionalProperties": true,
  "title": "List Tools"
}
```

Example invocation:

```json
{
  "tool": "list_tools",
  "args": {}
}
```

## list_workflow_run_jobs

List jobs within a workflow run, useful for troubleshooting failures.  Schema: full_name*:string, page:integer=1, per_page:integer=30, run_id*:integer

Invoking List Workflow Run Jobs…
Invoked List Workflow Run Jobs.

Tool metadata:
- name: list_workflow_run_jobs
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Workflow Run Jobs…
- invoked: Invoked List Workflow Run Jobs.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "run_id": {
      "type": "integer",
      "title": "Run Id"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "run_id"
  ],
  "title": "List Workflow Run Jobs"
}
```

Example invocation:

```json
{
  "tool": "list_workflow_run_jobs",
  "args": {}
}
```

## list_workflow_runs

List recent GitHub Actions workflow runs with optional filters.  Schema: branch:any, event:any, full_name*:string, page:integer=1, per_page:integer=30, status:any

Invoking List Workflow Runs…
Invoked List Workflow Runs.

Tool metadata:
- name: list_workflow_runs
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Workflow Runs…
- invoked: Invoked List Workflow Runs.

Parameters:
- branch (string | null; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- event (string | null; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- page (integer; optional, default=1)
  1-indexed page number for GitHub REST pagination.
  Examples: 1, 2
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100
- status (string | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "status": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Status"
    },
    "event": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Event"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "List Workflow Runs"
}
```

Example invocation:

```json
{
  "tool": "list_workflow_runs",
  "args": {}
}
```

## list_workflow_runs_graphql

List recent workflow runs using GraphQL with cursor-based pagination.  Schema: branch:any, cursor:any, full_name*:string, per_page:integer=30

Invoking List Workflow Runs Graphql…
Invoked List Workflow Runs Graphql.

Tool metadata:
- name: list_workflow_runs_graphql
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Workflow Runs Graphql…
- invoked: Invoked List Workflow Runs Graphql.

Parameters:
- branch (string | null; optional)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- cursor (string | null; optional)
  Pagination cursor returned by the previous call.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- per_page (integer; optional, default=30)
  Number of results per page for GitHub REST pagination.
  Examples: 30, 100

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "cursor": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cursor",
      "description": "Pagination cursor returned by the previous call."
    },
    "branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "List Workflow Runs Graphql"
}
```

Example invocation:

```json
{
  "tool": "list_workflow_runs_graphql",
  "args": {}
}
```

## list_workspace_files

List files in the repo mirror (workspace clone).  Schema: full_name:any, include_dirs:boolean=False, include_hidden:boolean=False, max_depth:any, max_files:any, max_results:any, path:string=, ref:string=main

Invoking List Workspace Files…
Invoked List Workspace Files.

Tool metadata:
- name: list_workspace_files
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Workspace Files…
- invoked: Invoked List Workspace Files.

Parameters:
- full_name (string | null; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_dirs (boolean; optional, default=False)
- include_hidden (boolean; optional, default=False)
- max_depth (integer | null; optional)
- max_files (integer | null; optional)
- max_results (integer | null; optional)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "path": {
      "type": "string",
      "default": "",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "max_files": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Max Files"
    },
    "max_results": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Max Results"
    },
    "max_depth": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Max Depth"
    },
    "include_hidden": {
      "type": "boolean",
      "default": false,
      "title": "Include Hidden"
    },
    "include_dirs": {
      "type": "boolean",
      "default": false,
      "title": "Include Dirs"
    }
  },
  "additionalProperties": true,
  "title": "List Workspace Files"
}
```

Example invocation:

```json
{
  "tool": "list_workspace_files",
  "args": {}
}
```

## list_write_actions

Enumerate write-capable MCP tools with optional schemas.  Schema: compact:any, include_parameters:boolean=False

Invoking List Write Actions…
Invoked List Write Actions.

Tool metadata:
- name: list_write_actions
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Write Actions…
- invoked: Invoked List Write Actions.

Parameters:
- compact (boolean | null; optional)
- include_parameters (boolean; optional, default=False)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "include_parameters": {
      "type": "boolean",
      "default": false,
      "title": "Include Parameters"
    },
    "compact": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Compact"
    }
  },
  "additionalProperties": true,
  "title": "List Write Actions"
}
```

Example invocation:

```json
{
  "tool": "list_write_actions",
  "args": {}
}
```

## list_write_tools

Describe write-capable tools exposed by this server.

This provides a concise summary without requiring a scan of the full module.

Invoking List Write Tools…
Invoked List Write Tools.

Tool metadata:
- name: list_write_tools
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 📖
- invoking: Invoking List Write Tools…
- invoked: Invoked List Write Tools.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": true,
  "title": "List Write Tools"
}
```

Example invocation:

```json
{
  "tool": "list_write_tools",
  "args": {}
}
```

## merge_pull_request

Merge Pull Request. Signature: merge_pull_request(full_name: str, number: int, merge_method: Literal['merge', 'squash', 'rebase'] = 'squash', commit_title: Optional[str] = None, commit_message: Optional[str] = None) -> Dict[str, Any].  Schema: commit_message:any, commit_title:any, full_name*:string, merge_method:string=squash, number*:integer

Invoking Merge Pull Request…
Invoked Merge Pull Request.

Tool metadata:
- name: merge_pull_request
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Merge Pull Request…
- invoked: Invoked Merge Pull Request.

Parameters:
- commit_message (string | null; optional)
- commit_title (string | null; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- merge_method (string; optional, default='squash')
- number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "number": {
      "type": "integer",
      "title": "Number"
    },
    "merge_method": {
      "enum": [
        "merge",
        "squash",
        "rebase"
      ],
      "type": "string",
      "default": "squash",
      "title": "Merge Method"
    },
    "commit_title": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Commit Title"
    },
    "commit_message": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Commit Message"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "number"
  ],
  "title": "Merge Pull Request"
}
```

Example invocation:

```json
{
  "tool": "merge_pull_request",
  "args": {}
}
```

## move_file

Move File. Signature: move_file(full_name: str, from_path: str, to_path: str, branch: str = 'main', message: Optional[str] = None) -> Dict[str, Any].  Schema: branch:string=main, from_path*:string, full_name*:string, message:any, to_path*:string

Invoking Move File…
Invoked Move File.

Tool metadata:
- name: move_file
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Move File…
- invoked: Invoked Move File.

Parameters:
- branch (string; optional, default='main')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- from_path (string; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- message (string | null; optional)
  Commit message.
  Examples: 'Refactor tool schemas'
- to_path (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "from_path": {
      "type": "string",
      "title": "From Path"
    },
    "to_path": {
      "type": "string",
      "title": "To Path"
    },
    "branch": {
      "type": "string",
      "default": "main",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "message": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Message",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "from_path",
    "to_path"
  ],
  "title": "Move File"
}
```

Example invocation:

```json
{
  "tool": "move_file",
  "args": {}
}
```

## move_workspace_paths

Move (rename) one or more workspace paths inside the repo mirror.  Schema: create_parents:boolean=True, full_name*:string, moves:any, overwrite:boolean=False, ref:string=main

Args:
  moves: list of {"src": "path", "dst": "path"}
  overwrite: if true, allow replacing an existing destination.

Invoking Move Workspace Paths…
Invoked Move Workspace Paths.

Tool metadata:
- name: move_workspace_paths
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Move Workspace Paths…
- invoked: Invoked Move Workspace Paths.

Parameters:
- create_parents (boolean; optional, default=True)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- moves (array | null; optional)
- overwrite (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "moves": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": {}
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Moves"
    },
    "overwrite": {
      "type": "boolean",
      "default": false,
      "title": "Overwrite"
    },
    "create_parents": {
      "type": "boolean",
      "default": true,
      "title": "Create Parents"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Move Workspace Paths"
}
```

Example invocation:

```json
{
  "tool": "move_workspace_paths",
  "args": {}
}
```

## open_issue_context

Return an issue plus related branches and pull requests.  Schema: full_name*:string, issue_number*:integer

Invoking Open Issue Context…
Invoked Open Issue Context.

Tool metadata:
- name: open_issue_context
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Open Issue Context…
- invoked: Invoked Open Issue Context.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "issue_number": {
      "type": "integer",
      "title": "Issue Number"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Open Issue Context"
}
```

Example invocation:

```json
{
  "tool": "open_issue_context",
  "args": {}
}
```

## open_pr_for_existing_branch

Open a pull request for an existing branch into a base branch.  Schema: base:string=main, body:any, branch*:string, draft:boolean=False, full_name*:string, title:any

This helper is intentionally idempotent: if there is already an open PR for
the same head/base pair, it will return that existing PR instead of failing
or creating a duplicate.

Invoking Open Pr For Existing Branch…
Invoked Open Pr For Existing Branch.

Tool metadata:
- name: open_pr_for_existing_branch
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Open Pr For Existing Branch…
- invoked: Invoked Open Pr For Existing Branch.

Parameters:
- base (string; optional, default='main')
- body (string | null; optional)
- branch (string; required)
  Branch name.
  Examples: 'main', 'feature/my-branch'
- draft (boolean; optional, default=False)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- title (string | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "type": "string",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "base": {
      "type": "string",
      "default": "main",
      "title": "Base"
    },
    "title": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Title"
    },
    "body": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Body"
    },
    "draft": {
      "type": "boolean",
      "default": false,
      "title": "Draft"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Open Pr For Existing Branch"
}
```

Example invocation:

```json
{
  "tool": "open_pr_for_existing_branch",
  "args": {}
}
```

## ping_extensions

Ping the MCP server extensions surface.

Invoking Ping Extensions…
Invoked Ping Extensions.

Tool metadata:
- name: ping_extensions
- visibility: public
- write_action: false
- write_allowed: true
- tags: diagnostics, meta

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Ping Extensions…
- invoked: Invoked Ping Extensions.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": true,
  "title": "Ping Extensions"
}
```

Example invocation:

```json
{
  "tool": "ping_extensions",
  "args": {}
}
```

## pr_smoke_test

Pr Smoke Test. Signature: pr_smoke_test(full_name: Optional[str] = None, base_branch: Optional[str] = None, draft: bool = True) -> Dict[str, Any].  Schema: base_branch:any, draft:boolean=True, full_name:any

Invoking Pr Smoke Test…
Invoked Pr Smoke Test.

Tool metadata:
- name: pr_smoke_test
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Pr Smoke Test…
- invoked: Invoked Pr Smoke Test.

Parameters:
- base_branch (string | null; optional)
- draft (boolean; optional, default=True)
- full_name (string | null; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "base_branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Base Branch"
    },
    "draft": {
      "type": "boolean",
      "default": true,
      "title": "Draft"
    }
  },
  "additionalProperties": true,
  "title": "Pr Smoke Test"
}
```

Example invocation:

```json
{
  "tool": "pr_smoke_test",
  "args": {}
}
```

## recent_prs_for_branch

Return recent pull requests associated with a branch, grouped by state.  Schema: branch*:string, full_name*:string, include_closed:boolean=False, per_page_closed:integer=5, per_page_open:integer=20

Invoking Recent Prs For Branch…
Invoked Recent Prs For Branch.

Tool metadata:
- name: recent_prs_for_branch
- visibility: public
- write_action: false
- write_allowed: true
- tags: github, navigation, prs, read

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Recent Prs For Branch…
- invoked: Invoked Recent Prs For Branch.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "type": "string",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "include_closed": {
      "type": "boolean",
      "default": false,
      "title": "Include Closed"
    },
    "per_page_open": {
      "type": "integer",
      "default": 20,
      "title": "Per Page Open"
    },
    "per_page_closed": {
      "type": "integer",
      "default": 5,
      "title": "Per Page Closed"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "branch"
  ],
  "title": "Recent Prs For Branch"
}
```

Example invocation:

```json
{
  "tool": "recent_prs_for_branch",
  "args": {}
}
```

## render_cancel_deploy

Render Cancel Deploy. Signature: render_cancel_deploy(service_id: str, deploy_id: str) -> Dict[str, Any].  Schema: deploy_id*:string, service_id*:string

Invoking Cancel Deploy…
Invoked Cancel Deploy.

Tool metadata:
- name: render_cancel_deploy
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🛑
- invoking: Invoking Cancel Deploy…
- invoked: Invoked Cancel Deploy.

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "deploy_id": {
      "type": "string",
      "title": "Deploy Id",
      "description": "Render deploy id (example: dpl-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Render Cancel Deploy"
}
```

Example invocation:

```json
{
  "tool": "render_cancel_deploy",
  "args": {}
}
```

## render_create_deploy

Render Create Deploy. Signature: render_create_deploy(service_id: str, clear_cache: bool = False, commit_id: Optional[str] = None, image_url: Optional[str] = None) -> Dict[str, Any].  Schema: clear_cache:boolean=False, commit_id:any, image_url:any, service_id*:string

Invoking Create Deploy…
Invoked Create Deploy.

Tool metadata:
- name: render_create_deploy
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🚀
- invoking: Invoking Create Deploy…
- invoked: Invoked Create Deploy.

Parameters:
- clear_cache (boolean; optional, default=False)
  When true, clears the build cache before deploying.
  Examples: True, False
- commit_id (string | null; optional)
  Optional git commit SHA to deploy (repo-backed services).
- image_url (string | null; optional)
  Optional container image URL to deploy (image-backed services).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "clear_cache": {
      "type": "boolean",
      "default": false,
      "title": "Clear Cache",
      "description": "When true, clears the build cache before deploying.",
      "examples": [
        true,
        false
      ]
    },
    "commit_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Commit Id",
      "description": "Optional git commit SHA to deploy (repo-backed services)."
    },
    "image_url": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Image Url",
      "description": "Optional container image URL to deploy (image-backed services)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id"
  ],
  "title": "Render Create Deploy"
}
```

Example invocation:

```json
{
  "tool": "render_create_deploy",
  "args": {}
}
```

## render_create_service

Render Create Service. Signature: render_create_service(service_spec: Dict[str, Any]) -> Dict[str, Any].  Schema: service_spec*:object

Invoking Create Service…
Invoked Create Service.

Tool metadata:
- name: render_create_service
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🧱
- invoking: Invoking Create Service…
- invoked: Invoked Create Service.

Parameters:
- service_spec (object; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_spec": {
      "type": "object",
      "additionalProperties": {},
      "title": "Service Spec"
    }
  },
  "additionalProperties": true,
  "required": [
    "service_spec"
  ],
  "title": "Render Create Service"
}
```

Example invocation:

```json
{
  "tool": "render_create_service",
  "args": {}
}
```

## render_get_deploy

Render Get Deploy. Signature: render_get_deploy(service_id: str, deploy_id: str) -> Dict[str, Any].  Schema: deploy_id*:string, service_id*:string

Invoking Get Deploy…
Invoked Get Deploy.

Tool metadata:
- name: render_get_deploy
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🟦
- invoking: Invoking Get Deploy…
- invoked: Invoked Get Deploy.

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "deploy_id": {
      "type": "string",
      "title": "Deploy Id",
      "description": "Render deploy id (example: dpl-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Render Get Deploy"
}
```

Example invocation:

```json
{
  "tool": "render_get_deploy",
  "args": {}
}
```

## render_get_logs

Render Get Logs. Signature: render_get_logs(resource_type: str, resource_id: str, start_time: Optional[str] = None, end_time: Optional[str] = None, limit: int = 200) -> Dict[str, Any].  Schema: end_time:any, limit:integer=200, resource_id*:string, resource_type*:string, start_time:any

Invoking Get Logs…
Invoked Get Logs.

Tool metadata:
- name: render_get_logs
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: render
- icon: 📜
- invoking: Invoking Get Logs…
- invoked: Invoked Get Logs.

Parameters:
- end_time (string | null; optional)
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
- start_time (string | null; optional)
  Optional ISO8601 timestamp for the start of a log query window.
  Examples: '2026-01-14T12:34:56Z'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "resource_type": {
      "type": "string",
      "title": "Resource Type",
      "description": "Render log resource type (service or job).",
      "examples": [
        "service",
        "job"
      ]
    },
    "resource_id": {
      "type": "string",
      "title": "Resource Id",
      "description": "Render log resource id corresponding to resource_type."
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Start Time",
      "description": "Optional ISO8601 timestamp for the start of a log query window.",
      "examples": [
        "2026-01-14T12:34:56Z"
      ]
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "End Time",
      "description": "Optional ISO8601 timestamp for the end of a log query window.",
      "examples": [
        "2026-01-14T13:34:56Z"
      ]
    },
    "limit": {
      "type": "integer",
      "default": 200,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "resource_type",
    "resource_id"
  ],
  "title": "Render Get Logs"
}
```

Example invocation:

```json
{
  "tool": "render_get_logs",
  "args": {}
}
```

## render_get_service

Render Get Service. Signature: render_get_service(service_id: str) -> Dict[str, Any].  Schema: service_id*:string

Invoking Get Service…
Invoked Get Service.

Tool metadata:
- name: render_get_service
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🟦
- invoking: Invoking Get Service…
- invoked: Invoked Get Service.

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id"
  ],
  "title": "Render Get Service"
}
```

Example invocation:

```json
{
  "tool": "render_get_service",
  "args": {}
}
```

## render_list_deploys

Render List Deploys. Signature: render_list_deploys(service_id: str, cursor: Optional[str] = None, limit: int = 20) -> Dict[str, Any].  Schema: cursor:any, limit:integer=20, service_id*:string

Invoking List Deploys…
Invoked List Deploys.

Tool metadata:
- name: render_list_deploys
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🟦
- invoking: Invoking List Deploys…
- invoked: Invoked List Deploys.

Parameters:
- cursor (string | null; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "cursor": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cursor",
      "description": "Pagination cursor returned by the previous call."
    },
    "limit": {
      "type": "integer",
      "default": 20,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id"
  ],
  "title": "Render List Deploys"
}
```

Example invocation:

```json
{
  "tool": "render_list_deploys",
  "args": {}
}
```

## render_list_logs

Render List Logs. Signature: render_list_logs(owner_id: str, resources: List[str], start_time: Optional[str] = None, end_time: Optional[str] = None, direction: str = 'backward', limit: int = 200, instance: Optional[str] = None, host: Optional[str] = None, level: Optional[str] = None, method: Optional[str] = None, status_code: Optional[int] = None, path: Optional[str] = None, text: Optional[str] = None, log_type: Optional[str] = None) -> Dict[str, Any].  Schema: direction:string=backward, end_time:any, host:any, instance:any, level:any, limit:integer=200, log_type:any, method:any, +6 more

Invoking List Logs…
Invoked List Logs.

Tool metadata:
- name: render_list_logs
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: render
- icon: 📜
- invoking: Invoking List Logs…
- invoked: Invoked List Logs.

Parameters:
- direction (string; optional, default='backward')
- end_time (string | null; optional)
  Optional ISO8601 timestamp for the end of a log query window.
  Examples: '2026-01-14T13:34:56Z'
- host (string | null; optional)
- instance (string | null; optional)
- level (string | null; optional)
- limit (integer; optional, default=200)
  Maximum number of results to return.
  Examples: 20, 50, 200
- log_type (string | null; optional)
- method (string | null; optional)
- owner_id (string; required)
  Render owner id (workspace or personal owner). Use list_render_owners to discover values.
- path (string | null; optional)
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- resources (array; required)
- start_time (string | null; optional)
  Optional ISO8601 timestamp for the start of a log query window.
  Examples: '2026-01-14T12:34:56Z'
- status_code (integer | null; optional)
- text (string | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "owner_id": {
      "type": "string",
      "title": "Owner Id",
      "description": "Render owner id (workspace or personal owner). Use list_render_owners to discover values."
    },
    "resources": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "title": "Resources"
    },
    "start_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Start Time",
      "description": "Optional ISO8601 timestamp for the start of a log query window.",
      "examples": [
        "2026-01-14T12:34:56Z"
      ]
    },
    "end_time": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "End Time",
      "description": "Optional ISO8601 timestamp for the end of a log query window.",
      "examples": [
        "2026-01-14T13:34:56Z"
      ]
    },
    "direction": {
      "type": "string",
      "default": "backward",
      "title": "Direction"
    },
    "limit": {
      "type": "integer",
      "default": 200,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    },
    "instance": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Instance"
    },
    "host": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Host"
    },
    "level": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Level"
    },
    "method": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Method"
    },
    "status_code": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Status Code"
    },
    "path": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "text": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Text"
    },
    "log_type": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Log Type"
    }
  },
  "additionalProperties": true,
  "required": [
    "owner_id",
    "resources"
  ],
  "title": "Render List Logs"
}
```

Example invocation:

```json
{
  "tool": "render_list_logs",
  "args": {}
}
```

## render_list_owners

Render List Owners. Signature: render_list_owners(cursor: Optional[str] = None, limit: int = 20) -> Dict[str, Any].  Schema: cursor:any, limit:integer=20

Invoking List Owners…
Invoked List Owners.

Tool metadata:
- name: render_list_owners
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🟦
- invoking: Invoking List Owners…
- invoked: Invoked List Owners.

Parameters:
- cursor (string | null; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "cursor": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cursor",
      "description": "Pagination cursor returned by the previous call."
    },
    "limit": {
      "type": "integer",
      "default": 20,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "title": "Render List Owners"
}
```

Example invocation:

```json
{
  "tool": "render_list_owners",
  "args": {}
}
```

## render_list_services

Render List Services. Signature: render_list_services(owner_id: Optional[str] = None, cursor: Optional[str] = None, limit: int = 20) -> Dict[str, Any].  Schema: cursor:any, limit:integer=20, owner_id:any

Invoking List Services…
Invoked List Services.

Tool metadata:
- name: render_list_services
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🟦
- invoking: Invoking List Services…
- invoked: Invoked List Services.

Parameters:
- cursor (string | null; optional)
  Pagination cursor returned by the previous call.
- limit (integer; optional, default=20)
  Maximum number of results to return.
  Examples: 20, 50, 200
- owner_id (string | null; optional)
  Render owner id (workspace or personal owner). Use list_render_owners to discover values.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "owner_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Owner Id",
      "description": "Render owner id (workspace or personal owner). Use list_render_owners to discover values."
    },
    "cursor": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cursor",
      "description": "Pagination cursor returned by the previous call."
    },
    "limit": {
      "type": "integer",
      "default": 20,
      "title": "Limit",
      "description": "Maximum number of results to return.",
      "examples": [
        20,
        50,
        200
      ]
    }
  },
  "additionalProperties": true,
  "title": "Render List Services"
}
```

Example invocation:

```json
{
  "tool": "render_list_services",
  "args": {}
}
```

## render_restart_service

Render Restart Service. Signature: render_restart_service(service_id: str) -> Dict[str, Any].  Schema: service_id*:string

Invoking Restart Service…
Invoked Restart Service.

Tool metadata:
- name: render_restart_service
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🔁
- invoking: Invoking Restart Service…
- invoked: Invoked Restart Service.

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id"
  ],
  "title": "Render Restart Service"
}
```

Example invocation:

```json
{
  "tool": "render_restart_service",
  "args": {}
}
```

## render_rollback_deploy

Render Rollback Deploy. Signature: render_rollback_deploy(service_id: str, deploy_id: str) -> Dict[str, Any].  Schema: deploy_id*:string, service_id*:string

Invoking Rollback Deploy…
Invoked Rollback Deploy.

Tool metadata:
- name: render_rollback_deploy
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: render
- icon: ⏪
- invoking: Invoking Rollback Deploy…
- invoked: Invoked Rollback Deploy.

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "deploy_id": {
      "type": "string",
      "title": "Deploy Id",
      "description": "Render deploy id (example: dpl-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Render Rollback Deploy"
}
```

Example invocation:

```json
{
  "tool": "render_rollback_deploy",
  "args": {}
}
```

## render_shell

Render-focused shell entry point for interacting with GitHub workspaces.  Schema: command:string=echo hello Render, command_lines:any, create_branch:any, full_name*:string, installing_dependencies:boolean=False, push_new_branch:boolean=True, ref:string=main, timeout_seconds:number=300, +2 more

This helper mirrors the Render deployment model by operating through the
server-side repo mirror. It ensures the repo mirror exists
for the default branch (or a provided ref), optionally creates a fresh
branch from that ref, and then executes the supplied shell command inside
the repo mirror.

Invoking Render Shell…
Invoked Render Shell.

Tool metadata:
- name: render_shell
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: render
- icon: 🟦
- invoking: Invoking Render Shell…
- invoked: Invoked Render Shell.

Parameters:
- command (string; optional, default='echo hello Render')
  Shell command to execute in the repo mirror (workspace clone).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (array | null; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- create_branch (string | null; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- push_new_branch (boolean; optional, default=True)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=300)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (string | null; optional)
  Working directory to run the command from. If relative, it is resolved within the repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "command": {
      "type": "string",
      "default": "echo hello Render",
      "title": "Command",
      "description": "Shell command to execute in the repo mirror (workspace clone).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ]
    },
    "command_lines": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Command Lines",
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload."
    },
    "create_branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Create Branch"
    },
    "push_new_branch": {
      "type": "boolean",
      "default": true,
      "title": "Push New Branch"
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "timeout_seconds": {
      "type": "number",
      "default": 300,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "workdir": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Workdir",
      "description": "Working directory to run the command from. If relative, it is resolved within the repo mirror.",
      "examples": [
        "",
        "src"
      ]
    },
    "use_temp_venv": {
      "type": "boolean",
      "default": true,
      "title": "Use Temp Venv"
    },
    "installing_dependencies": {
      "type": "boolean",
      "default": false,
      "title": "Installing Dependencies"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Render Shell"
}
```

Example invocation:

```json
{
  "tool": "render_shell",
  "args": {}
}
```

## replace_workspace_text

Replace text in a workspace file (single word/character or substring).  Schema: create_parents:boolean=True, full_name*:string, new:string=, occurrence:integer=1, old:string=, path:string=, ref:string=main, replace_all:boolean=False

By default, replaces the Nth occurrence (1-indexed). Use replace_all=true
to replace all occurrences.

Invoking Replace Workspace Text…
Invoked Replace Workspace Text.

Tool metadata:
- name: replace_workspace_text
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Replace Workspace Text…
- invoked: Invoked Replace Workspace Text.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "path": {
      "type": "string",
      "default": "",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "old": {
      "type": "string",
      "default": "",
      "title": "Old"
    },
    "new": {
      "type": "string",
      "default": "",
      "title": "New"
    },
    "occurrence": {
      "type": "integer",
      "default": 1,
      "title": "Occurrence"
    },
    "replace_all": {
      "type": "boolean",
      "default": false,
      "title": "Replace All"
    },
    "create_parents": {
      "type": "boolean",
      "default": true,
      "title": "Create Parents"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Replace Workspace Text"
}
```

Example invocation:

```json
{
  "tool": "replace_workspace_text",
  "args": {}
}
```

## resolve_handle

Resolve Handle. Signature: resolve_handle(full_name: str, handle: str) -> Dict[str, Any].  Schema: full_name*:string, handle*:string

Invoking Resolve Handle…
Invoked Resolve Handle.

Tool metadata:
- name: resolve_handle
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Resolve Handle…
- invoked: Invoked Resolve Handle.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- handle (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "handle": {
      "type": "string",
      "title": "Handle"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "handle"
  ],
  "title": "Resolve Handle"
}
```

Example invocation:

```json
{
  "tool": "resolve_handle",
  "args": {}
}
```

## restart_render_service

Restart a Render service.  Schema: service_id*:string

Invoking Restart Render Service…
Invoked Restart Render Service.

Tool metadata:
- name: restart_render_service
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Restart Render Service…
- invoked: Invoked Restart Render Service.

Parameters:
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id"
  ],
  "title": "Restart Render Service"
}
```

Example invocation:

```json
{
  "tool": "restart_render_service",
  "args": {}
}
```

## rollback_render_deploy

Roll back a service to the specified deploy.  Schema: deploy_id*:string, service_id*:string

Invoking Rollback Render Deploy…
Invoked Rollback Render Deploy.

Tool metadata:
- name: rollback_render_deploy
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Rollback Render Deploy…
- invoked: Invoked Rollback Render Deploy.

Parameters:
- deploy_id (string; required)
  Render deploy id (example: dpl-...).
- service_id (string; required)
  Render service id (example: srv-...).

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "service_id": {
      "type": "string",
      "title": "Service Id",
      "description": "Render service id (example: srv-...)."
    },
    "deploy_id": {
      "type": "string",
      "title": "Deploy Id",
      "description": "Render deploy id (example: dpl-...)."
    }
  },
  "additionalProperties": true,
  "required": [
    "service_id",
    "deploy_id"
  ],
  "title": "Rollback Render Deploy"
}
```

Example invocation:

```json
{
  "tool": "rollback_render_deploy",
  "args": {}
}
```

## run_command

Backward-compatible alias for :func:`terminal_command`.  Schema: command:string=pytest, command_lines:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, timeout_seconds:number=300, use_temp_venv:boolean=True, workdir:any

This exists for older MCP clients that still invoke `run_command`.

Invoking Run Command…
Invoked Run Command.

Tool metadata:
- name: run_command
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Run Command…
- invoked: Invoked Run Command.

Parameters:
- command (string; optional, default='pytest')
  Shell command to execute in the repo mirror (workspace clone).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (array | null; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=300)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (string | null; optional)
  Working directory to run the command from. If relative, it is resolved within the repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "command": {
      "type": "string",
      "default": "pytest",
      "title": "Command",
      "description": "Shell command to execute in the repo mirror (workspace clone).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ]
    },
    "command_lines": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Command Lines",
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload."
    },
    "timeout_seconds": {
      "type": "number",
      "default": 300,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "workdir": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Workdir",
      "description": "Working directory to run the command from. If relative, it is resolved within the repo mirror.",
      "examples": [
        "",
        "src"
      ]
    },
    "use_temp_venv": {
      "type": "boolean",
      "default": true,
      "title": "Use Temp Venv"
    },
    "installing_dependencies": {
      "type": "boolean",
      "default": false,
      "title": "Installing Dependencies"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Run Command"
}
```

Example invocation:

```json
{
  "tool": "run_command",
  "args": {}
}
```

## run_lint_suite

Run Lint Suite. Signature: run_lint_suite(full_name: 'str', ref: 'str' = 'main', lint_command: 'str' = 'ruff check .', timeout_seconds: 'float' = 600, workdir: 'Optional[str]' = None, use_temp_venv: 'bool' = False, installing_dependencies: 'bool' = False) -> 'Dict[str, Any]'.  Schema: full_name*:any, installing_dependencies:any=False, lint_command:any=ruff check ., ref:any=main, timeout_seconds:any=600, use_temp_venv:any=False, workdir:any

Invoking Run Lint Suite…
Invoked Run Lint Suite.

Tool metadata:
- name: run_lint_suite
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Run Lint Suite…
- invoked: Invoked Run Lint Suite.

Parameters:
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (unknown; optional, default=False)
- lint_command (unknown; optional, default='ruff check .')
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (unknown; optional, default=600)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (unknown; optional, default=False)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "lint_command": {
      "default": "ruff check .",
      "title": "Lint Command"
    },
    "timeout_seconds": {
      "default": 600,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "workdir": {
      "default": null,
      "title": "Workdir",
      "description": "Working directory to run the command from. If relative, it is resolved within the repo mirror.",
      "examples": [
        "",
        "src"
      ]
    },
    "use_temp_venv": {
      "default": false,
      "title": "Use Temp Venv"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Run Lint Suite"
}
```

Example invocation:

```json
{
  "tool": "run_lint_suite",
  "args": {}
}
```

## run_python

Run an inline Python script inside the repo mirror.  Schema: args:any, cleanup:boolean=True, filename:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, script:string=, timeout_seconds:number=300, +2 more

The script content is written to a file within the workspace mirror and executed.
The tool exists to support multi-line scripts without relying on shell-special syntax.

Invoking Run Python…
Invoked Run Python.

Tool metadata:
- name: run_python
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🐍
- invoking: Invoking Run Python…
- invoked: Invoked Run Python.

Parameters:
- args (array | null; optional)
- cleanup (boolean; optional, default=True)
- filename (string | null; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- script (string; optional, default='')
- timeout_seconds (number; optional, default=300)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (string | null; optional)
  Working directory to run the command from. If relative, it is resolved within the repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "script": {
      "type": "string",
      "default": "",
      "title": "Script"
    },
    "filename": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Filename"
    },
    "args": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Args"
    },
    "timeout_seconds": {
      "type": "number",
      "default": 300,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "workdir": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Workdir",
      "description": "Working directory to run the command from. If relative, it is resolved within the repo mirror.",
      "examples": [
        "",
        "src"
      ]
    },
    "use_temp_venv": {
      "type": "boolean",
      "default": true,
      "title": "Use Temp Venv"
    },
    "installing_dependencies": {
      "type": "boolean",
      "default": false,
      "title": "Installing Dependencies"
    },
    "cleanup": {
      "type": "boolean",
      "default": true,
      "title": "Cleanup"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Run Python"
}
```

Example invocation:

```json
{
  "tool": "run_python",
  "args": {}
}
```

## run_quality_suite

Run Quality Suite. Signature: run_quality_suite(full_name: 'str', ref: 'str' = 'main', test_command: 'str' = 'pytest -q', timeout_seconds: 'float' = 600, workdir: 'Optional[str]' = None, use_temp_venv: 'bool' = True, installing_dependencies: 'bool' = True, lint_command: 'str' = 'ruff check .', format_command: 'Optional[str]' = None, typecheck_command: 'Optional[str]' = None, security_command: 'Optional[str]' = None, preflight: 'bool' = True, fail_fast: 'bool' = True, include_raw_step_outputs: 'bool' = False, *, developer_defaults: 'bool' = True, auto_fix: 'bool' = False, gate_optional_steps: 'bool' = False) -> 'Dict[str, Any]'.  Schema: auto_fix:any=False, developer_defaults:any=True, fail_fast:any=True, format_command:any, full_name*:any, gate_optional_steps:any=False, include_raw_step_outputs:any=False, installing_dependencies:any=True, +9 more

Invoking Run Quality Suite…
Invoked Run Quality Suite.

Tool metadata:
- name: run_quality_suite
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Run Quality Suite…
- invoked: Invoked Run Quality Suite.

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
- timeout_seconds (unknown; optional, default=600)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- typecheck_command (unknown; optional)
- use_temp_venv (unknown; optional, default=True)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "test_command": {
      "default": "pytest -q",
      "title": "Test Command"
    },
    "timeout_seconds": {
      "default": 600,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "workdir": {
      "default": null,
      "title": "Workdir",
      "description": "Working directory to run the command from. If relative, it is resolved within the repo mirror.",
      "examples": [
        "",
        "src"
      ]
    },
    "use_temp_venv": {
      "default": true,
      "title": "Use Temp Venv"
    },
    "installing_dependencies": {
      "default": true,
      "title": "Installing Dependencies"
    },
    "lint_command": {
      "default": "ruff check .",
      "title": "Lint Command"
    },
    "format_command": {
      "default": null,
      "title": "Format Command"
    },
    "typecheck_command": {
      "default": null,
      "title": "Typecheck Command"
    },
    "security_command": {
      "default": null,
      "title": "Security Command"
    },
    "preflight": {
      "default": true,
      "title": "Preflight"
    },
    "fail_fast": {
      "default": true,
      "title": "Fail Fast"
    },
    "include_raw_step_outputs": {
      "default": false,
      "title": "Include Raw Step Outputs"
    },
    "developer_defaults": {
      "default": true,
      "title": "Developer Defaults"
    },
    "auto_fix": {
      "default": false,
      "title": "Auto Fix"
    },
    "gate_optional_steps": {
      "default": false,
      "title": "Gate Optional Steps"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Run Quality Suite"
}
```

Example invocation:

```json
{
  "tool": "run_quality_suite",
  "args": {}
}
```

## run_shell

Backward-compatible alias for :func:`terminal_command`.  Schema: command:string=pytest, command_lines:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, timeout_seconds:number=300, use_temp_venv:boolean=True, workdir:any

Some integrations refer to the workspace command runner as `run_shell`.

Invoking Run Shell…
Invoked Run Shell.

Tool metadata:
- name: run_shell
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Run Shell…
- invoked: Invoked Run Shell.

Parameters:
- command (string; optional, default='pytest')
  Shell command to execute in the repo mirror (workspace clone).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (array | null; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=300)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (string | null; optional)
  Working directory to run the command from. If relative, it is resolved within the repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "command": {
      "type": "string",
      "default": "pytest",
      "title": "Command",
      "description": "Shell command to execute in the repo mirror (workspace clone).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ]
    },
    "command_lines": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Command Lines",
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload."
    },
    "timeout_seconds": {
      "type": "number",
      "default": 300,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "workdir": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Workdir",
      "description": "Working directory to run the command from. If relative, it is resolved within the repo mirror.",
      "examples": [
        "",
        "src"
      ]
    },
    "use_temp_venv": {
      "type": "boolean",
      "default": true,
      "title": "Use Temp Venv"
    },
    "installing_dependencies": {
      "type": "boolean",
      "default": false,
      "title": "Installing Dependencies"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Run Shell"
}
```

Example invocation:

```json
{
  "tool": "run_shell",
  "args": {}
}
```

## run_terminal_commands

Backward-compatible alias for :func:`terminal_command`.  Schema: command:string=pytest, command_lines:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, timeout_seconds:number=300, use_temp_venv:boolean=True, workdir:any

This name appears in some older controller-side tool catalogs.

Invoking Run Terminal Commands…
Invoked Run Terminal Commands.

Tool metadata:
- name: run_terminal_commands
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Run Terminal Commands…
- invoked: Invoked Run Terminal Commands.

Parameters:
- command (string; optional, default='pytest')
  Shell command to execute in the repo mirror (workspace clone).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (array | null; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=300)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (string | null; optional)
  Working directory to run the command from. If relative, it is resolved within the repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "command": {
      "type": "string",
      "default": "pytest",
      "title": "Command",
      "description": "Shell command to execute in the repo mirror (workspace clone).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ]
    },
    "command_lines": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Command Lines",
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload."
    },
    "timeout_seconds": {
      "type": "number",
      "default": 300,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "workdir": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Workdir",
      "description": "Working directory to run the command from. If relative, it is resolved within the repo mirror.",
      "examples": [
        "",
        "src"
      ]
    },
    "use_temp_venv": {
      "type": "boolean",
      "default": true,
      "title": "Use Temp Venv"
    },
    "installing_dependencies": {
      "type": "boolean",
      "default": false,
      "title": "Installing Dependencies"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Run Terminal Commands"
}
```

Example invocation:

```json
{
  "tool": "run_terminal_commands",
  "args": {}
}
```

## run_tests

Run Tests. Signature: run_tests(full_name: 'str', ref: 'str' = 'main', test_command: 'str' = 'pytest', timeout_seconds: 'float' = 600, workdir: 'Optional[str]' = None, use_temp_venv: 'bool' = False, installing_dependencies: 'bool' = False) -> 'Dict[str, Any]'.  Schema: full_name*:any, installing_dependencies:any=False, ref:any=main, test_command:any=pytest, timeout_seconds:any=600, use_temp_venv:any=False, workdir:any

Invoking Run Tests…
Invoked Run Tests.

Tool metadata:
- name: run_tests
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Run Tests…
- invoked: Invoked Run Tests.

Parameters:
- full_name (unknown; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (unknown; optional, default=False)
- ref (unknown; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- test_command (unknown; optional, default='pytest')
- timeout_seconds (unknown; optional, default=600)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (unknown; optional, default=False)
- workdir (unknown; optional)
  Working directory to run the command from. If relative, it is resolved within the repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "test_command": {
      "default": "pytest",
      "title": "Test Command"
    },
    "timeout_seconds": {
      "default": 600,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "workdir": {
      "default": null,
      "title": "Workdir",
      "description": "Working directory to run the command from. If relative, it is resolved within the repo mirror.",
      "examples": [
        "",
        "src"
      ]
    },
    "use_temp_venv": {
      "default": false,
      "title": "Use Temp Venv"
    },
    "installing_dependencies": {
      "default": false,
      "title": "Installing Dependencies"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Run Tests"
}
```

Example invocation:

```json
{
  "tool": "run_tests",
  "args": {}
}
```

## search

Search. Signature: search(query: str, search_type: Literal['code', 'repositories', 'issues', 'commits', 'users'] = 'code', per_page: int = 30, page: int = 1, sort: Optional[str] = None, order: Optional[Literal['asc', 'desc']] = None) -> Dict[str, Any].  Schema: order:any, page:integer=1, per_page:integer=30, query*:string, search_type:string=code, sort:any

Invoking Search…
Invoked Search.

Tool metadata:
- name: search
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Search…
- invoked: Invoked Search.

Parameters:
- order (string | null; optional)
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
- sort (string | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "title": "Query",
      "description": "Search query string.",
      "examples": [
        "def main",
        "import os",
        "async def"
      ]
    },
    "search_type": {
      "enum": [
        "code",
        "repositories",
        "issues",
        "commits",
        "users"
      ],
      "type": "string",
      "default": "code",
      "title": "Search Type"
    },
    "per_page": {
      "type": "integer",
      "default": 30,
      "title": "Per Page",
      "description": "Number of results per page for GitHub REST pagination.",
      "examples": [
        30,
        100
      ]
    },
    "page": {
      "type": "integer",
      "default": 1,
      "title": "Page",
      "description": "1-indexed page number for GitHub REST pagination.",
      "examples": [
        1,
        2
      ]
    },
    "sort": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Sort"
    },
    "order": {
      "anyOf": [
        {
          "enum": [
            "asc",
            "desc"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Order"
    }
  },
  "additionalProperties": true,
  "required": [
    "query"
  ],
  "title": "Search"
}
```

Example invocation:

```json
{
  "tool": "search",
  "args": {}
}
```

## search_workspace

Search text files in the repo mirror (workspace clone) (bounded, no shell).  Schema: case_sensitive:boolean=False, full_name:any, include_hidden:boolean=False, max_file_bytes:any, max_results:any, path:string=, query:string=, ref:string=main, +1 more

Behavior for `query`:
- When regex=true, `query` is treated as a Python regular expression.
- Otherwise `query` is treated as a literal substring match.
- Results can be bounded via max_results and files can be bounded via
  max_file_bytes to keep searches responsive on large repositories.

Invoking Search Workspace…
Invoked Search Workspace.

Tool metadata:
- name: search_workspace
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Search Workspace…
- invoked: Invoked Search Workspace.

Parameters:
- case_sensitive (boolean; optional, default=False)
- full_name (string | null; optional)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- include_hidden (boolean; optional, default=False)
- max_file_bytes (integer | null; optional)
- max_results (integer | null; optional)
- path (string; optional, default='')
  Repository-relative path (POSIX-style).
  Examples: 'README.md', 'src/app.py'
- query (string; optional, default='')
  Search query string.
  Examples: 'def main', 'import os', 'async def'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- regex (boolean | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "query": {
      "type": "string",
      "default": "",
      "title": "Query",
      "description": "Search query string.",
      "examples": [
        "def main",
        "import os",
        "async def"
      ]
    },
    "path": {
      "type": "string",
      "default": "",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "case_sensitive": {
      "type": "boolean",
      "default": false,
      "title": "Case Sensitive"
    },
    "max_results": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Max Results"
    },
    "regex": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Regex"
    },
    "max_file_bytes": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Max File Bytes"
    },
    "include_hidden": {
      "type": "boolean",
      "default": false,
      "title": "Include Hidden"
    }
  },
  "additionalProperties": true,
  "title": "Search Workspace"
}
```

Example invocation:

```json
{
  "tool": "search_workspace",
  "args": {}
}
```

## set_workspace_file_contents

Replace a workspace file's contents by writing the full file text.  Schema: content:string=, create_parents:boolean=True, full_name*:string, path:string=, ref:string=main

This is a good fit for repo-mirror edits when you want to replace the full
contents of a file without relying on unified-diff patch application.

Invoking Set Workspace File Contents…
Invoked Set Workspace File Contents.

Tool metadata:
- name: set_workspace_file_contents
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Set Workspace File Contents…
- invoked: Invoked Set Workspace File Contents.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "path": {
      "type": "string",
      "default": "",
      "title": "Path",
      "description": "Repository-relative path (POSIX-style).",
      "examples": [
        "README.md",
        "src/app.py"
      ]
    },
    "content": {
      "type": "string",
      "default": "",
      "title": "Content"
    },
    "create_parents": {
      "type": "boolean",
      "default": true,
      "title": "Create Parents"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Set Workspace File Contents"
}
```

Example invocation:

```json
{
  "tool": "set_workspace_file_contents",
  "args": {}
}
```

## terminal_command

Run a shell command inside the repo mirror and return its result.  Schema: command:string=pytest, command_lines:any, full_name*:string, installing_dependencies:boolean=False, ref:string=main, timeout_seconds:number=300, use_temp_venv:boolean=True, workdir:any

This supports tests, linters, and project scripts that need the real working
tree.

Execution model:

- The command runs within the server-side repo mirror (a persistent git
  working copy).
- If ``use_temp_venv=true`` (default), the server creates an ephemeral
  virtualenv for the duration of the command.
- If ``installing_dependencies=true`` and ``use_temp_venv=true``, the tool
  will run a best-effort `pip install -r dev-requirements.txt` before
  executing the command.

The repo mirror persists across calls so file edits and git state are
preserved until explicitly reset.

Invoking Terminal Command…
Invoked Terminal Command.

Tool metadata:
- name: terminal_command
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🖥️
- invoking: Invoking Terminal Command…
- invoked: Invoked Terminal Command.

Parameters:
- command (string; optional, default='pytest')
  Shell command to execute in the repo mirror (workspace clone).
  Examples: 'pytest', 'python -m ruff check .'
- command_lines (array | null; optional)
  Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload.
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- installing_dependencies (boolean; optional, default=False)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- timeout_seconds (number; optional, default=300)
  Timeout for the operation in seconds.
  Examples: 60, 300, 600
- use_temp_venv (boolean; optional, default=True)
- workdir (string | null; optional)
  Working directory to run the command from. If relative, it is resolved within the repo mirror.
  Examples: '', 'src'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "command": {
      "type": "string",
      "default": "pytest",
      "title": "Command",
      "description": "Shell command to execute in the repo mirror (workspace clone).",
      "examples": [
        "pytest",
        "python -m ruff check ."
      ]
    },
    "command_lines": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Command Lines",
      "description": "Optional list of shell command lines. When provided, lines are joined with newlines and executed as a single command payload."
    },
    "timeout_seconds": {
      "type": "number",
      "default": 300,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "workdir": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Workdir",
      "description": "Working directory to run the command from. If relative, it is resolved within the repo mirror.",
      "examples": [
        "",
        "src"
      ]
    },
    "use_temp_venv": {
      "type": "boolean",
      "default": true,
      "title": "Use Temp Venv"
    },
    "installing_dependencies": {
      "type": "boolean",
      "default": false,
      "title": "Installing Dependencies"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Terminal Command"
}
```

Example invocation:

```json
{
  "tool": "terminal_command",
  "args": {}
}
```

## trigger_and_wait_for_workflow

Trigger a workflow and block until it completes or hits timeout.  Schema: full_name*:string, inputs:any, poll_interval_seconds:integer=10, ref*:string, timeout_seconds:integer=900, workflow*:string

Invoking Trigger And Wait For Workflow…
Invoked Trigger And Wait For Workflow.

Tool metadata:
- name: trigger_and_wait_for_workflow
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Trigger And Wait For Workflow…
- invoked: Invoked Trigger And Wait For Workflow.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- inputs (object | null; optional)
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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "workflow": {
      "type": "string",
      "title": "Workflow"
    },
    "ref": {
      "type": "string",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "inputs": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": {}
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Inputs"
    },
    "timeout_seconds": {
      "type": "integer",
      "default": 900,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "poll_interval_seconds": {
      "type": "integer",
      "default": 10,
      "title": "Poll Interval Seconds"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "workflow",
    "ref"
  ],
  "title": "Trigger And Wait For Workflow"
}
```

Example invocation:

```json
{
  "tool": "trigger_and_wait_for_workflow",
  "args": {}
}
```

## trigger_workflow_dispatch

Trigger a workflow dispatch event on the given ref.  Schema: full_name*:string, inputs:any, ref*:string, workflow*:string

Args:
full_name: "owner/repo" string.
workflow: Workflow file name or ID (e.g. "ci.yml" or a numeric ID).
ref: Git ref (branch, tag, or SHA) to run the workflow on.
inputs: Optional input payload for workflows that declare inputs.

Invoking Trigger Workflow Dispatch…
Invoked Trigger Workflow Dispatch.

Tool metadata:
- name: trigger_workflow_dispatch
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Trigger Workflow Dispatch…
- invoked: Invoked Trigger Workflow Dispatch.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- inputs (object | null; optional)
- ref (string; required)
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'
- workflow (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "workflow": {
      "type": "string",
      "title": "Workflow"
    },
    "ref": {
      "type": "string",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "inputs": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": {}
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Inputs"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "workflow",
    "ref"
  ],
  "title": "Trigger Workflow Dispatch"
}
```

Example invocation:

```json
{
  "tool": "trigger_workflow_dispatch",
  "args": {}
}
```

## update_file_from_workspace

Update a single file in a GitHub repository from the persistent workspace checkout. This pairs with workspace editing tools (for example, terminal_command) to modify a file and then write it back to the branch.  Schema: branch*:any, full_name*:any, message*:any, target_path*:any, workspace_path*:any

Invoking Update File From Workspace…
Invoked Update File From Workspace.

Tool metadata:
- name: update_file_from_workspace
- visibility: public
- write_action: true
- write_allowed: true
- tags: files, github, write

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Update File From Workspace…
- invoked: Invoked Update File From Workspace.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "workspace_path": {
      "title": "Workspace Path"
    },
    "target_path": {
      "title": "Target Path"
    },
    "branch": {
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "message": {
      "title": "Message",
      "description": "Commit message.",
      "examples": [
        "Refactor tool schemas"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "workspace_path",
    "target_path",
    "branch",
    "message"
  ],
  "title": "Update File From Workspace"
}
```

Example invocation:

```json
{
  "tool": "update_file_from_workspace",
  "args": {}
}
```

## update_files_and_open_pr

Commit multiple files, verify each, then open a PR in one call.  Schema: base_branch:string=main, body:any, draft:boolean=False, files*:array, full_name*:string, new_branch:any, title*:string

Invoking Update Files And Open Pr…
Invoked Update Files And Open Pr.

Tool metadata:
- name: update_files_and_open_pr
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Update Files And Open Pr…
- invoked: Invoked Update Files And Open Pr.

Parameters:
- base_branch (string; optional, default='main')
- body (string | null; optional)
- draft (boolean; optional, default=False)
- files (array; required)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- new_branch (string | null; optional)
  Name of the branch to create.
  Examples: 'simplify-tool-schemas'
- title (string; required)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "title": {
      "type": "string",
      "title": "Title"
    },
    "files": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": {}
      },
      "title": "Files"
    },
    "base_branch": {
      "type": "string",
      "default": "main",
      "title": "Base Branch"
    },
    "new_branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "New Branch",
      "description": "Name of the branch to create.",
      "examples": [
        "simplify-tool-schemas"
      ]
    },
    "body": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Body"
    },
    "draft": {
      "type": "boolean",
      "default": false,
      "title": "Draft"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "title",
    "files"
  ],
  "title": "Update Files And Open Pr"
}
```

Example invocation:

```json
{
  "tool": "update_files_and_open_pr",
  "args": {}
}
```

## update_issue

Update fields on an existing GitHub issue.  Schema: assignees:any, body:any, full_name*:string, issue_number*:integer, labels:any, state:any, title:any

Invoking Update Issue…
Invoked Update Issue.

Tool metadata:
- name: update_issue
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Update Issue…
- invoked: Invoked Update Issue.

Parameters:
- assignees (array | null; optional)
- body (string | null; optional)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- issue_number (integer; required)
- labels (array | null; optional)
- state (string | null; optional)
- title (string | null; optional)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "issue_number": {
      "type": "integer",
      "title": "Issue Number"
    },
    "title": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Title"
    },
    "body": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Body"
    },
    "state": {
      "anyOf": [
        {
          "enum": [
            "open",
            "closed"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "State"
    },
    "labels": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Labels"
    },
    "assignees": {
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Assignees"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "issue_number"
  ],
  "title": "Update Issue"
}
```

Example invocation:

```json
{
  "tool": "update_issue",
  "args": {}
}
```

## validate_environment

Check GitHub-related environment settings and report problems.

Invoking Validate Environment…
Invoked Validate Environment.

Tool metadata:
- name: validate_environment
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Validate Environment…
- invoked: Invoked Validate Environment.

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": true,
  "title": "Validate Environment"
}
```

Example invocation:

```json
{
  "tool": "validate_environment",
  "args": {}
}
```

## wait_for_workflow_run

Poll a workflow run until completion or timeout.  Schema: full_name*:string, poll_interval_seconds:integer=10, run_id*:integer, timeout_seconds:integer=900

Invoking Wait For Workflow Run…
Invoked Wait For Workflow Run.

Tool metadata:
- name: wait_for_workflow_run
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: github
- icon: 🔧
- invoking: Invoking Wait For Workflow Run…
- invoked: Invoked Wait For Workflow Run.

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
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "run_id": {
      "type": "integer",
      "title": "Run Id"
    },
    "timeout_seconds": {
      "type": "integer",
      "default": 900,
      "title": "Timeout Seconds",
      "description": "Timeout for the operation in seconds.",
      "examples": [
        60,
        300,
        600
      ]
    },
    "poll_interval_seconds": {
      "type": "integer",
      "default": 10,
      "title": "Poll Interval Seconds"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name",
    "run_id"
  ],
  "title": "Wait For Workflow Run"
}
```

Example invocation:

```json
{
  "tool": "wait_for_workflow_run",
  "args": {}
}
```

## workspace_create_branch

Create a branch using the repo mirror (workspace clone), optionally pushing to origin.  Schema: base_ref:string=main, full_name*:string, new_branch:string=, push:boolean=True

This exists because some direct GitHub-API branch-creation calls can be unavailable in some environments.

Invoking Workspace Create Branch…
Invoked Workspace Create Branch.

Tool metadata:
- name: workspace_create_branch
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🧩
- invoking: Invoking Workspace Create Branch…
- invoked: Invoked Workspace Create Branch.

Parameters:
- base_ref (string; optional, default='main')
  Base ref used as the starting point (branch/tag/SHA).
  Examples: 'main'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- new_branch (string; optional, default='')
  Name of the branch to create.
  Examples: 'simplify-tool-schemas'
- push (boolean; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "base_ref": {
      "type": "string",
      "default": "main",
      "title": "Base Ref",
      "description": "Base ref used as the starting point (branch/tag/SHA).",
      "examples": [
        "main"
      ]
    },
    "new_branch": {
      "type": "string",
      "default": "",
      "title": "New Branch",
      "description": "Name of the branch to create.",
      "examples": [
        "simplify-tool-schemas"
      ]
    },
    "push": {
      "type": "boolean",
      "default": true,
      "title": "Push"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Workspace Create Branch"
}
```

Example invocation:

```json
{
  "tool": "workspace_create_branch",
  "args": {}
}
```

## workspace_delete_branch

Delete a non-default branch using the repo mirror (workspace clone).  Schema: branch:string=, full_name*:string

This is the workspace counterpart to branch-creation helpers and is intended
for closing out ephemeral feature branches once their work has been merged.

Invoking Workspace Delete Branch…
Invoked Workspace Delete Branch.

Tool metadata:
- name: workspace_delete_branch
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🧩
- invoking: Invoking Workspace Delete Branch…
- invoked: Invoked Workspace Delete Branch.

Parameters:
- branch (string; optional, default='')
  Branch name.
  Examples: 'main', 'feature/my-branch'
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "type": "string",
      "default": "",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Workspace Delete Branch"
}
```

Example invocation:

```json
{
  "tool": "workspace_delete_branch",
  "args": {}
}
```

## workspace_self_heal_branch

Detect a mangled repo mirror branch and recover to a fresh branch.  Schema: base_ref:string=main, branch:string=, delete_mangled_branch:boolean=True, discard_uncommitted_changes:boolean=True, dry_run:boolean=False, enumerate_repo:boolean=True, full_name*:string, new_branch:any, +1 more

This tool targets cases where a repo mirror (workspace clone) becomes inconsistent (wrong
branch checked out, merge/rebase state, conflicts, etc.). When healing, it:

1) Diagnoses the repo mirror for ``branch``.
2) Optionally deletes the mangled branch (remote + best-effort local).
3) Resets the base branch repo mirror (default: ``main``).
4) Creates + pushes a new fresh branch.
5) Ensures a clean repo mirror for the new branch.
6) Optionally returns a small repo snapshot to rebuild context.

Returns plain-language step logs for UI rendering.

Invoking Workspace Self Heal Branch…
Invoked Workspace Self Heal Branch.

Tool metadata:
- name: workspace_self_heal_branch
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🧩
- invoking: Invoking Workspace Self Heal Branch…
- invoked: Invoked Workspace Self Heal Branch.

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
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- new_branch (string | null; optional)
  Name of the branch to create.
  Examples: 'simplify-tool-schemas'
- reset_base (boolean; optional, default=True)

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "branch": {
      "type": "string",
      "default": "",
      "title": "Branch",
      "description": "Branch name.",
      "examples": [
        "main",
        "feature/my-branch"
      ]
    },
    "base_ref": {
      "type": "string",
      "default": "main",
      "title": "Base Ref",
      "description": "Base ref used as the starting point (branch/tag/SHA).",
      "examples": [
        "main"
      ]
    },
    "new_branch": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "New Branch",
      "description": "Name of the branch to create.",
      "examples": [
        "simplify-tool-schemas"
      ]
    },
    "discard_uncommitted_changes": {
      "type": "boolean",
      "default": true,
      "title": "Discard Uncommitted Changes"
    },
    "delete_mangled_branch": {
      "type": "boolean",
      "default": true,
      "title": "Delete Mangled Branch"
    },
    "reset_base": {
      "type": "boolean",
      "default": true,
      "title": "Reset Base"
    },
    "enumerate_repo": {
      "type": "boolean",
      "default": true,
      "title": "Enumerate Repo"
    },
    "dry_run": {
      "type": "boolean",
      "default": false,
      "title": "Dry Run"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Workspace Self Heal Branch"
}
```

Example invocation:

```json
{
  "tool": "workspace_self_heal_branch",
  "args": {}
}
```

## workspace_sync_bidirectional

Sync repo mirror changes to the remote and refresh local state from GitHub.  Schema: add_all:boolean=True, commit_message:string=Sync workspace changes, discard_local_changes:boolean=False, full_name*:string, push:boolean=True, ref:string=main

Invoking Workspace Sync Bidirectional…
Invoked Workspace Sync Bidirectional.

Tool metadata:
- name: workspace_sync_bidirectional
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🧩
- invoking: Invoking Workspace Sync Bidirectional…
- invoked: Invoked Workspace Sync Bidirectional.

Parameters:
- add_all (boolean; optional, default=True)
- commit_message (string; optional, default='Sync workspace changes')
- discard_local_changes (boolean; optional, default=False)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- push (boolean; optional, default=True)
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "commit_message": {
      "type": "string",
      "default": "Sync workspace changes",
      "title": "Commit Message"
    },
    "add_all": {
      "type": "boolean",
      "default": true,
      "title": "Add All"
    },
    "push": {
      "type": "boolean",
      "default": true,
      "title": "Push"
    },
    "discard_local_changes": {
      "type": "boolean",
      "default": false,
      "title": "Discard Local Changes"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Workspace Sync Bidirectional"
}
```

Example invocation:

```json
{
  "tool": "workspace_sync_bidirectional",
  "args": {}
}
```

## workspace_sync_status

Report how a repo mirror (workspace clone) differs from its remote branch.  Schema: full_name*:string, ref:string=main

Invoking Workspace Sync Status…
Invoked Workspace Sync Status.

Tool metadata:
- name: workspace_sync_status
- visibility: public
- write_action: false
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🧩
- invoking: Invoking Workspace Sync Status…
- invoked: Invoked Workspace Sync Status.

Parameters:
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: False
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Workspace Sync Status"
}
```

Example invocation:

```json
{
  "tool": "workspace_sync_status",
  "args": {}
}
```

## workspace_sync_to_remote

Reset a repo mirror (workspace clone) to match the remote branch.  Schema: discard_local_changes:boolean=False, full_name*:string, ref:string=main

Invoking Workspace Sync To Remote…
Invoked Workspace Sync To Remote.

Tool metadata:
- name: workspace_sync_to_remote
- visibility: public
- write_action: true
- write_allowed: true

UI hints (optional):
- group: workspace
- icon: 🧩
- invoking: Invoking Workspace Sync To Remote…
- invoked: Invoked Workspace Sync To Remote.

Parameters:
- discard_local_changes (boolean; optional, default=False)
- full_name (string; required)
  GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.
  Examples: 'octocat/Hello-World'
- ref (string; optional, default='main')
  Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.
  Examples: 'main', 'develop', 'feature/my-branch'

Runtime notes:
  - Tool calls are logged with a per-invocation call_id and may include a schema hash.
  - Internal log-only keys prefixed with '__log_' are filtered from client responses.
  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.

Returns:
  A JSON-serializable value defined by the tool implementation.

Metadata:
- visibility: public
- write_action: True
- write_allowed: True
- write_enabled: True
- write_auto_approved: True
- approval_required: False

Input schema:

```json
{
  "type": "object",
  "properties": {
    "full_name": {
      "type": "string",
      "title": "Full Name",
      "description": "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's controller repository.",
      "examples": [
        "octocat/Hello-World"
      ]
    },
    "ref": {
      "type": "string",
      "default": "main",
      "title": "Ref",
      "description": "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. Defaults to 'main' when available.",
      "examples": [
        "main",
        "develop",
        "feature/my-branch"
      ]
    },
    "discard_local_changes": {
      "type": "boolean",
      "default": false,
      "title": "Discard Local Changes"
    }
  },
  "additionalProperties": true,
  "required": [
    "full_name"
  ],
  "title": "Workspace Sync To Remote"
}
```

Example invocation:

```json
{
  "tool": "workspace_sync_to_remote",
  "args": {}
}
```
