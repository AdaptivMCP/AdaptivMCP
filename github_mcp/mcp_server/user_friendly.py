"""Developer-friendly summaries for MCP tool results.

This module formats tool outputs for two audiences:
1) Humans in ChatGPT (clear, short summaries and next steps)
2) Automation (raw, machine-readable payload stays intact)

When a tool returns a dict payload, we add:
- controller_log: short list[str] intended for UI display
- summary: {title, bullets, next_steps}
- user_message: multiline string for UIs that prefer a single message

We do not alter authorization. We only format.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping


@dataclass(frozen=True)
class ToolSummary:
    title: str
    bullets: List[str]
    next_steps: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "bullets": list(self.bullets),
            "next_steps": list(self.next_steps),
        }


def _clean_lines(*values: Any) -> List[str]:
    out: List[str] = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, list):
            for item in v:
                s = str(item).strip()
                if s:
                    out.append(s)
            continue
        s = str(v).strip()
        if s:
            out.append(s)
    return out


def build_success_summary(tool_name: str, result: Mapping[str, Any]) -> ToolSummary:
    title = f"{tool_name}: completed"
    bullets: List[str] = []
    next_steps: List[str] = []

    if tool_name in {"terminal_command", "render_shell", "run_command"}:
        cmd = str(result.get("command_input") or result.get("command") or "").strip()
        res = result.get("result") if isinstance(result.get("result"), dict) else {}
        exit_code = res.get("exit_code") if isinstance(res, dict) else None
        timed_out = bool(res.get("timed_out")) if isinstance(res, dict) else False
        stdout = (res.get("stdout") if isinstance(res, dict) else "") or ""
        stderr = (res.get("stderr") if isinstance(res, dict) else "") or ""

        title = f"{tool_name}: command finished"
        if cmd:
            bullets.append(f"Command: {cmd}")
        if exit_code is not None:
            bullets.append(f"Exit code: {exit_code}")
        if timed_out:
            bullets.append("Timed out: true")
            next_steps.append("Increase timeout_seconds or reduce the command scope.")

        if stderr.strip() and exit_code not in (0, None):
            bullets.append("stderr: present")
            next_steps.append("Review stderr and re-run with a narrower command if needed.")
        elif stdout.strip():
            bullets.append("stdout: present")

        dep = result.get("dependency_hint")
        if isinstance(dep, dict) and dep.get("missing_module"):
            bullets.append(f"Missing module: {dep.get('missing_module')}")
            next_steps.append("Re-run with installing_dependencies=true (or install the missing module).")

    elif tool_name == "list_render_logs":
        title = "Render logs: fetched"
        count = result.get("log_count")
        if isinstance(count, int):
            bullets.append(f"Entries: {count}")
        bullets.append("Raw payload is available under `logs`.")

    # Prefer any existing controller_log already provided by the tool.
    existing = result.get("controller_log")
    if isinstance(existing, list) and existing:
        bullets = _clean_lines(existing)

    return ToolSummary(title=title, bullets=bullets[:12], next_steps=next_steps[:8])


def attach_user_facing_fields(tool_name: str, payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload

    out: Dict[str, Any] = dict(payload)
    summary = build_success_summary(tool_name, out)

    # controller_log is the most important UI-facing field.
    if not isinstance(out.get("controller_log"), list) or not out.get("controller_log"):
        out["controller_log"] = summary.bullets

    out.setdefault("summary", summary.to_dict())

    # Always provide a clean multiline message for ChatGPT UI.
    msg_lines = [summary.title] + [f"- {b}" for b in summary.bullets[:6]]
    if summary.next_steps:
        msg_lines.append("Next steps:")
        msg_lines.extend([f"- {s}" for s in summary.next_steps[:4]])
    out["user_message"] = "\n".join(msg_lines)

    return out


def attach_error_user_facing_fields(tool_name: str, payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload

    out: Dict[str, Any] = dict(payload)
    err = out.get("error") if isinstance(out.get("error"), Mapping) else {}

    title = f"{tool_name}: failed"
    message = str(err.get("message") or out.get("user_message") or "Unknown error").strip()
    code = str(err.get("code") or "").strip()
    hint = str(err.get("hint") or "").strip()

    bullets = _clean_lines(message, f"code: {code}" if code else None)
    next_steps = _clean_lines(hint)

    out["summary"] = ToolSummary(title=title, bullets=bullets[:12], next_steps=next_steps[:8]).to_dict()
    out["controller_log"] = bullets[:12]

    msg_lines = [title] + [f"- {b}" for b in bullets[:6]]
    if hint:
        msg_lines.append("Next steps:")
        msg_lines.append(f"- {hint}")
    out["user_message"] = "\n".join(msg_lines)

    return out
