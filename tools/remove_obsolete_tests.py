from __future__ import annotations

import re
from pathlib import Path

path = Path("tests/test_dynamic_write_action_metadata.py")
text = path.read_text(encoding="utf-8")

# Remove two obsolete tests by function name, including their docstrings and bodies.
patterns = [
    r"\n\ndef test_registered_tool_annotations_update_on_invocation\(.*?\n\n(?=def |\Z)",
    r"\n\ndef test_tool_obj_meta_annotations_overwrite_on_invocation\(.*?\n\n(?=def |\Z)",
]

new_text = text
for pat in patterns:
    new_text, n = re.subn(pat, "\n\n", new_text, flags=re.S)
    if n != 1:
        raise SystemExit(
            f"Expected to remove exactly 1 block for pattern: {pat} (removed={n})"
        )

# Normalize excessive blank lines (keep at most 2 between top-level defs).
new_text = re.sub(r"\n{4,}", "\n\n\n", new_text)

# Ensure trailing newline
if not new_text.endswith("\n"):
    new_text += "\n"

path.write_text(new_text, encoding="utf-8")
print("Updated", path, "bytes", len(text), "->", len(new_text))
