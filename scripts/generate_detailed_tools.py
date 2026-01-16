"""Generate Detailed_Tools.md from the live tool registry.

This repo treats the Python code as the source of truth.
Tool docs may be regenerated when the tool surface or schemas change.

Usage:
  python scripts/generate_detailed_tools.py
  python scripts/generate_detailed_tools.py Detailed_Tools.md

This script writes atomically (via a temporary file) so failed imports or
runtime errors do not truncate the existing output file.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

# Ensure repository root is on sys.path when invoked as a script.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _load_main():
    """Import main lazily.

    The running server depends on runtime packages (for example httpx). When
    those packages are missing, importing main will fail. This helper keeps the
    failure mode explicit and prevents partial file writes.
    """

    try:
        import main  # type: ignore  # noqa: E402

        return main
    except ModuleNotFoundError as exc:
        missing = getattr(exc, "name", None) or str(exc)
        raise RuntimeError(
            "Unable to import the server registry (main). Install runtime dependencies "
            "first (for example: pip install -r requirements.txt). Missing module: "
            f"{missing}"
        ) from exc


def _as_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False)


def _resolve_output_path(argv: list[str]) -> Path:
    if len(argv) >= 2 and argv[1].strip():
        return Path(argv[1]).expanduser()
    return Path("Detailed_Tools.md")


def main_cli(argv: list[str]) -> None:
    out_path = _resolve_output_path(argv)
    main = _load_main()
    catalog = main.list_all_actions(include_parameters=True, compact=False)
    tools = list(catalog.get("tools", []))
    tools.sort(key=lambda t: (t.get("name") or ""))

    lines: list[str] = []
    lines.append("# Detailed tools reference (generated)\n\n")
    lines.append(
        "This file is generated from the running tool registry via "
        "`main.list_all_actions(include_parameters=True, compact=False)`.\n\n"
    )
    lines.append(
        "Regenerate via:\n\n"
        "```bash\npython scripts/generate_detailed_tools.py > Detailed_Tools.md\n```\n\n"
    )

    lines.append(f"Total tools: {len(tools)}\n")

    for tool in tools:
        name = tool.get("name") or "<unknown>"
        description = (tool.get("description") or "").strip()
        write_action = bool(tool.get("write_action"))
        write_allowed = bool(tool.get("write_allowed"))
        write_auto_approved = bool(tool.get("write_auto_approved"))
        approval_required = bool(tool.get("approval_required"))
        write_enabled = bool(tool.get("write_enabled"))
        visibility = tool.get("visibility")
        ui_prompt_val = tool.get("ui_prompt")
        ui_prompt = ""
        if isinstance(ui_prompt_val, str):
            ui_prompt = ui_prompt_val.strip()
        elif ui_prompt_val is not None and ui_prompt_val is not False:
            ui_prompt = str(ui_prompt_val).strip()
        input_schema = tool.get("input_schema")

        lines.append(f"\n## {name}\n\n")
        if description:
            lines.append(description + "\n\n")

        lines.append("Metadata:\n")
        lines.append(f"- visibility: {visibility}\n")
        lines.append(f"- write_action: {write_action}\n")
        lines.append(f"- write_allowed: {write_allowed}\n")
        lines.append(f"- write_enabled: {write_enabled}\n")
        lines.append(f"- write_auto_approved: {write_auto_approved}\n")
        lines.append(f"- approval_required: {approval_required}\n")
        if ui_prompt:
            lines.append(f"- ui_prompt: {ui_prompt}\n")

        if input_schema is not None:
            lines.append("\nInput schema:\n\n```json\n")
            lines.append(_as_json(input_schema) + "\n")
            lines.append("```\n")

        lines.append("\nExample invocation:\n\n```json\n")
        lines.append(_as_json({"tool": name, "args": {}}) + "\n")
        lines.append("```\n")

    rendered = "".join(lines)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = str(out_path.parent)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=tmp_dir) as tmp:
        tmp.write(rendered)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name

    os.replace(tmp_name, out_path)

    # Also echo to stdout for convenience.
    sys.stdout.write(rendered)


if __name__ == "__main__":
    main_cli(sys.argv)
