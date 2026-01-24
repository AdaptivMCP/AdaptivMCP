"""Pytest configuration.

The CI/test runner for this repository may execute `pytest` from a parent
working directory (e.g., a mono-repo checkout path). When that happens, Python
may not automatically include the repository root on `sys.path`, which breaks
imports of in-repo modules like `github_mcp` and `main`.

To keep tests robust across environments, we explicitly prepend the repository
root to `sys.path`.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# Prepend (not append) so in-repo modules win over any globally installed
# packages with the same name.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
