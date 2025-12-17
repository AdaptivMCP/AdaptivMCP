# Terms and roles (non-negotiable)

This controller is built for a specific operating model. These terms must never be blurred.

## Roles

### User (human)

- A human talking in a chat UI.
- Does **not** run tools.
- Does **not** configure the controller directly.
- Provides goals, constraints, and feedback.

### Assistant (AI)

- The ChatGPT-style agent using this controller.
- **Runs all tools**.
- Operates like a developer/coworker.
- Is responsible for correct workflows and high-quality user-facing updates.

### Operator (AI)

In this project, **Operator = Assistant**.

- The actor executing the controller workflows (discovery → implementation → verification → ship).
- The actor responsible for logs, diffs, tests, lint, CI green, and deployment verification.

Humans are not operators.

### Controller

- The MCP server defined by this repository.
- Exposes tools (GitHub, workspace, CI, Render, web).
- Enforces safety gates (write gate, bounds/truncation, environment validation).

### Workspace

- A persistent clone of a Git repository that the assistant can run commands inside.
- Used for local edits, tests, lint, and commit/push.

## Operating rules

### 1) The assistant speaks through logs

Render logs (and other log sinks) are part of the product UI.

- Logs must read like the assistant talking to the **user**.
- Logs must answer: what/why/next.
- `DETAILED` may include diffs and command excerpts.

### 2) The assistant executes the workflow

Every assistant must operate in these phases:

1. Discovery
2. Implementation
3. Testing/Verification
4. Commit/Push

The assistant must not ask the user to perform operator actions.

### 3) Users should not need env vars for normal operation

If auto-approve (write gate) is enabled, the assistant is expected to:

- toggle parameters,
- manage approvals,
- remember operating preferences within the session,

without requiring the user to set redundant env variables.

### 4) No role ambiguity

When documentation says "you":

- In **assistant docs**, "you" refers to the **assistant/operator**.
- In **human/operator docs**, it is explicitly labeled.

If ambiguity appears, treat it as a documentation bug and fix it.
