from __future__ import annotations

import re
import shlex
from collections.abc import Iterable

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


_SHELL_REDIRECT_TOKENS = {">", ">>", "2>", "&>", "1>", "2>>", "1>>"}

# Common shell command separators that indicate multiple commands.
_SHELL_SEPARATORS = {"&&", "||", ";"}


_SED_INPLACE = re.compile(r"(^|\s)-i(\s|$)")
_SHELL_REDIRECT_RE = re.compile(r"(^|\s)(?:\d*>>?|&>|2>|1>)")


def _has_unquoted_output_redirection(cmd: str) -> bool:
    """Return True if cmd contains an unquoted output redirection operator.

    We treat only output redirection (>, >>, 1>, 2>, &>) as write intent.
    Input redirection (<, <<) is ignored for gating purposes.

    This is a small state machine so commands like `rg ">" .` do not get
    misclassified as writes.
    """

    if not isinstance(cmd, str) or not cmd:
        return False

    in_single = False
    in_double = False
    escape = False

    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if escape:
            escape = False
            i += 1
            continue

        if ch == "\\":
            # Backslash escapes outside single quotes.
            if not in_single:
                escape = True
            i += 1
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if not in_single and not in_double:
            # Check multi-char operators first.
            if cmd.startswith("&>>", i):
                return True
            if cmd.startswith("2>>", i) or cmd.startswith("1>>", i):
                return True
            if cmd.startswith(">>", i):
                return True
            if cmd.startswith("&>", i):
                return True
            if cmd.startswith("2>", i) or cmd.startswith("1>", i):
                return True
            if ch == ">":
                return True

        i += 1

    return False


_READ_ONLY_DEV_BINARIES: set[str] = {
    "pytest",
    "py.test",
    "mypy",
    "flake8",
    "pylint",
}


def _split_pipeline(parts: list[str]) -> list[list[str]]:
    """Split a shlex token stream on pipes.

    This is intentionally simple: it assumes shlex already respected quoting.
    """

    segments: list[list[str]] = [[]]
    for tok in parts:
        if tok == "|":
            if segments[-1]:
                segments.append([])
            continue
        segments[-1].append(tok)
    return [seg for seg in segments if seg]


def _infer_write_action_from_parts(parts: list[str]) -> bool:
    """Infer write intent from an already-tokenized command (no redirection/pipes)."""

    if not parts:
        return True

    prog = parts[0]

    # `sudo <cmd>`: classify based on the underlying command.
    if prog == "sudo" and len(parts) > 1:
        return _infer_write_action_from_parts(parts[1:])

    # Wrapper commands: `poetry run <cmd>` / `pipenv run <cmd>` / `uv run <cmd>`.
    if prog in {"poetry", "pipenv", "uv"} and len(parts) > 2 and parts[1] == "run":
        return _infer_write_action_from_parts(parts[2:])

    # `make <target>`: treat common verification targets as read-ish.
    if prog == "make" and len(parts) > 1:
        if parts[1] in {"test", "lint", "check", "typecheck", "ci"}:
            return False

    # Common dev/test commands (generally safe; may still create ephemeral caches).
    if prog in _READ_ONLY_DEV_BINARIES:
        return False

    # pip: some subcommands are read-only.
    if prog == "pip" and len(parts) > 1:
        sub = parts[1]
        if sub in {"check", "--version", "-V", "list", "freeze", "show", "help"}:
            return False

    # Python module entrypoints.
    if prog == "python" and len(parts) >= 3 and parts[1] == "-m":
        module = parts[2]
        # pip is nuanced: some subcommands are read-only.
        if module == "pip":
            sub = parts[3] if len(parts) >= 4 else ""
            if sub in {"check", "--version", "-V", "list", "freeze", "show", "help"}:
                return False
            return True
        # Delegate classification for other common modules.
        return _infer_write_action_from_parts([module, *parts[3:]])

    # Ruff: `ruff check` is read unless `--fix`; `ruff format` writes unless `--check/--diff`.
    if prog == "ruff":
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "format":
            return not any(flag in parts for flag in {"--check", "--diff"})
        if sub == "check":
            return any(flag in parts for flag in {"--fix", "--unsafe-fixes"})
        # Default ruff command is check-like.
        return any(flag in parts for flag in {"--fix", "--unsafe-fixes"})

    # Black: writes unless explicitly checking.
    if prog == "black":
        return not any(flag in parts for flag in {"--check", "--diff"})

    # isort: writes unless explicitly checking.
    if prog == "isort":
        return not any(flag in parts for flag in {"--check", "--check-only", "--diff"})

    # ESLint: writes only with --fix.
    if prog == "eslint":
        return "--fix" in parts

    # Prettier: writes only with --write.
    if prog == "prettier":
        return "--write" in parts

    # Node package managers: allow common verification commands to be treated as read-ish.
    if prog in {"npm", "pnpm", "yarn"} and len(parts) > 1:
        sub = parts[1]
        if sub == "test":
            return False
        if sub == "run" and len(parts) > 2 and parts[2] in {
            "test",
            "lint",
            "typecheck",
            "check",
            "ci",
        }:
            return False
        # Installs and other mutations remain write.
        return True

    # sed is read-only unless -i (in-place) is used.
    if prog == "sed":
        cmd = " ".join(parts)
        return bool(_SED_INPLACE.search(cmd))

    # Explicit write-y utilities.
    if prog in _WRITE_BINARIES:
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


def _first_non_empty(lines: Iterable[str]) -> str:
    for line in lines:
        if isinstance(line, str) and line.strip():
            return line.strip()
    return ""


def infer_write_action_from_shell(
    command: str,
    *,
    command_lines: list[str] | None = None,
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

    # Tokenize for best-effort classification.
    try:
        parts = shlex.split(cmd)
    except Exception:
        return True

    if not parts:
        return True

    # Redirections are write-ish, but only when unquoted.
    # Avoid false positives like: rg ">" .
    if _has_unquoted_output_redirection(cmd):
        return True

    # Split chained commands (e.g. "cmd1 && cmd2; cmd3").
    segments: list[list[str]] = [[]]
    for tok in parts:
        if tok in _SHELL_SEPARATORS:
            if segments[-1]:
                segments.append([])
            continue
        segments[-1].append(tok)
    segments = [seg for seg in segments if seg]

    def _segment_is_write(seg: list[str]) -> bool:
        if not seg:
            return False
        # Pipelines: treat as write only if any stage is write.
        if "|" in seg:
            pipe_segments = _split_pipeline(seg)
            if not pipe_segments:
                return True
            return any(_infer_write_action_from_parts(p) for p in pipe_segments)
        return _infer_write_action_from_parts(seg)

    if segments:
        return any(_segment_is_write(seg) for seg in segments)
    return True
