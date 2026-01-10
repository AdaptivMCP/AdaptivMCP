"""User-facing summaries for MCP tool results.

This module formats tool outputs for two audiences:
1) Humans in ChatGPT or similar UIs (compact summaries and next steps)
2) Developers/automation (stable machine-readable payloads)

The tool payload itself should remain machine-readable. Any human-facing
summaries are attached under a single `ui` field to avoid polluting the
top-level response shape.

The `ui` field is optional and has the shape:
  ui: {title: str, bullets: list[str], next_steps: list[str], message: str}

Policy:
- Do not remove or mutate machine-readable fields.
- Do not introduce secrets into UI fields.
- Keep UI fields compact and single-line per bullet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional


def _single_line(value: str) -> str:
    value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(value.split()).strip()


def _preview_text(value: str) -> str:
    return _single_line(value)


def _safe_str(value: Any) -> str:
    try:
        return str(value)
    except Exception:  # pragma: no cover
        return repr(value)


def _bounded_lines(lines: List[str]) -> List[str]:
    # Normalize per-line whitespace and drop empty lines.
    return [_preview_text(line) for line in lines if line.strip()]


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

    def to_ui(self) -> Dict[str, Any]:
        msg_lines = [self.title] + [f"- {b}" for b in self.bullets]
        if self.next_steps:
            msg_lines.append("Next steps:")
            msg_lines.extend([f"- {s}" for s in self.next_steps])
        return {
            "title": self.title,
            "bullets": list(self.bullets),
            "next_steps": list(self.next_steps),
            "message": "\n".join(msg_lines),
        }


def _strip_legacy_ui_fields(payload: Dict[str, Any]) -> None:
    """Remove legacy top-level UI fields from a tool payload in-place."""

    payload.pop("controller_log", None)
    payload.pop("user_message", None)

    summary = payload.get("summary")
    if isinstance(summary, Mapping) and {"title", "bullets", "next_steps"}.issubset(summary.keys()):
        payload.pop("summary", None)


def _ui_from_legacy_fields(
    tool_name: str,
    *,
    controller_log: Any,
    summary: Any,
    user_message: Any,
) -> Optional[Dict[str, Any]]:
    """Convert legacy top-level UI fields into the new `ui` mapping."""

    if isinstance(summary, Mapping) and {"title", "bullets", "next_steps"}.issubset(summary.keys()):
        title = _safe_str(summary.get("title") or f"{tool_name}: completed").strip()
        bullets = _bounded_lines(_clean_lines(summary.get("bullets") or []))
        next_steps = _bounded_lines(_clean_lines(summary.get("next_steps") or []))
        return ToolSummary(title=title, bullets=bullets, next_steps=next_steps).to_ui()

    if isinstance(controller_log, list) and controller_log:
        bullets = _bounded_lines(_clean_lines(controller_log))
        if bullets:
            return ToolSummary(
                title=f"{tool_name}: completed",
                bullets=bullets,
                next_steps=[],
            ).to_ui()

    if isinstance(user_message, str) and user_message.strip():
        msg = user_message.strip()
        # Keep it simple: treat each line after the first as a bullet.
        lines = [line.strip() for line in msg.splitlines() if line.strip()]
        if not lines:
            return None
        title = lines[0]
        bullets = _bounded_lines(lines[1:])
        return ToolSummary(title=title, bullets=bullets, next_steps=[]).to_ui()

    return None


def _text_stats(text: str) -> tuple[int, int]:
    # (chars, lines)
    if not text:
        return (0, 0)
    return (len(text), text.count("\n") + 1)


def build_success_summary(tool_name: str, result: Mapping[str, Any]) -> ToolSummary:
    title = f"{tool_name}: completed"
    bullets: List[str] = []
    next_steps: List[str] = []

    # Envelope shape: prefer `data` when present.
    data = result.get("data") if isinstance(result.get("data"), Mapping) else result

    # Command-style tools: avoid dumping full command/stdout/stderr into UI.
    if tool_name.endswith("terminal_command") or tool_name.endswith("render_shell"):
        cmd = _safe_str(data.get("command_input") or data.get("command") or "").strip()
        res = data.get("result") if isinstance(data.get("result"), dict) else {}

        exit_code = res.get("exit_code") if isinstance(res, dict) else None
        timed_out = bool(res.get("timed_out")) if isinstance(res, dict) else False
        stdout = (_safe_str(res.get("stdout")) if isinstance(res, dict) else "") or ""
        stderr = (_safe_str(res.get("stderr")) if isinstance(res, dict) else "") or ""

        title = f"{tool_name}: command finished"
        if cmd:
            bullets.append(f"Command: {_preview_text(cmd)}")

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

        dep = data.get("dependency_hint")
        if isinstance(dep, dict) and dep.get("missing_module"):
            bullets.append(f"Missing module: {_safe_str(dep.get('missing_module'))}")
            next_steps.append(
                "Re-run with installing_dependencies=true (or install the missing module)."
            )

    return ToolSummary(
        title=title,
        bullets=_bounded_lines(bullets),
        next_steps=_bounded_lines(next_steps),
    )


def attach_user_facing_fields(tool_name: str, payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload

    out: Dict[str, Any] = dict(payload)

    # If the tool already provided a UI payload, keep it but remove legacy noise.
    existing_ui = out.get("ui")
    if isinstance(existing_ui, Mapping) and existing_ui:
        _strip_legacy_ui_fields(out)
        return out

    legacy_ui = _ui_from_legacy_fields(
        tool_name,
        controller_log=out.get("controller_log"),
        summary=out.get("summary"),
        user_message=out.get("user_message"),
    )

    _strip_legacy_ui_fields(out)

    if legacy_ui is not None:
        out["ui"] = legacy_ui
        return out

    summary = build_success_summary(tool_name, out)
    out["ui"] = summary.to_ui()
    return out


def attach_error_user_facing_fields(tool_name: str, payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload

    out: Dict[str, Any] = dict(payload)

    existing_ui = out.get("ui")
    if isinstance(existing_ui, Mapping) and existing_ui:
        _strip_legacy_ui_fields(out)
        return out

    legacy_ui = _ui_from_legacy_fields(
        tool_name,
        controller_log=out.get("controller_log"),
        summary=out.get("summary"),
        user_message=out.get("user_message"),
    )

    _strip_legacy_ui_fields(out)
    err = out.get("error") if isinstance(out.get("error"), Mapping) else {}

    title = f"{tool_name}: failed"
    message = _safe_str(err.get("message") or "Unknown error").strip()
    code = _safe_str(err.get("code") or "").strip()
    category = _safe_str(err.get("category") or "").strip()
    retryable = err.get("retryable")
    critical = err.get("critical")
    hint = _safe_str(err.get("hint") or "").strip()
    incident = _safe_str(err.get("incident_id") or "").strip()

    bullets = _clean_lines(_preview_text(message))
    if code:
        bullets.append(f"code: {_preview_text(code)}")
    if category:
        bullets.append(f"category: {_preview_text(category)}")
    if retryable is not None:
        bullets.append(f"retryable: {'yes' if retryable else 'no'}")
    if critical is not None:
        bullets.append(f"critical: {'yes' if critical else 'no'}")
    if incident:
        bullets.append(f"incident: {_preview_text(incident)}")

    next_steps = _clean_lines(_preview_text(hint)) if hint else []

    summary = ToolSummary(
        title=title,
        bullets=_bounded_lines(bullets),
        next_steps=_bounded_lines(next_steps),
    )

    # Prefer the structured error summary, but fall back to legacy UI when the
    # error payload is missing key fields.
    if summary.bullets or hint:
        out["ui"] = summary.to_ui()
    elif legacy_ui is not None:
        out["ui"] = legacy_ui
    else:
        out["ui"] = summary.to_ui()
    return out
