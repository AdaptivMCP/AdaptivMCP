# Architecture and safety

This document describes the current safety posture of the Adaptiv GitHub MCP server.

The code is the source of truth. If anything in this document diverges from runtime behavior, update the document.

## Write actions

Write actions are classified in the tool registry (`write_action: true`).
The server does not enforce hard blocks on write tools; clients decide if they
need user confirmation before invoking them.
