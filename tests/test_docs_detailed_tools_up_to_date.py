from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_detailed_tools_markdown_is_up_to_date() -> None:
    """Fail if Detailed_Tools.md is not regenerated after tool surface changes."""

    # Run generation in a fresh interpreter so earlier tests cannot mutate the
    # in-process tool registry and cause nondeterministic tool counts.
    expected = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from scripts.generate_detailed_tools import render_detailed_tools; import sys; sys.stdout.write(render_detailed_tools())",
        ],
        text=True,
    )
    actual = Path("Detailed_Tools.md").read_text(encoding="utf-8")

    # Keep the comparison strict so CI reliably signals when regeneration is needed.
    assert (
        actual == expected
    ), "Detailed_Tools.md is out of date. Regenerate it by running: python scripts/generate_detailed_tools.py"

