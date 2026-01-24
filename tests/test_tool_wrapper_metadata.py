from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any


def _get_tool_annotations(tool_obj: Any) -> Mapping[str, Any] | None:
    ann = getattr(tool_obj, "annotations", None)
    if isinstance(ann, Mapping):
        return ann
    if isinstance(tool_obj, Mapping):
        ann2 = tool_obj.get("annotations")
        if isinstance(ann2, Mapping):
            return ann2
    meta = getattr(tool_obj, "meta", None)
    if isinstance(meta, Mapping):
        ann3 = meta.get("annotations")
        if isinstance(ann3, Mapping):
            return ann3
    return None


def _normalize_input_schema(tool_obj: Any) -> Mapping[str, Any] | None:
    # Import lazily to avoid import cycles during test collection.
    from github_mcp.mcp_server.schemas import _normalize_input_schema as _norm

    return _norm(tool_obj)


def test_all_registered_tools_have_docstring_metadata_schema_and_signature() -> None:
    """Regression: ensure every tool (old + new) is properly wrapped.

    This checks that the @mcp_tool wrapper:
    - attaches a FastMCP tool object to `__mcp_tool__`
    - stamps a developer-oriented docstring containing tool metadata
    - exposes a JSON-schema-like input schema on the tool object
    - preserves a sensible signature (inspectable) for the wrapper
    - attaches UI annotations (readOnlyHint/destructiveHint/openWorldHint)
    """

    import main  # noqa: F401
    from github_mcp.server import _REGISTERED_MCP_TOOLS

    assert _REGISTERED_MCP_TOOLS, "Expected at least one registered tool."

    failures: list[str] = []

    for tool_obj, func in _REGISTERED_MCP_TOOLS:
        # The registry stores the wrapper callable as `func`.
        name = (
            getattr(tool_obj, "name", None)
            or getattr(func, "__mcp_tool_name__", None)
            or getattr(func, "__name__", None)
        )
        if not name:
            failures.append("<unnamed tool>")
            continue
        name = str(name)

        # 1) Wrapper is linked to tool object.
        if getattr(func, "__mcp_tool__", None) is None:
            failures.append(f"{name}: missing func.__mcp_tool__")
        if getattr(func, "__mcp_tool__", None) is not tool_obj:
            failures.append(
                f"{name}: func.__mcp_tool__ does not match registry tool_obj"
            )

        # 2) Docstring exists and contains a metadata section.
        doc = (inspect.getdoc(func) or "").strip()
        if not doc:
            failures.append(f"{name}: missing wrapper docstring")
        else:
            if "Tool metadata:" not in doc:
                failures.append(
                    f"{name}: wrapper docstring missing 'Tool metadata' section"
                )
            if f"- name: {name}" not in doc:
                failures.append(f"{name}: wrapper docstring missing tool name line")
            if "- write_action:" not in doc:
                failures.append(f"{name}: wrapper docstring missing write_action line")

        # 3) write_action classification present.
        write_action = getattr(func, "__mcp_write_action__", None)
        if write_action is None and getattr(tool_obj, "write_action", None) is None:
            failures.append(f"{name}: missing write_action classification")

        # 4) Input schema exists and is object-like.
        schema = _normalize_input_schema(tool_obj)
        if not isinstance(schema, Mapping):
            failures.append(f"{name}: missing input schema on tool object")
        else:
            if schema.get("type") != "object":
                failures.append(f"{name}: input schema type is not 'object'")
            props = schema.get("properties")
            if props is not None and not isinstance(props, Mapping):
                failures.append(f"{name}: input schema properties is not a mapping")

        # 5) Tool annotations exist and include core UI hints.
        ann = _get_tool_annotations(tool_obj)
        if not isinstance(ann, Mapping):
            failures.append(f"{name}: missing tool annotations")
        else:
            for k in ("readOnlyHint", "destructiveHint", "openWorldHint"):
                if k not in ann:
                    failures.append(f"{name}: annotations missing {k}")

        # 6) Signature is inspectable (wrapper should not be a bare *args/**kwargs).
        try:
            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            if len(params) == 2 and all(
                p.kind
                in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                for p in params
            ):
                failures.append(
                    f"{name}: wrapper signature collapsed to *args/**kwargs"
                )
        except Exception:
            failures.append(f"{name}: wrapper signature not inspectable")

    assert not failures, "\n".join(["Tool wrapper/metadata failures:"] + failures)


def test_registered_tool_names_are_unique() -> None:
    """Guardrail: overlapping/colliding registrations should not produce duplicates."""

    import main  # noqa: F401
    from github_mcp.server import _REGISTERED_MCP_TOOLS

    names: list[str] = []
    for tool_obj, func in _REGISTERED_MCP_TOOLS:
        name = (
            getattr(tool_obj, "name", None)
            or getattr(func, "__mcp_tool_name__", None)
            or getattr(func, "__name__", None)
        )
        if name:
            names.append(str(name))

    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"Duplicate registered tool names found: {dupes}"
