"""Optional helpers to summarize tool payloads for humans.

These helpers are not applied automatically to tool results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping


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
    if tool_name in {"terminal_command", "render_shell"}:
        cmd = _safe_str(result.get("command_input") or result.get("command") or "").strip()
        res = result.get("result") if isinstance(result.get("result"), dict) else {}

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

        dep = result.get("dependency_hint")
        if isinstance(dep, dict) and dep.get("missing_module"):
            bullets.append(f"Missing module: {_safe_str(dep.get('missing_module'))}")
            next_steps.append(
                "Re-run with installing_dependencies=true (or install the missing module)."
            )

    # Prefer any existing controller_log already provided by the tool, but keep it bounded.
    existing = result.get("controller_log")
    if isinstance(existing, list) and existing:
        existing_lines = _bounded_lines(_clean_lines(existing))
        # If the tool-provided log is empty after bounding, fall back.
        if existing_lines:
            bullets = existing_lines

    return ToolSummary(
        title=title,
        bullets=_bounded_lines(bullets),
        next_steps=_bounded_lines(next_steps),
    )
