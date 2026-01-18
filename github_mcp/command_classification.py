from __future__ import annotations

import re
import shlex
from typing import Iterable, Optional


_READ_ONLY_BINARIES: set[str] = {
    "cat",
    "cd",
    "echo",
    "env",
    "find",
    "git",
    "head",
    "less",
    "ls",
    "pwd",
    "rg",
    "ripgrep",
    "sed",
    "tail",
    "test",
    "true",
    "type",
    "uname",
    "wc",
    "which",
}


_GIT_READ_SUBCOMMANDS: set[str] = {
    "branch",
    "diff",
    "grep",
    "log",
    "rev-parse",
    "show",
    "status",
    "ls-files",
    "remote",
    "config",  # can mutate; we treat as write only with explicit --global/--system + set.
}


_GIT_WRITE_SUBCOMMANDS: set[str] = {
    "add",
    "am",
    "apply",
    "checkout",
    "cherry-pick",
    "clean",
    "clone",
    "commit",
    "fetch",
    "merge",
    "mv",
    "pull",
    "push",
    "rebase",
    "reset",
    "revert",
    "rm",
    "stash",
    "submodule",
    "switch",
    "tag",
}


_WRITE_BINARIES: set[str] = {
    "chmod",
    "chown",
    "cp",
    "install",
    "ln",
    "mkdir",
    "mv",
    "npm",
    "pnpm",
    "pip",
    "poetry",
    "rm",
    "rmdir",
    "tee",
    "touch",
    "yarn",
}


_SHELL_WRITE_TOKENS = {">", ">>", "2>", "&>", "1>", "|"}


_SED_INPLACE = re.compile(r"(^|\s)-i(\s|$)")


def _first_non_empty(lines: Iterable[str]) -> str:
    for line in lines:
        if isinstance(line, str) and line.strip():
            return line.strip()
    return ""


def infer_write_action_from_shell(
    command: str,
    *,
    command_lines: Optional[list[str]] = None,
    installing_dependencies: bool = False,
) -> bool:
    """Infer whether a shell command is intended to be a write (mutating) action.

    This intentionally errs on the side of classifying as a write unless we can
    confidently identify the invocation as read-only.

    Notes:
    - The classification is best-effort and heuristic.
    - The goal is to provide *dynamic metadata* and safer retry behavior,
      not a perfect sandbox-level policy.
    """

    if installing_dependencies:
        return True

    if not isinstance(command, str):
        return True

    cmd = command.strip()
    if not cmd and command_lines:
        cmd = _first_non_empty(command_lines)
    if not cmd:
        return True

    # Obvious shell redirection / pipelines often indicate output writes.
    # Pipelines are conservative here: `... | less` is read-ish, but `... | tee`
    # is write-ish, and we do not want to under-classify.
    if any(tok in cmd for tok in _SHELL_WRITE_TOKENS):
        # Special-case: pipe into read-only pagers.
        if "|" in cmd and ("| less" in cmd or "| more" in cmd):
            return False
        return True

    # Tokenize for best-effort classification.
    try:
        parts = shlex.split(cmd)
    except Exception:
        return True

    if not parts:
        return True

    prog = parts[0]

    # `sudo <cmd>`: classify based on the underlying command.
    if prog == "sudo" and len(parts) > 1:
        prog = parts[1]
        parts = parts[1:]

    # sed is read-only unless -i (in-place) is used.
    if prog == "sed":
        return bool(_SED_INPLACE.search(cmd))

    # Explicit write-y utilities.
    if prog in _WRITE_BINARIES:
        return True

    # Python -m pip is write.
    if prog == "python" and len(parts) >= 3 and parts[1] == "-m" and parts[2] in {"pip"}:
        return True

    # Git: classify by subcommand with some nuance.
    if prog == "git":
        sub = parts[1] if len(parts) > 1 else ""
        if sub in _GIT_WRITE_SUBCOMMANDS:
            return True
        if sub in _GIT_READ_SUBCOMMANDS:
            # `git branch -d/-D` and friends are write actions.
            if sub == "branch" and any(x in parts for x in {"-d", "-D", "--delete"}):
                return True
            # `git config` can mutate; treat `--global/--system` with set as write.
            if sub == "config" and any(x in parts for x in {"--global", "--system"}):
                # If caller is setting a key, it's a mutation.
                if len(parts) >= 4:
                    return True
            return False
        # Unknown git subcommand -> conservative.
        return True

    # Common read-only utilities.
    if prog in _READ_ONLY_BINARIES:
        return False

    # Default: unknown commands are treated as write actions.
    return True

