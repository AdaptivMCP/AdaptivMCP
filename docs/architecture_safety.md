# Architecture and safety

This document describes the current safety posture of the Adaptiv GitHub MCP server.

The code is the source of truth. If anything in this document diverges from runtime behavior, update the document.

## Write gating (auto-approval)

Write actions are classified in the tool registry (`write_action: true`).

The environment variable `GITHUB_MCP_WRITE_ALLOWED` controls whether write actions are auto-approved.

- When true: write tools are auto-approved.
- When false: the tool surface remains available, but some clients may prompt or gate before invoking write tools.

Tool listings expose `approval_required` so clients can implement consistent gating if desired.
