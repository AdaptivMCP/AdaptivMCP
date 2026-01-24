from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedToolCall:
    tool_name: str
    args: dict[str, Any]
    channel: str
    start: int
    end: int


_FENCED_BLOCK_RE = re.compile(
    r"```(?P<lang>[a-zA-Z0-9_\-]*)\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)


_FILE_BLOCK_LANGS = {"file", "files"}


def extract_file_blocks_from_text(
    texts: Iterable[tuple[str, str | None]],
    *,
    max_blocks: int = 50,
    max_block_chars: int = 2_000_000,
) -> dict[str, str]:
    """Extract non-JSON fenced blocks that represent whole-file content.

    This is designed to pair with /llm/execute for runtimes that can't use
    structured tool-calling and where embedding a whole file as a JSON string
    is unwieldy.

    Supported block form:

      ```file
      path: relative/path/to/file.py
      name: optional_alias
      <raw file contents...>
      ```

    Rules:
      - The first contiguous set of header lines may include `path:` and/or
        `name:` (case-insensitive). The first non-header line begins content.
      - Content is returned verbatim (minus the outer fences).
      - The returned mapping is keyed by both `path` and `name` (if present).
    """

    blocks: dict[str, str] = {}
    count = 0

    for _channel, text in texts:
        if not text:
            continue

        for match in _FENCED_BLOCK_RE.finditer(text):
            if count >= max_blocks:
                return blocks

            lang = (match.group("lang") or "").strip().lower()
            if lang not in _FILE_BLOCK_LANGS:
                continue

            body = match.group("body") or ""
            if not body:
                continue

            if len(body) > max_block_chars:
                # Skip excessively large blocks to avoid memory abuse.
                continue

            # Parse header lines.
            path: str | None = None
            name: str | None = None
            lines = body.splitlines()
            content_start = 0
            for i, raw in enumerate(lines):
                line = raw.strip()
                if not line:
                    # Allow a blank line between headers and content.
                    content_start = i + 1
                    break

                m = re.match(r"^(path|name)\s*:\s*(.+)\s*$", line, flags=re.IGNORECASE)
                if not m:
                    content_start = i
                    break
                key = (m.group(1) or "").strip().lower()
                value = (m.group(2) or "").strip()
                if key == "path" and value:
                    path = value
                elif key == "name" and value:
                    name = value
                content_start = i + 1

            content = "\n".join(lines[content_start:])

            # Ignore empty payloads.
            if not content and content_start >= len(lines):
                continue

            if path:
                blocks[path] = content
            if name:
                blocks[name] = content

            count += 1

    return blocks


_BLOCK_REF_RE = re.compile(r"^\s*@(?P<kind>file|block)\s*:\s*(?P<key>.+?)\s*$", re.I)


def resolve_block_references(value: Any, blocks: dict[str, str]) -> Any:
    """Recursively replace block reference sentinels with extracted content.

    Supported reference forms:
      - "@file:<path>" or "@block:<name>" in any string field
      - {"$file": "<path>"} or {"$block": "<name>"} as a dict value

    If a reference cannot be resolved, the original value is returned.
    """

    if not blocks:
        return value

    if isinstance(value, str):
        m = _BLOCK_REF_RE.match(value)
        if not m:
            return value
        key = (m.group("key") or "").strip()
        if not key:
            return value
        return blocks.get(key, value)

    if isinstance(value, list):
        return [resolve_block_references(v, blocks) for v in value]

    if isinstance(value, dict):
        # Single-key dict sentinel form.
        if len(value) == 1:
            if "$file" in value and isinstance(value.get("$file"), str):
                k = str(value["$file"]).strip()
                return blocks.get(k, value)
            if "$block" in value and isinstance(value.get("$block"), str):
                k = str(value["$block"]).strip()
                return blocks.get(k, value)

        return {k: resolve_block_references(v, blocks) for k, v in value.items()}

    return value


def _coerce_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    if stripped[0] not in {"{", "["}:
        return value
    try:
        return json.loads(stripped)
    except Exception:
        return value


def _normalize_call_object(obj: Any) -> list[tuple[str, dict[str, Any]]]:
    """Normalize a JSON-ish object into (tool_name, args) pairs."""

    if obj is None:
        return []

    if isinstance(obj, list):
        out: list[tuple[str, dict[str, Any]]] = []
        for entry in obj:
            out.extend(_normalize_call_object(entry))
        return out

    if not isinstance(obj, dict):
        return []

    # OpenAI-ish wrapper: {"tool_calls": [{"function": {"name": ..., "arguments": "{...}"}}]}
    tool_calls = obj.get("tool_calls")
    if isinstance(tool_calls, list):
        out: list[tuple[str, dict[str, Any]]] = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            fn = call.get("function")
            if isinstance(fn, dict):
                name = fn.get("name")
                if not name:
                    continue
                raw_args = fn.get("arguments", {})
                coerced = _coerce_json(raw_args)
                args = coerced if isinstance(coerced, dict) else {}
                out.append((str(name), args))
                continue
            out.extend(_normalize_call_object(call))
        return out

    # Common shapes.
    name = obj.get("tool") or obj.get("tool_name") or obj.get("name")
    if not name and isinstance(obj.get("function"), dict):
        fn = obj.get("function")
        name = fn.get("name")
        raw_args = fn.get("arguments", {})
        coerced = _coerce_json(raw_args)
        args = coerced if isinstance(coerced, dict) else {}
        return [(str(name), args)] if name else []

    if not name:
        return []

    raw_args: Any = (
        obj.get("args")
        if "args" in obj
        else obj.get("arguments")
        if "arguments" in obj
        else obj.get("parameters")
        if "parameters" in obj
        else obj.get("input")
        if "input" in obj
        else obj.get("kwargs")
        if "kwargs" in obj
        else {}
    )

    coerced = _coerce_json(raw_args)
    args = coerced if isinstance(coerced, dict) else {}
    return [(str(name), args)]


def extract_tool_calls_from_text(
    texts: Iterable[tuple[str, str | None]],
    *,
    max_calls: int = 20,
) -> list[ParsedToolCall]:
    """Extract tool calls from LLM text.

    This helper exists for runtimes that cannot use structured tool-calling.
    It scans fenced code blocks (```...```) and attempts to parse JSON payloads
    that describe tool invocations.

    Supported payload shapes inside the fenced block:
      - {"tool": "name", "args": {...}}
      - {"tool_name": "name", "arguments": {...}}
      - {"name": "name", "parameters": {...}}
      - {"tool_calls": [{"function": {"name": "...", "arguments": "{...}"}}]}
      - A JSON list of any of the above

    Only JSON-like fenced blocks are considered to avoid accidental execution.
    """

    calls: list[ParsedToolCall] = []

    for channel, text in texts:
        if not text:
            continue

        for match in _FENCED_BLOCK_RE.finditer(text):
            if len(calls) >= max_calls:
                return calls

            lang = (match.group("lang") or "").strip().lower()
            body = (match.group("body") or "").strip()
            if not body:
                continue

            # Only consider likely-JSON blocks.
            if lang and lang not in {
                "tool",
                "tools",
                "mcp",
                "tool_call",
                "toolcall",
                "action",
                "json",
            }:
                continue
            if body[0] not in {"{", "["}:
                continue

            try:
                parsed = json.loads(body)
            except Exception:
                continue

            for tool_name, args in _normalize_call_object(parsed):
                if len(calls) >= max_calls:
                    return calls
                calls.append(
                    ParsedToolCall(
                        tool_name=tool_name,
                        args=args,
                        channel=channel,
                        start=match.start(),
                        end=match.end(),
                    )
                )

    return calls
