# Terminology and glossary

This repository uses a small number of terms with specific meanings. These
definitions are intended to be stable across documentation, tool descriptions,
and code comments.

The code is the authoritative reference. If runtime behavior differs from the
definitions below, update this document.

Protocol

MCP (Model Context Protocol)
  A protocol for exposing tools and resources to model-driven clients. This
  server exposes MCP tools over an SSE transport endpoint.

Tool
  A named operation exposed via MCP. Tools accept a JSON-compatible argument
  object and return a JSON-compatible result.

Tool output
  The payload returned to the MCP client. Tool outputs are distinct from
  provider logs.

Provider logs
  Operator-facing logs emitted by the server runtime (for example Render logs).
  Provider logs are optimized for human scanning and correlation.

GitHub working models

Repo mirror
  A persistent, server-side git working copy used by workspace tools. The repo
  mirror is created/reused via `ensure_workspace_clone`. Workspace file tools
  and command execution operate on this working copy.

Live GitHub state
  The remote repository state on GitHub. The repo mirror does not automatically
  reflect live GitHub state; the remote branch reflects updates only after you push.

Workspace tool
  A tool that operates on the repo mirror (filesystem + git). Workspace tools
  enable file edits, command execution, commits, and pushes.

GitHub API tool
  A tool that operates directly against GitHub's remote state using the REST or
  GraphQL APIs (issues, PRs, workflows, contents, dashboards).

Request context

Request context
  A structured set of correlation fields attached to logs and (sometimes) tool
  results. The server tracks:
  - request_id: per HTTP request
  - session_id, message_id: per MCP session/message (when provided)
  - idempotency_key: client-provided key for dedupe across retries
  - chatgpt metadata: safe OpenAI headers for connector correlation

Output normalization

Tool result envelope
  An optional normalization layer that adds a consistent `ok` and `status`
  surface to mapping (dict-like) tool results.

Response shaping
  An optional, client-facing result shaping layer (primarily for ChatGPT-hosted
  connectors) that ensures stable envelopes and bounds payload sizes.

