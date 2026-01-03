"""Developer-friendly summaries for MCP tool results.

This module formats tool outputs for two audiences:
1) Humans in ChatGPT (clear, compact summaries and next steps)
2) Developers/automation (raw machine-readable payload remains intact)

When a tool returns a mapping payload, we add:
- controller_log: list[str] intended for UI display (compact)
- summary: {title, bullets, next_steps}
- user_message: multiline string for UIs that prefer a single message

Policy:
- Do not remove or mutate machine-readable fields.
- Do not introduce secrets into UI fields.
- Keep UI fields bounded (length + line count).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping


_UI_MAX_LINES = 12
_UI_MAX_CHARS_PER_LINE = 180
_UI_MAX_TOTAL_CHARS = 1200


def _single_line(value: str) -> str:
    value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(value.split()).strip()


def _preview_text(value: str, *, max_chars: int = _UI_MAX_CHARS_PER_LINE) -> str:
    s = _single_line(value)
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 1)] + "…"


def _safe_str(value: Any) -> str:
    try:
        return str(value)
    except Exception:  # pragma: no cover
        return repr(value)


def _bounded_lines(lines: List[str]) -> List[str]:
    # Truncate per-line and cap line count.
    trimmed = [_preview_text(line) for line in lines if line.strip()]
    trimmed = trimmed[:_UI_MAX_LINES]

    # Cap total chars.
    total = 0
    out: List[str] = []
    for line in trimmed:
        if total + len(line) > _UI_MAX_TOTAL_CHARS:
            break
        out.append(line)
        total += len(line)
    return out


def _clean_lines(*values: Any) -> List[str]:
    out: List[str] = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, list):
            for item in v:
                s = _safe_str(item).strip()
                if s:
                    out.append(_single_line(s))
            continue
        s = _safe_str(v).strip()
        if s:
            out.append(_single_line(s))
    return out


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


def _text_stats(text: str) -> tuple[int, int]:
    # (chars, lines)
    if not text:
        return (0, 0)
    return (len(text), text.count("\n") + 1)


def build_success_summary(tool_name: str, result: Mapping[str, Any]) -> ToolSummary:
    title = f"{tool_name}: completed"
    bullets: List[str] = []
    next_steps: List[str] = []

    # Command-style tools: avoid dumping full command/stdout/stderr into UI.
    if tool_name in {"terminal_command", "render_shell", "run_command"}:
        cmd = _safe_str(result.get("command_input") or result.get("command") or "").strip()
        res = result.get("result") if isinstance(result.get("result"), dict) else {}

        exit_code = res.get("exit_code") if isinstance(res, dict) else None
        timed_out = bool(res.get("timed_out")) if isinstance(res, dict) else False
        stdout = (_safe_str(res.get("stdout")) if isinstance(res, dict) else "") or ""
        stderr = (_safe_str(res.get("stderr")) if isinstance(res, dict) else "") or ""

        title = f"{tool_name}: command finished"
        if cmd:
            bullets.append(f"Command: {_preview_text(cmd)}")
            if len(_single_line(cmd)) > _UI_MAX_CHARS_PER_LINE:
                bullets.append(f"Command length: {len(cmd)} chars")

        if exit_code is not None:
            bullets.append(f"Exit code: {exit_code}")
        if timed_out:
            bullets.append("Timed out: true")
            next_steps.append("Increase timeout_seconds or reduce the command scope.")

        out_chars, out_lines = _text_stats(stdout)
        err_chars, err_lines = _text_stats(stderr)
        if out_chars:
            bullets.append(f"stdout: {out_chars} chars / {out_lines} lines")
        if err_chars:
            bullets.append(f"stderr: {err_chars} chars / {err_lines} lines")
            if exit_code not in (0, None):
                bullets.append(f"stderr preview: {_preview_text(stderr)}")

        dep = result.get("dependency_hint")
        if isinstance(dep, dict) and dep.get("missing_module"):
            bullets.append(f"Missing module: {_safe_str(dep.get('missing_module'))}")
            next_steps.append("Re-run with installing_dependencies=true (or install the missing module).")

    elif tool_name == "list_render_logs":
        title = "Render logs: fetched"
        count = result.get("log_count")
        if isinstance(count, int):
            bullets.append(f"Entries: {count}")
        bullets.append("Raw payload is available under `logs`.")

    # Prefer any existing controller_log already provided by the tool, but keep it bounded.
    existing = result.get("controller_log")
    if isinstance(existing, list) and existing:
        existing_lines = _bounded_lines(_clean_lines(existing))
        # If the tool-provided log is empty after bounding, fall back.
        if existing_lines:
            bullets = existing_lines

    return ToolSummary(title=title, bullets=_bounded_lines(bullets), next_steps=_bounded_lines(next_steps))


def attach_user_facing_fields(tool_name: str, payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload

    out: Dict[str, Any] = dict(payload)
    summary = build_success_summary(tool_name, out)

    # controller_log is the primary UI field.
    out["controller_log"] = summary.bullets
    out.setdefault("summary", summary.to_dict())

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
    message = _safe_str(err.get("message") or out.get("user_message") or "Unknown error").strip()
    code = _safe_str(err.get("code") or "").strip()
    hint = _safe_str(err.get("hint") or "").strip()
    incident = _safe_str(err.get("incident_id") or "").strip()

    bullets = _clean_lines(_preview_text(message))
    if code:
        bullets.append(f"code: {_preview_text(code)}")
    if incident:
        bullets.append(f"incident: {_preview_text(incident)}")

    next_steps = _clean_lines(_preview_text(hint)) if hint else []

    summary = ToolSummary(title=title, bullets=_bounded_lines(bullets), next_steps=_bounded_lines(next_steps))

    out["summary"] = summary.to_dict()
    out["controller_log"] = summary.bullets

    msg_lines = [title] + [f"- {b}" for b in summary.bullets[:6]]
    if hint:
        msg_lines.append("Next steps:")
        msg_lines.append(f"- {_preview_text(hint)}")
    out["user_message"] = "\n".join(msg_lines)

    return out
