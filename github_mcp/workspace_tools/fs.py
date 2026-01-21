# Split from github_mcp.tools_workspace (generated).
import glob
import hashlib
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any, Literal

from github_mcp.diff_utils import build_unified_diff, diff_stats
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)

from ._shared import _tw

_LOG_WRITE_DIFFS = os.environ.get("ADAPTIV_MCP_LOG_WRITE_DIFFS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


# Default read limits to avoid loading multi-megabyte files into memory.
# These are used by the single-file and multi-file read tools unless callers
# override them.
_DEFAULT_MAX_READ_BYTES = 2_000_000
_DEFAULT_MAX_READ_CHARS = 300_000


def _maybe_diff_for_log(
    *,
    path: str,
    before: str,
    after: str,
    before_exists: bool,
) -> str | None:
    """Best-effort unified diff for provider logs.

    The diff is attached to tool results under a __log_* key. The tool wrapper
    preserves these fields in client-visible payloads by default so the user and
    model see the same data that produced visual tool logs.
    """

    if not _LOG_WRITE_DIFFS:
        return None
    if not isinstance(before, str) or not isinstance(after, str):
        return None
    if before == after:
        return None

    diff = build_unified_diff(
        before,
        after,
        fromfile=(path if before_exists else "/dev/null"),
        tofile=path,
    )
    if not diff:
        return None
    return diff


def _delete_diff_for_log(*, path: str, before: str) -> str | None:
    """Best-effort unified diff for deletions."""

    if not _LOG_WRITE_DIFFS:
        return None
    if not isinstance(before, str) or before == "":
        return None
    diff = build_unified_diff(before, "", fromfile=path, tofile="/dev/null")
    if not diff:
        return None
    return diff


def _looks_like_diff(text: str) -> bool:
    if not isinstance(text, str):
        return False
    s = text.lstrip()
    if not s:
        return False
    sample = "\n".join(s.splitlines()[:25])
    return (
        "diff --git" in sample
        or sample.startswith("diff --git")
        or "+++ " in sample
        or "--- " in sample
        or "@@ " in sample
    )


def _workspace_safe_join(repo_dir: str, rel_path: str) -> str:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise ValueError("path must be a non-empty string")
    raw_path = rel_path.strip().replace("\\", "/")
    root = os.path.realpath(repo_dir)
    if os.path.isabs(raw_path):
        # Accept absolute paths *only* when they resolve inside this workspace
        # mirror. This allows callers to round-trip paths returned by tools
        # like `terminal_command` (which reports an absolute workdir) without
        # requiring them to know the workspace base directory.
        candidate = os.path.realpath(raw_path)
        try:
            common = os.path.commonpath([root, candidate])
        except Exception:
            common = ""
        if common != root:
            raise ValueError(
                "path must be repository-relative or an absolute path inside the workspace repository"
            )
        return candidate
    rel_path = raw_path.lstrip("/\\")
    if not rel_path:
        raise ValueError("path must be a non-empty string")
    candidate = os.path.realpath(os.path.join(repo_dir, rel_path))
    try:
        common = os.path.commonpath([root, candidate])
    except Exception:
        common = ""
    if common != root:
        raise ValueError("path must resolve inside the workspace repository")
    return candidate


def _workspace_read_text(repo_dir: str, path: str) -> dict[str, Any]:
    abs_path = _workspace_safe_join(repo_dir, path)
    if not os.path.exists(abs_path):
        return {
            "exists": False,
            "path": path,
            "text": "",
            "encoding": "utf-8",
            "had_decoding_errors": False,
        }

    with open(abs_path, "rb") as f:
        data = f.read()

    had_errors = False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        had_errors = True
        text = data.decode("utf-8", errors="replace")

    return {
        "exists": True,
        "path": path,
        "text": text,
        "encoding": "utf-8",
        "had_decoding_errors": had_errors,
        "size_bytes": len(data),
    }


def _workspace_read_text_limited(
    repo_dir: str,
    path: str,
    *,
    max_chars: int,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Read a workspace file as text with hard truncation limits.

    - max_bytes limits the number of raw bytes read from disk.
    - max_chars limits the number of decoded characters returned.

    The returned payload includes a `truncated` boolean.
    """

    if not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars must be an int >= 1")
    if max_bytes is None:
        # Heuristic: assume up to ~4 bytes per char for UTF-8.
        max_bytes = max(_DEFAULT_MAX_READ_BYTES, max_chars * 4)
    if not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be an int >= 1")

    abs_path = _workspace_safe_join(repo_dir, path)
    if not os.path.exists(abs_path):
        return {
            "exists": False,
            "path": path,
            "text": "",
            "encoding": "utf-8",
            "had_decoding_errors": False,
            "truncated": False,
        }

    # Binary files can decode into enormous replacement-filled strings that
    # overwhelm some clients and appear as an "infinite hang". Detect a small
    # sample up-front and return a stable, non-text payload.
    if _is_probably_binary(abs_path):
        size_bytes = os.path.getsize(abs_path)
        truncated_bytes = size_bytes > max_bytes
        sample = b""
        try:
            with open(abs_path, "rb") as bf:
                sample = bf.read(min(4096, int(max_bytes)))
        except Exception:
            sample = b""

        digest = hashlib.blake2s(sample, digest_size=4).hexdigest() if sample else None
        return {
            "exists": True,
            "path": path,
            "text": "",
            "encoding": "binary",
            "is_binary": True,
            "had_decoding_errors": False,
            "size_bytes": int(size_bytes),
            "truncated": bool(truncated_bytes),
            "truncated_bytes": bool(truncated_bytes),
            "truncated_chars": False,
            "max_bytes": int(max_bytes),
            "max_chars": int(max_chars),
            "text_digest": digest,
        }

    size_bytes = os.path.getsize(abs_path)
    truncated_bytes = size_bytes > max_bytes
    to_read = min(size_bytes, max_bytes)
    with open(abs_path, "rb") as f:
        data = f.read(to_read)

    had_errors = False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        had_errors = True
        text = data.decode("utf-8", errors="replace")

    truncated_chars = len(text) > max_chars
    if truncated_chars:
        text = text[:max_chars]

    digest = hashlib.blake2s(text.encode("utf-8", errors="replace"), digest_size=4).hexdigest()

    return {
        "exists": True,
        "path": path,
        "text": text,
        "encoding": "utf-8",
        "had_decoding_errors": had_errors,
        "size_bytes": size_bytes,
        "truncated": bool(truncated_bytes or truncated_chars),
        "truncated_bytes": bool(truncated_bytes),
        "truncated_chars": bool(truncated_chars),
        "max_bytes": int(max_bytes),
        "max_chars": int(max_chars),
        "text_digest": digest,
    }


def _is_probably_binary(abs_path: str) -> bool:
    try:
        with open(abs_path, "rb") as bf:
            sample = bf.read(4096)
        return b"\x00" in sample
    except Exception:
        return False


def _read_lines_excerpt(
    abs_path: str,
    *,
    start_line: int,
    max_lines: int,
    max_chars: int,
) -> dict[str, Any]:
    """Read a subset of lines from a text file without loading the full file."""

    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if max_lines < 1:
        raise ValueError("max_lines must be >= 1")
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")

    lines_out: list[dict[str, Any]] = []
    current = 0
    collected_chars = 0
    truncated = False
    had_decoding_errors = False

    try:
        with open(abs_path, encoding="utf-8", errors="replace") as tf:
            for current, raw in enumerate(tf, start=1):
                if current < start_line:
                    continue
                if len(lines_out) >= max_lines:
                    truncated = True
                    break
                # Strip trailing newline for display while keeping content readable.
                text = raw.rstrip("\n")
                # Hard cap total chars.
                if collected_chars + len(text) > max_chars:
                    remaining = max_chars - collected_chars
                    if remaining > 0:
                        text = text[:remaining]
                        lines_out.append({"line": current, "text": text, "truncated": True})
                    truncated = True
                    break
                lines_out.append({"line": current, "text": text})
                collected_chars += len(text)
    except UnicodeDecodeError:
        had_decoding_errors = True
    except Exception as exc:
        raise exc

    end_line = start_line + len(lines_out) - 1 if lines_out else start_line
    return {
        "start_line": int(start_line),
        "end_line": int(end_line),
        "lines": lines_out,
        "truncated": bool(truncated),
        "had_decoding_errors": bool(had_decoding_errors),
        "max_lines": int(max_lines),
        "max_chars": int(max_chars),
    }


def _sections_from_line_iter(
    line_iter: Any,
    *,
    start_line: int,
    max_sections: int,
    max_lines_per_section: int,
    max_chars_per_section: int,
    overlap_lines: int,
) -> dict[str, Any]:
    """Build multiple line-numbered sections from an iterator of text lines.

    The iterator must yield raw strings (including trailing newlines). Line
    numbers are assigned based on iteration order starting at 1.
    """

    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if max_sections < 1:
        raise ValueError("max_sections must be >= 1")
    if max_lines_per_section < 1:
        raise ValueError("max_lines_per_section must be >= 1")
    if max_chars_per_section < 1:
        raise ValueError("max_chars_per_section must be >= 1")

    overlap = int(overlap_lines)
    if overlap < 0:
        overlap = 0
    # Prevent degenerate overlap that would stall pagination.
    if overlap >= max_lines_per_section:
        overlap = max_lines_per_section - 1
        if overlap < 0:
            overlap = 0

    parts: list[dict[str, Any]] = []
    current_lines: list[dict[str, Any]] = []
    current_chars = 0
    current_start: int | None = None
    had_decoding_errors = False
    line_no = 0
    truncated = False
    next_start_line: int | None = None

    def _finalize_current() -> None:
        nonlocal current_lines, current_chars, current_start
        if not current_lines or current_start is None:
            current_lines = []
            current_chars = 0
            current_start = None
            return
        parts.append(
            {
                "part_index": len(parts),
                "start_line": int(current_start),
                "end_line": int(current_lines[-1]["line"]),
                "lines": current_lines,
            }
        )
        current_lines = []
        current_chars = 0
        current_start = None

    def _seed_overlap_from_last() -> None:
        nonlocal current_lines, current_chars, current_start
        if overlap <= 0 or not parts:
            return
        tail = list(parts[-1]["lines"][-overlap:])
        if not tail:
            return
        current_lines = tail
        current_start = int(tail[0]["line"])
        # +1 per line for display newline accounting.
        current_chars = sum(len(str(x.get("text") or "")) + 1 for x in tail)

    for raw in line_iter:
        line_no += 1
        if line_no < start_line:
            continue

        if current_start is None:
            current_start = line_no

        text = raw.rstrip("\n")

        # If adding this line would overflow the section, finalize and start a
        # new section (with optional overlap).
        would_overflow = False
        if current_lines and len(current_lines) >= max_lines_per_section:
            would_overflow = True
        elif current_lines and (current_chars + len(text) + 1) > max_chars_per_section:
            would_overflow = True

        if would_overflow:
            _finalize_current()
            if len(parts) >= max_sections:
                truncated = True
                # Continuation should begin after applying overlap.
                last_end = int(parts[-1]["end_line"]) if parts else line_no
                next_start_line = max(1, last_end - overlap + 1)
                break
            _seed_overlap_from_last()
            if current_start is None:
                current_start = line_no

        # Handle a single line that alone exceeds the section char budget.
        if not current_lines and (len(text) + 1) > max_chars_per_section:
            truncated = True
            clipped = text[: max(0, max_chars_per_section - 1)]
            current_lines.append({"line": line_no, "text": clipped, "truncated": True})
            current_start = line_no
            _finalize_current()
            next_start_line = line_no + 1
            break

        next_chars = current_chars + len(text) + 1
        if next_chars > max_chars_per_section:
            # Clip within the current section.
            truncated = True
            remaining = max_chars_per_section - current_chars - 1
            if remaining > 0:
                current_lines.append({"line": line_no, "text": text[:remaining], "truncated": True})
            _finalize_current()
            next_start_line = line_no + 1
            break

        current_lines.append({"line": line_no, "text": text})
        current_chars = next_chars

    if not truncated:
        # If we finished naturally, flush any remaining buffered section.
        _finalize_current()
    else:
        # If truncated but we didn't flush (e.g., max_sections cut), ensure any
        # pending section makes it into the response.
        if current_lines and (not parts or parts[-1].get("end_line") != current_lines[-1]["line"]):
            _finalize_current()

    # If we filled max_sections exactly but ended at EOF, clear truncation.
    # We can't reliably detect EOF without consuming more from the iterator,
    # so only clear when we never set truncated.

    overall_start = int(start_line)
    overall_end = int(parts[-1]["end_line"]) if parts else int(start_line)
    return {
        "start_line": overall_start,
        "end_line": overall_end,
        "parts": parts,
        "truncated": bool(truncated),
        "next_start_line": next_start_line,
        "max_sections": int(max_sections),
        "max_lines_per_section": int(max_lines_per_section),
        "max_chars_per_section": int(max_chars_per_section),
        "overlap_lines": int(overlap),
        "had_decoding_errors": bool(had_decoding_errors),
    }


def _read_lines_sections(
    abs_path: str,
    *,
    start_line: int,
    max_sections: int,
    max_lines_per_section: int,
    max_chars_per_section: int,
    overlap_lines: int,
) -> dict[str, Any]:
    """Read multiple line-numbered sections from a text file.

    This is intended for large files where callers want pagination/chunking
    with *real* line numbers.
    """

    try:
        with open(abs_path, encoding="utf-8", errors="replace") as tf:
            return _sections_from_line_iter(
                tf,
                start_line=int(start_line),
                max_sections=int(max_sections),
                max_lines_per_section=int(max_lines_per_section),
                max_chars_per_section=int(max_chars_per_section),
                overlap_lines=int(overlap_lines),
            )
    except UnicodeDecodeError:
        # errors="replace" should avoid this, but keep schema stable.
        return {
            "start_line": int(start_line),
            "end_line": int(start_line),
            "parts": [],
            "truncated": False,
            "next_start_line": None,
            "max_sections": int(max_sections),
            "max_lines_per_section": int(max_lines_per_section),
            "max_chars_per_section": int(max_chars_per_section),
            "overlap_lines": int(overlap_lines),
            "had_decoding_errors": True,
        }


def _sanitize_git_ref(ref: str) -> str:
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("git ref must be a non-empty string")
    r = ref.strip()
    if any(ch.isspace() for ch in r):
        raise ValueError("git ref must not contain whitespace")
    if r.startswith("-"):
        raise ValueError("git ref must not start with '-' ")
    if "\x00" in r:
        raise ValueError("git ref must not contain NUL")
    return r


def _sanitize_git_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")
    p = path.strip().replace("\\", "/").lstrip("/")
    if ":" in p:
        raise ValueError("path must not contain ':'")
    if p.startswith("-"):
        raise ValueError("path must not start with '-' ")
    return p


def _git_show_text(repo_dir: str, git_ref: str, path: str) -> dict[str, Any]:
    """Read a file as text from a git object (ref:path) without checkout."""

    ref = _sanitize_git_ref(git_ref)
    rel = _sanitize_git_path(path)
    # Ensure the rel path is safe and inside the workspace.
    _workspace_safe_join(repo_dir, rel)

    proc = subprocess.run(
        ["git", "show", f"{ref}:{rel}"],
        cwd=repo_dir,
        capture_output=True,
        timeout=20,
    )
    if proc.returncode != 0:
        return {
            "exists": False,
            "ref": ref,
            "path": rel,
            "text": "",
            "encoding": "utf-8",
            "had_decoding_errors": False,
            "error": (proc.stderr or b"").decode("utf-8", errors="replace").strip() or None,
        }

    data = proc.stdout or b""
    had_errors = False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        had_errors = True
        text = data.decode("utf-8", errors="replace")

    return {
        "exists": True,
        "ref": ref,
        "path": rel,
        "text": text,
        "encoding": "utf-8",
        "had_decoding_errors": had_errors,
        "size_bytes": len(data),
    }


def _git_show_text_limited(
    repo_dir: str,
    git_ref: str,
    path: str,
    *,
    max_chars: int,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Like _git_show_text, but reads at most max_bytes and returns at most max_chars.

    This avoids holding very large blobs in memory.
    """

    if not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars must be an int >= 1")
    if max_bytes is None:
        max_bytes = max(_DEFAULT_MAX_READ_BYTES, max_chars * 4)
    if not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be an int >= 1")

    ref = _sanitize_git_ref(git_ref)
    rel = _sanitize_git_path(path)
    _workspace_safe_join(repo_dir, rel)

    proc = subprocess.Popen(
        ["git", "show", f"{ref}:{rel}"],
        cwd=repo_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout = b""
    stderr = b""
    truncated_bytes = False
    try:
        if proc.stdout is None or proc.stderr is None:
            raise RuntimeError("failed to spawn git show")
        # Read up to max_bytes from stdout.
        while len(stdout) < max_bytes:
            chunk = proc.stdout.read(min(65536, max_bytes - len(stdout)))
            if not chunk:
                break
            stdout += chunk
        if len(stdout) >= max_bytes:
            truncated_bytes = True
            try:
                proc.kill()
            except Exception:
                pass
        try:
            _out, _err = proc.communicate(timeout=10)
            # If we didn't hit truncation, stdout may be fully captured by communicate.
            if not truncated_bytes:
                stdout = _out or b""
            stderr = _err or b""
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                _out, _err = proc.communicate(timeout=5)
                if not truncated_bytes:
                    stdout = _out or b""
                stderr = _err or b""
            except Exception:
                pass
    finally:
        try:
            proc.stdout.close() if proc.stdout else None
        except Exception:
            pass
        try:
            proc.stderr.close() if proc.stderr else None
        except Exception:
            pass

    if proc.returncode not in (0, None):
        return {
            "exists": False,
            "ref": ref,
            "path": rel,
            "text": "",
            "encoding": "utf-8",
            "had_decoding_errors": False,
            "truncated": False,
            "error": (stderr or b"").decode("utf-8", errors="replace").strip() or None,
        }

    had_errors = False
    try:
        text = (stdout or b"").decode("utf-8")
    except UnicodeDecodeError:
        had_errors = True
        text = (stdout or b"").decode("utf-8", errors="replace")

    truncated_chars = len(text) > max_chars
    if truncated_chars:
        text = text[:max_chars]

    digest = hashlib.blake2s(text.encode("utf-8", errors="replace"), digest_size=4).hexdigest()

    return {
        "exists": True,
        "ref": ref,
        "path": rel,
        "text": text,
        "encoding": "utf-8",
        "had_decoding_errors": had_errors,
        "size_bytes": len(stdout or b""),
        "truncated": bool(truncated_bytes or truncated_chars),
        "truncated_bytes": bool(truncated_bytes),
        "truncated_chars": bool(truncated_chars),
        "max_bytes": int(max_bytes),
        "max_chars": int(max_chars),
        "text_digest": digest,
    }


def _workspace_write_text(
    repo_dir: str,
    path: str,
    text: str,
    *,
    create_parents: bool = True,
) -> dict[str, Any]:
    abs_path = _workspace_safe_join(repo_dir, path)
    parent = os.path.dirname(abs_path)
    if create_parents:
        os.makedirs(parent, exist_ok=True)

    existed = os.path.exists(abs_path)
    data = (text or "").encode("utf-8")

    tmp_path = abs_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, abs_path)

    return {
        "path": path,
        "exists_before": existed,
        "size_bytes": len(data),
        "encoding": "utf-8",
    }


def _infer_eol_from_lines(lines: list[str]) -> str:
    """Infer an EOL sequence from an existing file.

    Defaults to \n, but prefers \r\n when detected.
    """

    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
    for line in lines:
        if line.endswith("\n"):
            return "\n"
    for line in lines:
        if line.endswith("\r"):
            return "\r"
    return "\n"


def _split_lines_keepends(text: str) -> list[str]:
    # splitlines(True) returns [] for empty strings; keep that behavior.
    return (text or "").splitlines(True)


def _line_content_and_eol(raw_line: str) -> tuple[str, str]:
    if raw_line.endswith("\r\n"):
        return raw_line[:-2], "\r\n"
    if raw_line.endswith("\n"):
        return raw_line[:-1], "\n"
    if raw_line.endswith("\r"):
        return raw_line[:-1], "\r"
    return raw_line, ""


def _pos_to_offset(lines: list[str], line: int, col: int) -> int:
    """Convert a 1-indexed (line, col) position to a 0-indexed absolute offset.

    Semantics:
      - line is 1..len(lines)+1 (len(lines)+1 represents EOF).
      - col is 1..len(line_content)+1 for in-file lines.
      - For EOF (line == len(lines)+1), col must be 1.
      - col counts unicode codepoints within the line content; the position
        col=len(content)+1 is the point *after* the last character in that line,
        but before the line ending (if any). Selecting across lines naturally
        includes the newline by using end=(next_line, 1).
    """

    if line < 1:
        raise ValueError("line must be >= 1")
    if col < 1:
        raise ValueError("col must be >= 1")

    # EOF sentinel.
    if line == len(lines) + 1:
        if col != 1:
            raise ValueError("col must be 1 when line points at EOF")
        return sum(len(x) for x in lines)

    if line > len(lines):
        raise ValueError("line out of range")

    raw_line = lines[line - 1]
    content, _eol = _line_content_and_eol(raw_line)
    if col > len(content) + 1:
        raise ValueError("col out of range for line")

    prefix = sum(len(x) for x in lines[: line - 1])
    return prefix + (col - 1)


@mcp_tool(write_action=True)
async def create_workspace_folders(
    full_name: str,
    ref: str = "main",
    paths: list[str] | None = None,
    exist_ok: bool = True,
    create_parents: bool = True,
) -> dict[str, Any]:
    """Create one or more folders in the repo mirror.

    Notes:
      - `paths` must be repo-relative paths.
      - When `exist_ok` is false, existing folders are treated as failures.
    """

    if paths is None:
        paths = []
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise TypeError("paths must be a list of strings")
    if len(paths) == 0:
        raise ValueError("paths must contain at least one path")

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        created: list[str] = []
        existing: list[str] = []
        failed: list[dict[str, Any]] = []

        for rel_path in paths:
            try:
                abs_path = _workspace_safe_join(repo_dir, rel_path)
                if os.path.exists(abs_path):
                    if os.path.isdir(abs_path):
                        if exist_ok:
                            existing.append(rel_path)
                        else:
                            raise FileExistsError(rel_path)
                    else:
                        raise FileExistsError(rel_path)
                    continue

                if create_parents:
                    os.makedirs(abs_path, exist_ok=bool(exist_ok))
                else:
                    os.mkdir(abs_path)
                created.append(rel_path)
            except Exception as exc:
                failed.append({"path": rel_path, "error": str(exc)})

        return {
            "ref": effective_ref,
            "status": "created",
            "created": created,
            "existing": existing,
            "failed": failed,
            "ok": len(failed) == 0,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="create_workspace_folders")


@mcp_tool(write_action=True)
async def delete_workspace_paths(
    full_name: str,
    ref: str = "main",
    paths: list[str] | None = None,
    allow_missing: bool = True,
    allow_recursive: bool = False,
) -> dict[str, Any]:
    """Delete one or more paths from the repo mirror.

    This tool exists because some environments can block patch-based file deletions.
    Prefer this over embedding deletions into unified-diff patches.

    Notes:
      - `paths` must be repo-relative paths.
      - Directories require `allow_recursive=true` (for non-empty directories).
    """

    if paths is None:
        paths = []
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise TypeError("paths must be a list of strings")
    if len(paths) == 0:
        raise ValueError("paths must contain at least one path")

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)

        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        removed: list[str] = []
        missing: list[str] = []
        failed: list[dict[str, Any]] = []

        for rel_path in paths:
            try:
                abs_path = _workspace_safe_join(repo_dir, rel_path)

                if not os.path.exists(abs_path):
                    if allow_missing:
                        missing.append(rel_path)
                        continue
                    raise FileNotFoundError(rel_path)

                if os.path.isdir(abs_path):
                    if allow_recursive:
                        shutil.rmtree(abs_path)
                    else:
                        os.rmdir(abs_path)
                else:
                    os.remove(abs_path)

                removed.append(rel_path)
            except Exception as exc:
                failed.append({"path": rel_path, "error": str(exc)})

        return {
            "ref": effective_ref,
            "status": "deleted",
            "removed": removed,
            "missing": missing,
            "failed": failed,
            "ok": len(failed) == 0,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="delete_workspace_paths")


@mcp_tool(write_action=True)
async def delete_workspace_folders(
    full_name: str,
    ref: str = "main",
    paths: list[str] | None = None,
    allow_missing: bool = True,
    allow_recursive: bool = False,
) -> dict[str, Any]:
    """Delete one or more folders from the repo mirror.

    Notes:
      - `paths` must be repo-relative paths.
      - Non-empty folders require `allow_recursive=true`.
    """

    if paths is None:
        paths = []
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise TypeError("paths must be a list of strings")
    if len(paths) == 0:
        raise ValueError("paths must contain at least one path")

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        removed: list[str] = []
        missing: list[str] = []
        failed: list[dict[str, Any]] = []

        for rel_path in paths:
            try:
                abs_path = _workspace_safe_join(repo_dir, rel_path)

                if not os.path.exists(abs_path):
                    if allow_missing:
                        missing.append(rel_path)
                        continue
                    raise FileNotFoundError(rel_path)

                if not os.path.isdir(abs_path):
                    raise NotADirectoryError(rel_path)

                if allow_recursive:
                    shutil.rmtree(abs_path)
                else:
                    os.rmdir(abs_path)
                removed.append(rel_path)
            except Exception as exc:
                failed.append({"path": rel_path, "error": str(exc)})

        return {
            "ref": effective_ref,
            "status": "deleted",
            "removed": removed,
            "missing": missing,
            "failed": failed,
            "ok": len(failed) == 0,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="delete_workspace_folders")


@mcp_tool(write_action=False)
async def get_workspace_file_contents(
    full_name: str,
    ref: str = "main",
    path: str = "",
    *,
    max_chars: int = _DEFAULT_MAX_READ_CHARS,
    max_bytes: int = _DEFAULT_MAX_READ_BYTES,
) -> dict[str, Any]:
    """Read a file from the persistent repo mirror (no shell).

    Args:
      path: Repo-relative path (POSIX-style). Must resolve inside the repo mirror.

    Returns:
      A dict with keys like: exists, path, text, encoding, size_bytes.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text_limited(
            repo_dir,
            path,
            max_chars=int(max_chars),
            max_bytes=int(max_bytes),
        )
        info.update({"full_name": full_name, "ref": effective_ref})
        return info
    except Exception as exc:
        return _structured_tool_error(exc, context="get_workspace_file_contents", path=path)


@mcp_tool(write_action=False)
async def get_workspace_files_contents(
    full_name: str,
    ref: str = "main",
    paths: list[str] | None = None,
    *,
    expand_globs: bool = True,
    max_chars_per_file: int = 20000,
    max_total_chars: int = 120000,
    include_missing: bool = True,
) -> dict[str, Any]:
    """Read multiple files from the persistent repo mirror in one call.

    This tool is optimized for examination workflows where a client wants to
    inspect several files (optionally via glob patterns) without issuing many
    per-file calls.

    Notes:
      - All paths are repository-relative.
      - When expand_globs is true, glob patterns (e.g. "src/**/*.py") are
        expanded relative to the repo root.
      - max_chars_per_file and max_total_chars are accepted for compatibility
        but are not enforced as truncation limits.
    """

    try:
        if paths is None:
            paths = []
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            raise TypeError("paths must be a list of strings")
        if not paths:
            raise ValueError("paths must contain at least one path")
        if not isinstance(max_chars_per_file, int) or max_chars_per_file < 1:
            raise ValueError("max_chars_per_file must be an int >= 1")
        if not isinstance(max_total_chars, int) or max_total_chars < 1:
            raise ValueError("max_total_chars must be an int >= 1")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        expanded: list[str] = []
        for raw in paths:
            p = (raw or "").strip().replace("\\", "/")
            if not p:
                continue
            if expand_globs and any(ch in p for ch in ("*", "?", "[")):
                pat_abs = _workspace_safe_join(repo_dir, p)
                matches = glob.glob(pat_abs, recursive=True)
                for m in matches:
                    try:
                        rel = os.path.relpath(m, repo_dir).replace("\\", "/")
                        _workspace_safe_join(repo_dir, rel)
                        expanded.append(rel)
                    except Exception:
                        continue
            else:
                _workspace_safe_join(repo_dir, p)
                expanded.append(p.lstrip("/"))

        seen: set[str] = set()
        normalized_paths: list[str] = []
        for p in expanded:
            if p in seen:
                continue
            seen.add(p)
            normalized_paths.append(p)

        files: list[dict[str, Any]] = []
        missing: list[str] = []
        errors: list[dict[str, Any]] = []
        truncated = False
        remaining_total = int(max_total_chars)
        for p in normalized_paths:
            try:
                if remaining_total <= 0:
                    truncated = True
                    break
                per_file = min(int(max_chars_per_file), remaining_total)
                info = _workspace_read_text_limited(
                    repo_dir,
                    p,
                    max_chars=per_file,
                    max_bytes=max(_DEFAULT_MAX_READ_BYTES, per_file * 4),
                )
                if info.get("exists"):
                    files.append(info)
                    remaining_total -= len(info.get("text") or "")
                    if info.get("truncated"):
                        truncated = True
                else:
                    if include_missing:
                        files.append(info)
                    missing.append(p)
            except Exception as exc:
                errors.append({"path": p, "error": str(exc)})

        ok = len(errors) == 0
        status = "ok" if ok else "partial"

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "status": status,
            "ok": ok,
            "expanded_globs": bool(expand_globs),
            "max_chars_per_file": int(max_chars_per_file),
            "max_total_chars": int(max_total_chars),
            "summary": {
                "requested": len(paths),
                "resolved": len(normalized_paths),
                "returned": len(files),
                "missing": len(missing),
                "errors": len(errors),
                "total_chars": sum(len(f.get("text") or "") for f in files),
                "truncated": bool(truncated),
            },
            "files": files,
            "missing_paths": missing,
            "errors": errors,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="get_workspace_files_contents")


@mcp_tool(write_action=False)
async def read_workspace_file_excerpt(
    full_name: str,
    ref: str = "main",
    path: str = "",
    *,
    start_line: int = 1,
    max_lines: int = 200,
    max_chars: int = 80_000,
) -> dict[str, Any]:
    """Read an excerpt of a file with line numbers (safe for very large files).

    Unlike get_workspace_file_contents, this reads only the requested line range
    and returns a structured list of {line, text} entries.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(start_line, int) or start_line < 1:
            raise ValueError("start_line must be an int >= 1")
        if not isinstance(max_lines, int) or max_lines < 1:
            raise ValueError("max_lines must be an int >= 1")
        if not isinstance(max_chars, int) or max_chars < 1:
            raise ValueError("max_chars must be an int >= 1")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        abs_path = _workspace_safe_join(repo_dir, path)
        if not os.path.exists(abs_path):
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": path,
                "exists": False,
                "excerpt": {
                    "start_line": int(start_line),
                    "end_line": int(start_line),
                    "lines": [],
                    "truncated": False,
                    "max_lines": int(max_lines),
                    "max_chars": int(max_chars),
                },
            }

        if os.path.isdir(abs_path):
            raise IsADirectoryError(path)
        if _is_probably_binary(abs_path):
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": path,
                "exists": True,
                "is_binary": True,
                "size_bytes": os.path.getsize(abs_path),
                "excerpt": {
                    "start_line": int(start_line),
                    "end_line": int(start_line),
                    "lines": [],
                    "truncated": False,
                    "max_lines": int(max_lines),
                    "max_chars": int(max_chars),
                },
            }

        excerpt = _read_lines_excerpt(
            abs_path,
            start_line=int(start_line),
            max_lines=int(max_lines),
            max_chars=int(max_chars),
        )
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": path,
            "exists": True,
            "is_binary": False,
            "size_bytes": os.path.getsize(abs_path),
            "excerpt": excerpt,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="read_workspace_file_excerpt", path=path)


@mcp_tool(write_action=False)
async def read_workspace_file_sections(
    full_name: str,
    ref: str = "main",
    path: str = "",
    *,
    start_line: int = 1,
    max_sections: int = 5,
    max_lines_per_section: int = 200,
    max_chars_per_section: int = 80_000,
    overlap_lines: int = 20,
) -> dict[str, Any]:
    """Read a file as multiple "parts" with real line numbers.

    This is the multi-part companion to `read_workspace_file_excerpt`.
    It chunks a file into `max_sections` parts (each bounded by
    `max_lines_per_section` and `max_chars_per_section`) starting at
    `start_line`.

    The response includes `next_start_line` when the file was truncated, so
    callers can page.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(start_line, int) or start_line < 1:
            raise ValueError("start_line must be an int >= 1")
        if not isinstance(max_sections, int) or max_sections < 1:
            raise ValueError("max_sections must be an int >= 1")
        if not isinstance(max_lines_per_section, int) or max_lines_per_section < 1:
            raise ValueError("max_lines_per_section must be an int >= 1")
        if not isinstance(max_chars_per_section, int) or max_chars_per_section < 1:
            raise ValueError("max_chars_per_section must be an int >= 1")
        if not isinstance(overlap_lines, int) or overlap_lines < 0:
            raise ValueError("overlap_lines must be an int >= 0")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        abs_path = _workspace_safe_join(repo_dir, path)
        if not os.path.exists(abs_path):
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": path,
                "exists": False,
                "sections": {
                    "start_line": int(start_line),
                    "end_line": int(start_line),
                    "parts": [],
                    "truncated": False,
                    "next_start_line": None,
                    "max_sections": int(max_sections),
                    "max_lines_per_section": int(max_lines_per_section),
                    "max_chars_per_section": int(max_chars_per_section),
                    "overlap_lines": int(overlap_lines),
                    "had_decoding_errors": False,
                },
            }

        if os.path.isdir(abs_path):
            raise IsADirectoryError(path)
        if _is_probably_binary(abs_path):
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": path,
                "exists": True,
                "is_binary": True,
                "size_bytes": os.path.getsize(abs_path),
                "sections": {
                    "start_line": int(start_line),
                    "end_line": int(start_line),
                    "parts": [],
                    "truncated": False,
                    "next_start_line": None,
                    "max_sections": int(max_sections),
                    "max_lines_per_section": int(max_lines_per_section),
                    "max_chars_per_section": int(max_chars_per_section),
                    "overlap_lines": int(overlap_lines),
                    "had_decoding_errors": False,
                },
            }

        sections = _read_lines_sections(
            abs_path,
            start_line=int(start_line),
            max_sections=int(max_sections),
            max_lines_per_section=int(max_lines_per_section),
            max_chars_per_section=int(max_chars_per_section),
            overlap_lines=int(overlap_lines),
        )
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": path,
            "exists": True,
            "is_binary": False,
            "size_bytes": os.path.getsize(abs_path),
            "sections": sections,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="read_workspace_file_sections", path=path)


def _git_show_lines_excerpt_limited(
    repo_dir: str,
    *,
    git_ref: str,
    path: str,
    start_line: int,
    max_lines: int,
    max_chars: int,
) -> tuple[bool, list[dict[str, Any]], bool, str | None]:
    """Stream `git show <git_ref>:<path>` and return a line-numbered excerpt.

    Returns:
      (exists, lines, truncated, error)
    """
    if start_line < 1:
        start_line = 1
    if max_lines < 1:
        max_lines = 1
    if max_chars < 1:
        max_chars = 1

    cmd = ["git", "show", f"{git_ref}:{path}"]
    proc = subprocess.Popen(
        cmd,
        cwd=repo_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )

    lines: list[dict[str, Any]] = []
    truncated = False
    chars = 0
    line_no = 0
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line_no += 1
            if line_no < start_line:
                continue
            text = raw.rstrip("\n")
            next_chars = chars + len(text) + 1
            if next_chars > max_chars:
                truncated = True
                break
            lines.append({"line": line_no, "text": text})
            chars = next_chars
            if len(lines) >= max_lines:
                truncated = True
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            _, stderr = proc.communicate(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            _, stderr = proc.communicate()

    if proc.returncode != 0:
        err = (stderr or "").strip() or None
        return False, [], False, err
    return True, lines, truncated, None


def _git_show_lines_sections_limited(
    repo_dir: str,
    *,
    git_ref: str,
    path: str,
    start_line: int,
    max_sections: int,
    max_lines_per_section: int,
    max_chars_per_section: int,
    overlap_lines: int,
) -> tuple[bool, dict[str, Any], str | None]:
    """Stream `git show <git_ref>:<path>` and return chunked sections.

    Returns: (exists, sections, error)
    """

    if start_line < 1:
        start_line = 1
    if max_sections < 1:
        max_sections = 1
    if max_lines_per_section < 1:
        max_lines_per_section = 1
    if max_chars_per_section < 1:
        max_chars_per_section = 1
    if overlap_lines < 0:
        overlap_lines = 0

    cmd = ["git", "show", f"{git_ref}:{path}"]
    proc = subprocess.Popen(
        cmd,
        cwd=repo_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )

    sections: dict[str, Any]
    try:
        assert proc.stdout is not None
        sections = _sections_from_line_iter(
            proc.stdout,
            start_line=int(start_line),
            max_sections=int(max_sections),
            max_lines_per_section=int(max_lines_per_section),
            max_chars_per_section=int(max_chars_per_section),
            overlap_lines=int(overlap_lines),
        )
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            _, stderr = proc.communicate(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            _, stderr = proc.communicate()

    if proc.returncode != 0:
        err = (stderr or "").strip() or None
        return (
            False,
            {
                "start_line": int(start_line),
                "end_line": int(start_line),
                "parts": [],
                "truncated": False,
                "next_start_line": None,
                "max_sections": int(max_sections),
                "max_lines_per_section": int(max_lines_per_section),
                "max_chars_per_section": int(max_chars_per_section),
                "overlap_lines": int(overlap_lines),
                "had_decoding_errors": False,
            },
            err,
        )

    return True, sections, None


@mcp_tool(write_action=False)
async def read_git_file_excerpt(
    full_name: str,
    ref: str = "main",
    path: str = "",
    *,
    git_ref: str = "HEAD",
    start_line: int = 1,
    max_lines: int = 200,
    max_chars: int = 80_000,
) -> dict[str, Any]:
    """Read an excerpt of a file as it exists at a git ref, with line numbers.

    Uses the local workspace mirror and `git show` so callers can inspect
    historical versions without changing the checkout.

    Line numbers are 1-indexed and correspond to the file at `git_ref`.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(git_ref, str) or not git_ref.strip():
            raise ValueError("git_ref must be a non-empty string")
        if not isinstance(start_line, int) or start_line < 1:
            raise ValueError("start_line must be an int >= 1")
        if not isinstance(max_lines, int) or max_lines < 1:
            raise ValueError("max_lines must be an int >= 1")
        if not isinstance(max_chars, int) or max_chars < 1:
            raise ValueError("max_chars must be an int >= 1")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        exists, lines, truncated, error = _git_show_lines_excerpt_limited(
            repo_dir,
            git_ref=git_ref.strip(),
            path=path.strip(),
            start_line=int(start_line),
            max_lines=int(max_lines),
            max_chars=int(max_chars),
        )
        if not exists:
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": path,
                "git_ref": git_ref,
                "exists": False,
                "error": error,
            }

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": path,
            "git_ref": git_ref,
            "exists": True,
            "excerpt": {
                "start_line": int(start_line),
                "end_line": (lines[-1]["line"] if lines else int(start_line)),
                "lines": lines,
                "truncated": bool(truncated),
                "max_lines": int(max_lines),
                "max_chars": int(max_chars),
            },
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="read_git_file_excerpt",
            path=path,
            git_ref=git_ref,
        )


@mcp_tool(write_action=False)
async def read_git_file_sections(
    full_name: str,
    ref: str = "main",
    path: str = "",
    *,
    git_ref: str = "HEAD",
    start_line: int = 1,
    max_sections: int = 5,
    max_lines_per_section: int = 200,
    max_chars_per_section: int = 80_000,
    overlap_lines: int = 20,
) -> dict[str, Any]:
    """Read a file at a git ref as multiple parts with real line numbers.

    This is the multi-part companion to `read_git_file_excerpt`.
    It uses `git show <git_ref>:<path>` streamed from the local workspace
    mirror, so line numbers correspond to the file at `git_ref`.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(git_ref, str) or not git_ref.strip():
            raise ValueError("git_ref must be a non-empty string")
        if not isinstance(start_line, int) or start_line < 1:
            raise ValueError("start_line must be an int >= 1")
        if not isinstance(max_sections, int) or max_sections < 1:
            raise ValueError("max_sections must be an int >= 1")
        if not isinstance(max_lines_per_section, int) or max_lines_per_section < 1:
            raise ValueError("max_lines_per_section must be an int >= 1")
        if not isinstance(max_chars_per_section, int) or max_chars_per_section < 1:
            raise ValueError("max_chars_per_section must be an int >= 1")
        if not isinstance(overlap_lines, int) or overlap_lines < 0:
            raise ValueError("overlap_lines must be an int >= 0")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        exists, sections, error = _git_show_lines_sections_limited(
            repo_dir,
            git_ref=git_ref.strip(),
            path=path.strip(),
            start_line=int(start_line),
            max_sections=int(max_sections),
            max_lines_per_section=int(max_lines_per_section),
            max_chars_per_section=int(max_chars_per_section),
            overlap_lines=int(overlap_lines),
        )

        if not exists:
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": path,
                "git_ref": git_ref,
                "exists": False,
                "error": error,
                "sections": sections,
            }

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": path,
            "git_ref": git_ref,
            "exists": True,
            "sections": sections,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="read_git_file_sections",
            path=path,
            git_ref=git_ref,
        )


@mcp_tool(write_action=False)
async def compare_workspace_files(
    full_name: str,
    ref: str = "main",
    comparisons: list[dict[str, Any]] | None = None,
    *,
    context_lines: int = 3,
    max_chars_per_side: int = 200000,
    max_diff_chars: int = 200000,
    include_stats: bool = False,
) -> dict[str, Any]:
    """Compare multiple file pairs or ref/path variants and return diffs.

    Each entry in `comparisons` supports one of the following shapes:
      1) {"left_path": "a.txt", "right_path": "b.txt"}
         Compares two workspace paths.
      2) {"path": "a.txt", "base_ref": "main"}
         Compares the workspace file at `path` (current checkout) to the file
         content at `base_ref:path` via `git show`.
      3) {"left_ref": "main", "left_path": "a.txt", "right_ref": "feature", "right_path": "a.txt"}
         Compares two git object versions without changing checkout.

    Returned diffs are unified diffs with full file contents.

    If include_stats is true, each comparison result includes a "stats" object
    with {added, removed} line counts derived from the full unified diff.
    """

    try:
        if comparisons is None:
            comparisons = []
        if not isinstance(comparisons, list) or any(not isinstance(c, dict) for c in comparisons):
            raise TypeError("comparisons must be a list of dicts")
        if not comparisons:
            raise ValueError("comparisons must contain at least one item")
        if not isinstance(context_lines, int) or context_lines < 0:
            raise ValueError("context_lines must be an int >= 0")
        if not isinstance(max_chars_per_side, int) or max_chars_per_side < 1:
            raise ValueError("max_chars_per_side must be an int >= 1")
        if not isinstance(max_diff_chars, int) or max_diff_chars < 1:
            raise ValueError("max_diff_chars must be an int >= 1")
        include_stats = bool(include_stats)

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        out: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for idx, spec in enumerate(comparisons):
            try:
                left_truncated = False
                right_truncated = False
                left_ref = spec.get("left_ref")
                right_ref = spec.get("right_ref")
                left_path = spec.get("left_path") or spec.get("path")
                right_path = spec.get("right_path")

                base_ref = spec.get("base_ref")
                if base_ref is not None and right_ref is None and right_path is None:
                    # Workspace path vs git ref:path.
                    if not isinstance(left_path, str) or not left_path.strip():
                        raise ValueError("path must be a non-empty string")
                    if not isinstance(base_ref, str) or not base_ref.strip():
                        raise ValueError("base_ref must be a non-empty string")

                    ws = _workspace_read_text_limited(
                        repo_dir, left_path, max_chars=max_chars_per_side
                    )
                    base = _git_show_text_limited(
                        repo_dir,
                        base_ref,
                        left_path,
                        max_chars=max_chars_per_side,
                    )
                    if not base.get("exists"):
                        raise FileNotFoundError(f"missing at {base_ref}:{left_path}")
                    left_text = base.get("text") or ""
                    right_text = ws.get("text") or ""
                    left_truncated = bool(base.get("truncated"))
                    right_truncated = bool(ws.get("truncated"))
                    fromfile = f"a/{left_path} ({_sanitize_git_ref(base_ref)})"
                    tofile = f"b/{left_path} ({effective_ref})"
                    partial = False
                elif left_ref is not None or right_ref is not None:
                    # git ref:path vs git ref:path.
                    if not isinstance(left_ref, str) or not left_ref.strip():
                        raise ValueError("left_ref must be a non-empty string")
                    if not isinstance(right_ref, str) or not right_ref.strip():
                        raise ValueError("right_ref must be a non-empty string")
                    if not isinstance(left_path, str) or not left_path.strip():
                        raise ValueError("left_path must be a non-empty string")
                    if not isinstance(right_path, str) or not right_path.strip():
                        raise ValueError("right_path must be a non-empty string")

                    left_info = _git_show_text_limited(
                        repo_dir,
                        left_ref,
                        left_path,
                        max_chars=max_chars_per_side,
                    )
                    right_info = _git_show_text_limited(
                        repo_dir,
                        right_ref,
                        right_path,
                        max_chars=max_chars_per_side,
                    )
                    if not left_info.get("exists"):
                        raise FileNotFoundError(f"missing at {left_ref}:{left_path}")
                    if not right_info.get("exists"):
                        raise FileNotFoundError(f"missing at {right_ref}:{right_path}")
                    left_text = left_info.get("text") or ""
                    right_text = right_info.get("text") or ""
                    left_truncated = bool(left_info.get("truncated"))
                    right_truncated = bool(right_info.get("truncated"))
                    fromfile = f"a/{left_path} ({_sanitize_git_ref(left_ref)})"
                    tofile = f"b/{right_path} ({_sanitize_git_ref(right_ref)})"
                    partial = False
                else:
                    # Workspace path vs workspace path.
                    if not isinstance(left_path, str) or not left_path.strip():
                        raise ValueError("left_path must be a non-empty string")
                    if not isinstance(right_path, str) or not right_path.strip():
                        raise ValueError("right_path must be a non-empty string")
                    left_info = _workspace_read_text_limited(
                        repo_dir, left_path, max_chars=max_chars_per_side
                    )
                    right_info = _workspace_read_text_limited(
                        repo_dir, right_path, max_chars=max_chars_per_side
                    )
                    if not left_info.get("exists"):
                        raise FileNotFoundError(left_path)
                    if not right_info.get("exists"):
                        raise FileNotFoundError(right_path)
                    left_text = left_info.get("text") or ""
                    right_text = right_info.get("text") or ""
                    left_truncated = bool(left_info.get("truncated"))
                    right_truncated = bool(right_info.get("truncated"))
                    fromfile = f"a/{left_path}"
                    tofile = f"b/{right_path}"
                    partial = False

                diff_full = build_unified_diff(
                    left_text,
                    right_text,
                    fromfile=fromfile,
                    tofile=tofile,
                    n=int(context_lines),
                )
                if not diff_full:
                    diff_full = ""

                # Mark partial when either side was truncated.
                partial = bool(partial) or bool(left_truncated or right_truncated)

                truncated = False
                if diff_full and len(diff_full) > int(max_diff_chars):
                    diff_full = diff_full[: int(max_diff_chars)]
                    truncated = True
                    partial = True

                stats_obj: dict[str, int] | None = None
                if include_stats:
                    if diff_full:
                        ds = diff_stats(diff_full)
                        stats_obj = {"added": int(ds.added), "removed": int(ds.removed)}
                    else:
                        stats_obj = {"added": 0, "removed": 0}

                out.append(
                    {
                        "index": idx,
                        "status": "ok",
                        "partial": bool(partial),
                        "truncated": bool(truncated),
                        **({"stats": stats_obj} if include_stats else {}),
                        "diff": diff_full,
                    }
                )
            except Exception as exc:
                errors.append({"index": idx, "error": str(exc), "spec": spec})
                out.append({"index": idx, "status": "error", "error": str(exc)})

        ok = len(errors) == 0
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "status": "ok" if ok else "partial",
            "ok": ok,
            "comparisons": out,
            "errors": errors,
            "limits": {
                "context_lines": int(context_lines),
                "max_chars_per_side": int(max_chars_per_side),
                "max_diff_chars": int(max_diff_chars),
                "include_stats": bool(include_stats),
            },
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="compare_workspace_files")


async def _build_workspace_diff_payload(
    *,
    full_name: str,
    ref: str,
    path: str | None,
    before: str | None,
    after: str | None,
    updated_content: str | None,
    context_lines: int,
    max_chars_per_side: int,
    max_diff_chars: int,
    fromfile: str | None,
    tofile: str | None,
) -> dict[str, Any]:
    if not isinstance(context_lines, int) or context_lines < 0:
        raise ValueError("context_lines must be an int >= 0")
    if not isinstance(max_chars_per_side, int) or max_chars_per_side < 1:
        raise ValueError("max_chars_per_side must be an int >= 1")
    if not isinstance(max_diff_chars, int) or max_diff_chars < 1:
        raise ValueError("max_diff_chars must be an int >= 1")

    meta: dict[str, Any] = {
        "context_lines": int(context_lines),
        "max_diff_chars": int(max_diff_chars),
    }

    if path is not None and path != "":
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string when provided")
        if updated_content is None:
            raise ValueError("updated_content must be provided when path is set")
        if not isinstance(updated_content, str):
            raise TypeError("updated_content must be a string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        before_info = _workspace_read_text_limited(repo_dir, path, max_chars=max_chars_per_side)
        before_text = (before_info.get("text") or "") if before_info.get("exists") else ""
        before_exists = bool(before_info.get("exists"))
        before_label = fromfile or (f"a/{path}" if before_exists else "/dev/null")
        after_label = tofile or f"b/{path}"

        meta.update(
            {
                "ref": effective_ref,
                "path": path,
                "before_exists": before_exists,
                "before_truncated": bool(before_info.get("truncated")),
                "max_chars_per_side": int(max_chars_per_side),
            }
        )
        before = before_text
        after = updated_content
    else:
        if before is None or after is None:
            raise ValueError("before and after must be provided when path is not set")
        if not isinstance(before, str) or not isinstance(after, str):
            raise TypeError("before and after must be strings")
        before_label = fromfile or "before"
        after_label = tofile or "after"

    diff_text = build_unified_diff(
        before,
        after,
        fromfile=before_label,
        tofile=after_label,
        n=int(context_lines),
    )
    truncated = False
    if len(diff_text) > int(max_diff_chars):
        diff_text = diff_text[: int(max_diff_chars)]
        truncated = True

    stats = diff_stats(diff_text)
    meta.update(
        {
            "diff": diff_text,
            "diff_stats": {"added": stats.added, "removed": stats.removed},
            "truncated": bool(truncated),
        }
    )
    return meta


@mcp_tool(write_action=False)
async def make_workspace_diff(
    full_name: str,
    ref: str = "main",
    *,
    path: str | None = None,
    before: str | None = None,
    after: str | None = None,
    updated_content: str | None = None,
    context_lines: int = 3,
    max_chars_per_side: int = 200_000,
    max_diff_chars: int = 200_000,
    fromfile: str | None = None,
    tofile: str | None = None,
) -> dict[str, Any]:
    """Build a unified diff from workspace content or provided text."""

    try:
        return await _build_workspace_diff_payload(
            full_name=full_name,
            ref=ref,
            path=path,
            before=before,
            after=after,
            updated_content=updated_content,
            context_lines=context_lines,
            max_chars_per_side=max_chars_per_side,
            max_diff_chars=max_diff_chars,
            fromfile=fromfile,
            tofile=tofile,
        )
    except Exception as exc:
        return _structured_tool_error(exc, context="make_workspace_diff", path=path)


@mcp_tool(write_action=False)
async def make_workspace_patch(
    full_name: str,
    ref: str = "main",
    *,
    path: str | None = None,
    before: str | None = None,
    after: str | None = None,
    updated_content: str | None = None,
    context_lines: int = 3,
    max_chars_per_side: int = 200_000,
    max_diff_chars: int = 200_000,
    fromfile: str | None = None,
    tofile: str | None = None,
) -> dict[str, Any]:
    """Build a unified diff patch from workspace content or provided text."""

    try:
        payload = await _build_workspace_diff_payload(
            full_name=full_name,
            ref=ref,
            path=path,
            before=before,
            after=after,
            updated_content=updated_content,
            context_lines=context_lines,
            max_chars_per_side=max_chars_per_side,
            max_diff_chars=max_diff_chars,
            fromfile=fromfile,
            tofile=tofile,
        )
        patch = payload.pop("diff", "")
        payload["patch"] = patch
        return payload
    except Exception as exc:
        return _structured_tool_error(exc, context="make_workspace_patch", path=path)


@mcp_tool(write_action=True)
async def set_workspace_file_contents(
    full_name: str,
    ref: str = "main",
    path: str = "",
    content: str = "",
    create_parents: bool = True,
) -> dict[str, Any]:
    """Replace a workspace file's contents by writing the full file text.

    This is a good fit for repo-mirror edits when you want to replace the full
    contents of a file without relying on unified-diff patch application.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise TypeError("content must be a string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)

        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        before_info = _workspace_read_text(repo_dir, path)
        before_text = (before_info.get("text") or "") if before_info.get("exists") else ""
        write_info = _workspace_write_text(
            repo_dir,
            path,
            content,
            create_parents=create_parents,
        )

        log_diff = _maybe_diff_for_log(
            path=path,
            before=before_text,
            after=content,
            before_exists=bool(before_info.get("exists")),
        )

        return {
            "ref": effective_ref,
            "status": "written",
            "__log_diff": log_diff,
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="set_workspace_file_contents", path=path)


@mcp_tool(write_action=True)
async def edit_workspace_text_range(
    full_name: str,
    ref: str = "main",
    path: str = "",
    start_line: int = 1,
    start_col: int = 1,
    end_line: int = 1,
    end_col: int = 1,
    replacement: str = "",
    create_parents: bool = True,
) -> dict[str, Any]:
    """Edit a file by replacing a precise (line, column) text range.

    This is the most granular edit primitive:
      - Single-character edit: start=(L,C), end=(L,C+1)
      - Word edit: start/end wrap the word
      - Line edit: start=(L,1), end=(L+1,1) (includes the newline)

    Positions are 1-indexed. The end position is *exclusive* (Python-slice
    semantics).
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if replacement is None:
            replacement = ""
        if not isinstance(replacement, str):
            raise TypeError("replacement must be a string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        if not info.get("exists"):
            raise FileNotFoundError(path)

        original = info.get("text") or ""
        lines = _split_lines_keepends(original)

        start_offset = _pos_to_offset(lines, int(start_line), int(start_col))
        end_offset = _pos_to_offset(lines, int(end_line), int(end_col))
        if end_offset < start_offset:
            raise ValueError("end position must be after or equal to start position")

        updated = original[:start_offset] + replacement + original[end_offset:]
        write_info = _workspace_write_text(
            repo_dir,
            path,
            updated,
            create_parents=create_parents,
        )

        log_diff = _maybe_diff_for_log(
            path=path,
            before=original,
            after=updated,
            before_exists=True,
        )

        return {
            "ref": effective_ref,
            "status": "edited",
            "path": path,
            "start": {"line": int(start_line), "col": int(start_col)},
            "end": {"line": int(end_line), "col": int(end_col)},
            "bytes_before": len(original.encode("utf-8")),
            "bytes_after": len(updated.encode("utf-8")),
            "__log_diff": log_diff,
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="edit_workspace_text_range",
            path=path,
            start_line=start_line,
            start_col=start_col,
            end_line=end_line,
            end_col=end_col,
        )


@mcp_tool(write_action=True)
async def delete_workspace_lines(
    full_name: str,
    ref: str = "main",
    path: str = "",
    start_line: int = 1,
    end_line: int = 1,
    create_parents: bool = True,
) -> dict[str, Any]:
    """Delete one or more whole lines from a workspace file.

    Line numbers are 1-indexed and inclusive. Deleting a single line is the same
    as setting start_line=end_line.

    This is a convenience wrapper over edit_workspace_text_range where the range
    spans complete lines (including their newline when present).
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(start_line, int) or start_line < 1:
            raise ValueError("start_line must be an int >= 1")
        if not isinstance(end_line, int) or end_line < 1:
            raise ValueError("end_line must be an int >= 1")
        if end_line < start_line:
            raise ValueError("end_line must be >= start_line")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        if not info.get("exists"):
            raise FileNotFoundError(path)

        original = info.get("text") or ""
        lines = _split_lines_keepends(original)
        if not lines:
            raise ValueError("cannot delete lines from an empty file")
        if start_line > len(lines) or end_line > len(lines):
            raise ValueError("line range out of bounds")

        start_offset = _pos_to_offset(lines, int(start_line), 1)
        if end_line < len(lines):
            end_offset = _pos_to_offset(lines, int(end_line) + 1, 1)
        else:
            end_offset = _pos_to_offset(lines, len(lines) + 1, 1)

        removed = original[start_offset:end_offset]
        updated = original[:start_offset] + original[end_offset:]

        write_info = _workspace_write_text(
            repo_dir,
            path,
            updated,
            create_parents=create_parents,
        )

        return {
            "ref": effective_ref,
            "status": "edited",
            "path": path,
            "operation": "delete_lines",
            "start_line": int(start_line),
            "end_line": int(end_line),
            "removed": removed,
            "line_count_before": len(lines),
            "line_count_after": len(_split_lines_keepends(updated)),
            "__log_diff": _maybe_diff_for_log(
                path=path,
                before=original,
                after=updated,
                before_exists=True,
            ),
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="delete_workspace_lines",
            path=path,
            start_line=start_line,
            end_line=end_line,
        )


@mcp_tool(write_action=True)
async def delete_workspace_char(
    full_name: str,
    ref: str = "main",
    path: str = "",
    line: int = 1,
    col: int = 1,
    count: int = 1,
    create_parents: bool = True,
) -> dict[str, Any]:
    """Delete one or more characters starting at a (line, col) position.

    Positions are 1-indexed. `count` is measured in Python string characters.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(line, int) or line < 1:
            raise ValueError("line must be an int >= 1")
        if not isinstance(col, int) or col < 1:
            raise ValueError("col must be an int >= 1")
        if not isinstance(count, int) or count < 1:
            raise ValueError("count must be an int >= 1")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        if not info.get("exists"):
            raise FileNotFoundError(path)

        original = info.get("text") or ""
        lines = _split_lines_keepends(original)
        start_offset = _pos_to_offset(lines, int(line), int(col))
        end_offset = start_offset + int(count)
        if end_offset > len(original):
            raise ValueError("delete range extends beyond end of file")

        removed = original[start_offset:end_offset]
        updated = original[:start_offset] + original[end_offset:]

        write_info = _workspace_write_text(
            repo_dir,
            path,
            updated,
            create_parents=create_parents,
        )

        return {
            "ref": effective_ref,
            "status": "edited",
            "path": path,
            "operation": "delete_char",
            "start": {"line": int(line), "col": int(col)},
            "count": int(count),
            "removed": removed,
            "bytes_before": len(original.encode("utf-8")),
            "bytes_after": len(updated.encode("utf-8")),
            "__log_diff": _maybe_diff_for_log(
                path=path,
                before=original,
                after=updated,
                before_exists=True,
            ),
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="delete_workspace_char",
            path=path,
            line=line,
            col=col,
            count=count,
        )


@mcp_tool(write_action=True)
async def delete_workspace_word(
    full_name: str,
    ref: str = "main",
    path: str = "",
    word: str = "",
    occurrence: int = 1,
    replace_all: bool = False,
    case_sensitive: bool = True,
    whole_word: bool = True,
    create_parents: bool = True,
) -> dict[str, Any]:
    """Delete a word (or substring) from a workspace file.

    - occurrence is 1-indexed (ignored when replace_all=True)
    - when whole_word=True, word boundaries (\b) are used
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(word, str) or word == "":
            raise ValueError("word must be a non-empty string")
        if not isinstance(occurrence, int) or occurrence < 1:
            raise ValueError("occurrence must be an int >= 1")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        if not info.get("exists"):
            raise FileNotFoundError(path)

        original = info.get("text") or ""
        flags = 0 if case_sensitive else re.IGNORECASE
        pat = re.escape(word)
        if whole_word:
            pat = r"\b" + pat + r"\b"

        matches = list(re.finditer(pat, original, flags))
        if not matches:
            updated = original
            removed = ""
            removed_span = None
        elif replace_all:
            removed = ""  # potentially multiple
            removed_span = None
            updated = re.sub(pat, "", original, flags=flags)
        else:
            idx = min(len(matches), occurrence) - 1
            if idx < 0 or idx >= len(matches):
                updated = original
                removed = ""
                removed_span = None
            else:
                m = matches[idx]
                removed = m.group(0)
                removed_span = {"start": m.start(), "end": m.end()}
                updated = original[: m.start()] + original[m.end() :]

        write_info = _workspace_write_text(
            repo_dir,
            path,
            updated,
            create_parents=create_parents,
        )

        status = "edited" if updated != original else "noop"
        return {
            "ref": effective_ref,
            "status": status,
            "path": path,
            "operation": "delete_word",
            "word": word,
            "occurrence": int(occurrence),
            "replace_all": bool(replace_all),
            "case_sensitive": bool(case_sensitive),
            "whole_word": bool(whole_word),
            "removed": removed,
            "removed_span": removed_span,
            "__log_diff": _maybe_diff_for_log(
                path=path,
                before=original,
                after=updated,
                before_exists=True,
            ),
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="delete_workspace_word",
            path=path,
            word=word,
            occurrence=occurrence,
            replace_all=replace_all,
        )


@mcp_tool(write_action=True)
async def edit_workspace_line(
    full_name: str,
    ref: str = "main",
    path: str = "",
    operation: Literal["replace", "insert_before", "insert_after", "delete"] = "replace",
    line_number: int = 1,
    text: str = "",
    create_parents: bool = True,
) -> dict[str, Any]:
    """Edit a single line in a workspace file.

    Operations:
      - replace: replace the target line's content (preserves its line ending).
      - insert_before / insert_after: insert a new line adjacent to line_number.
      - delete: delete the target line.

    Line numbers are 1-indexed.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if operation not in ("replace", "insert_before", "insert_after", "delete"):
            raise ValueError("operation must be replace/insert_before/insert_after/delete")
        if not isinstance(line_number, int) or line_number < 1:
            raise ValueError("line_number must be an int >= 1")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        if not info.get("exists"):
            raise FileNotFoundError(path)

        original = info.get("text") or ""
        lines = _split_lines_keepends(original)
        eol = _infer_eol_from_lines(lines)

        if line_number > max(1, len(lines)):
            raise ValueError("line_number out of range")

        def _ensure_eol(s: str) -> str:
            if s.endswith("\r\n") or s.endswith("\n") or s.endswith("\r"):
                return s
            return s + eol

        idx = line_number - 1

        if operation == "delete":
            if not lines:
                raise ValueError("cannot delete from an empty file")
            removed = lines.pop(idx)
            updated_lines = lines
            updated = "".join(updated_lines)
            write_info = _workspace_write_text(
                repo_dir,
                path,
                updated,
                create_parents=create_parents,
            )
            return {
                "ref": effective_ref,
                "status": "edited",
                "path": path,
                "operation": operation,
                "line_number": line_number,
                "removed": removed,
                "line_count_before": len(_split_lines_keepends(original)),
                "line_count_after": len(updated_lines),
                "__log_diff": _maybe_diff_for_log(
                    path=path,
                    before=original,
                    after=updated,
                    before_exists=True,
                ),
                **write_info,
            }

        if operation in ("insert_before", "insert_after"):
            insert_at = idx if operation == "insert_before" else idx + 1
            payload = text
            payload = _ensure_eol(payload)
            lines.insert(insert_at, payload)
            updated = "".join(lines)
            write_info = _workspace_write_text(
                repo_dir,
                path,
                updated,
                create_parents=create_parents,
            )
            return {
                "ref": effective_ref,
                "status": "edited",
                "path": path,
                "operation": operation,
                "line_number": line_number,
                "inserted_at": insert_at + 1,
                "inserted": payload,
                "line_count_before": len(_split_lines_keepends(original)),
                "line_count_after": len(lines),
                "__log_diff": _maybe_diff_for_log(
                    path=path,
                    before=original,
                    after=updated,
                    before_exists=True,
                ),
                **write_info,
            }

        # replace
        if not lines:
            # Empty file: treat line 1 as replaceable.
            payload = _ensure_eol(text)
            updated = payload
        else:
            raw = lines[idx]
            _content, line_eol = _line_content_and_eol(raw)
            # Preserve the existing line ending (or fallback to inferred).
            effective_eol = line_eol or eol
            payload = text
            payload = payload.rstrip("\r\n")
            payload = payload + effective_eol if effective_eol else payload
            lines[idx] = payload
            updated = "".join(lines)

        write_info = _workspace_write_text(
            repo_dir,
            path,
            updated,
            create_parents=create_parents,
        )
        return {
            "ref": effective_ref,
            "status": "edited",
            "path": path,
            "operation": operation,
            "line_number": line_number,
            "line_count_before": len(_split_lines_keepends(original)),
            "line_count_after": len(_split_lines_keepends(updated)),
            "__log_diff": _maybe_diff_for_log(
                path=path,
                before=original,
                after=updated,
                before_exists=True,
            ),
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="edit_workspace_line",
            path=path,
            operation=operation,
            line_number=line_number,
        )


@mcp_tool(write_action=True)
async def replace_workspace_text(
    full_name: str,
    ref: str = "main",
    path: str = "",
    old: str = "",
    new: str = "",
    occurrence: int = 1,
    replace_all: bool = False,
    create_parents: bool = True,
) -> dict[str, Any]:
    """Replace text in a workspace file (single word/character or substring).

    By default, replaces the Nth occurrence (1-indexed). When replace_all=true,
    all occurrences are replaced.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(old, str) or old == "":
            raise ValueError("old must be a non-empty string")
        if new is None:
            new = ""
        if not isinstance(new, str):
            raise TypeError("new must be a string")
        if not isinstance(occurrence, int) or occurrence < 1:
            raise ValueError("occurrence must be an int >= 1")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        if not info.get("exists"):
            raise FileNotFoundError(path)

        original = info.get("text") or ""
        updated = original
        replaced = 0

        if replace_all:
            replaced = original.count(old)
            updated = original.replace(old, new)
        else:
            start = 0
            found_at = -1
            for _i in range(occurrence):
                found_at = original.find(old, start)
                if found_at == -1:
                    break
                start = found_at + len(old)
            if found_at != -1:
                replaced = 1
                updated = original[:found_at] + new + original[found_at + len(old) :]

        if replaced == 0:
            return {
                "ref": effective_ref,
                "status": "noop",
                "path": path,
                "replaced": 0,
                "replace_all": bool(replace_all),
                "occurrence": int(occurrence),
            }

        write_info = _workspace_write_text(
            repo_dir,
            path,
            updated,
            create_parents=create_parents,
        )

        return {
            "ref": effective_ref,
            "status": "replaced",
            "path": path,
            "replaced": replaced,
            "replace_all": bool(replace_all),
            "occurrence": int(occurrence),
            "__log_diff": _maybe_diff_for_log(
                path=path,
                before=original,
                after=updated,
                before_exists=True,
            ),
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="replace_workspace_text",
            path=path,
            occurrence=occurrence,
            replace_all=replace_all,
        )


async def _apply_patch_impl(
    *,
    full_name: str,
    ref: str,
    patch: str | list[str],
    add: bool,
    commit: bool,
    commit_message: str,
    push: bool,
    check_changes: bool,
    context: str,
) -> dict[str, Any]:
    debug_args: dict[str, Any] = {
        "full_name": full_name,
        "ref": ref,
        "add": bool(add),
        "commit": bool(commit),
        "push": bool(push),
        "check_changes": bool(check_changes),
    }

    try:
        if push and not commit:
            raise ValueError("push=true requires commit=true")

        # Normalize patch input.
        patches: list[str]
        if patch is None:
            raise ValueError("patch must be provided")
        if isinstance(patch, str):
            if not patch.strip():
                raise ValueError("patch must be a non-empty string")
            patches = [patch]
        elif isinstance(patch, list):
            if not patch:
                raise ValueError("patch must be a non-empty string or list of strings")
            if any(not isinstance(item, str) or not item.strip() for item in patch):
                raise ValueError("patch list entries must be non-empty strings")
            patches = patch
        else:
            raise ValueError("patch must be a non-empty string or list of strings")

        # Record patch digests for safe debugging.
        from github_mcp.diff_utils import diff_stats as _diff_stats
        from github_mcp.diff_utils import sha1_8

        patch_digests = [sha1_8(p) for p in patches]
        debug_args.update({"patches": len(patches), "patch_digests": patch_digests})

        # Only surface unified diffs for visual logs.
        diff_blobs = [p for p in patches if isinstance(p, str) and _looks_like_diff(p)]
        combined_diff = "\n".join(x.rstrip("\n") for x in diff_blobs).strip() if diff_blobs else ""
        if combined_diff and not combined_diff.endswith("\n"):
            combined_diff += "\n"

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        debug_args["effective_ref"] = effective_ref

        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        for patch_entry in patches:
            await deps["apply_patch_to_repo"](repo_dir, patch_entry)

        if add or commit:
            add_result = await deps["run_shell"]("git add -A", cwd=repo_dir)
            if add_result.get("exit_code") != 0:
                stderr = add_result.get("stderr", "") or add_result.get("stdout", "")
                raise ValueError(f"git add failed: {stderr}")

        status_result = None
        if check_changes or commit:
            status_result = await deps["run_shell"]("git status --porcelain", cwd=repo_dir)

        commit_result = None
        push_result = None
        if commit:
            if not isinstance(commit_message, str) or not commit_message.strip():
                raise ValueError("commit_message must be a non-empty string when commit is true")

            status_lines = (status_result.get("stdout", "") if status_result else "").strip()
            if not status_lines:
                raise ValueError("No changes to commit after applying patch")

            commit_cmd = f"git commit -m {shlex.quote(commit_message)}"
            commit_result = await deps["run_shell"](commit_cmd, cwd=repo_dir)
            if commit_result.get("exit_code") != 0:
                stderr = commit_result.get("stderr", "") or commit_result.get("stdout", "")
                raise ValueError(f"git commit failed: {stderr}")

            if push:
                # Disallow pushing from detached HEAD (e.g., when ref is a tag or commit SHA).
                head_ref = await deps["run_shell"](
                    "git symbolic-ref --quiet --short HEAD", cwd=repo_dir
                )
                branch_name = (head_ref.get("stdout", "") or "").strip()
                if head_ref.get("exit_code") != 0 or not branch_name:
                    raise ValueError(
                        "Cannot push from detached HEAD. Provide a branch ref (e.g. ref='main' or a feature branch)."
                    )

                # Push to the requested ref name.
                push_cmd = f"git push origin {shlex.quote(f'HEAD:{effective_ref}')}"
                push_result = await deps["run_shell"](push_cmd, cwd=repo_dir)
                if push_result.get("exit_code") != 0:
                    stderr = push_result.get("stderr", "") or push_result.get("stdout", "")
                    raise ValueError(f"git push failed: {stderr}")

        response: dict[str, Any] = {
            "ref": effective_ref,
            "status": "patched",
            "ok": True,
            "patches_applied": len(patches),
        }

        if combined_diff:
            stats = _diff_stats(combined_diff)
            response["diff_stats"] = {"added": stats.added, "removed": stats.removed}
            response["__log_diff"] = combined_diff

        if status_result is not None:
            response["status_output"] = (status_result.get("stdout", "") or "").strip()
        if commit_result is not None:
            response["commit"] = commit_result
        if push_result is not None:
            response["push"] = push_result
        return response

    except Exception as exc:
        return _structured_tool_error(exc, context=context, args=debug_args)


@mcp_tool(
    write_action=True,
    open_world_hint=True,
    destructive_hint=True,
    ui={
        "group": "workspace",
        "icon": "🧩",
        "label": "Apply Patch",
        "danger": "high",
    },
)
async def apply_patch(
    full_name: str,
    ref: str = "main",
    *,
    patch: str | list[str],
    add: bool = False,
    commit: bool = False,
    commit_message: str = "Apply patch",
    push: bool = False,
    check_changes: bool = False,
) -> dict[str, Any]:
    """Apply one or more unified diff patches to the persistent repo mirror.

    Args:
      patch: a unified diff string or a list of unified diff strings.
      add: if true, stage changes after applying.
      commit: if true, create a local commit after applying (requires changes).
      push: if true, push the created commit to origin (requires commit=true and a branch ref).
      check_changes: if true, include `status_output` (git status porcelain) in the response.

    Returns:
      A dict with stable keys: ref, status, ok, patches_applied (+ optional diff_stats/status_output).

    Notes:
      - Visual tool logs look for `__log_diff` in the *raw* tool payload. The decorator wrapper
        preserves `__log_*` fields in the client-facing response by default.
        Set ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS=1 to restore legacy stripping.
      - To avoid leaking patch contents in error responses, we only include short digests.
    """

    return await _apply_patch_impl(
        full_name=full_name,
        ref=ref,
        patch=patch,
        add=add,
        commit=commit,
        commit_message=commit_message,
        push=push,
        check_changes=check_changes,
        context="apply_patch",
    )


@mcp_tool(
    write_action=True,
    open_world_hint=True,
    destructive_hint=True,
    ui={
        "group": "workspace",
        "icon": "🧩",
        "label": "Apply Diff",
        "danger": "high",
    },
)
async def apply_workspace_diff(
    full_name: str,
    ref: str = "main",
    *,
    diff: str | list[str],
    add: bool = False,
    commit: bool = False,
    commit_message: str = "Apply diff",
    push: bool = False,
    check_changes: bool = False,
) -> dict[str, Any]:
    """Apply one or more unified diffs to the persistent repo mirror."""

    return await _apply_patch_impl(
        full_name=full_name,
        ref=ref,
        patch=diff,
        add=add,
        commit=commit,
        commit_message=commit_message,
        push=push,
        check_changes=check_changes,
        context="apply_workspace_diff",
    )


@mcp_tool(write_action=True)
async def move_workspace_paths(
    full_name: str,
    ref: str = "main",
    moves: list[dict[str, Any]] | None = None,
    overwrite: bool = False,
    create_parents: bool = True,
) -> dict[str, Any]:
    """Move (rename) one or more workspace paths inside the repo mirror.

    Args:
      moves: list of {"src": "path", "dst": "path"}
      overwrite: if true, allow replacing an existing destination.
    """

    if moves is None:
        moves = []
    if not isinstance(moves, list) or any(not isinstance(m, dict) for m in moves):
        raise TypeError("moves must be a list of dicts")
    if not moves:
        raise ValueError("moves must contain at least one item")

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        moved: list[dict[str, str]] = []
        failed: list[dict[str, Any]] = []

        for m in moves:
            src = m.get("src")
            dst = m.get("dst")
            if not isinstance(src, str) or not src.strip():
                failed.append({"src": src, "dst": dst, "error": "src must be a non-empty string"})
                continue
            if not isinstance(dst, str) or not dst.strip():
                failed.append({"src": src, "dst": dst, "error": "dst must be a non-empty string"})
                continue

            try:
                abs_src = _workspace_safe_join(repo_dir, src)
                abs_dst = _workspace_safe_join(repo_dir, dst)
                if not os.path.exists(abs_src):
                    raise FileNotFoundError(src)
                if os.path.exists(abs_dst):
                    if overwrite:
                        if os.path.isdir(abs_dst):
                            shutil.rmtree(abs_dst)
                        else:
                            os.remove(abs_dst)
                    else:
                        raise FileExistsError(dst)

                if create_parents:
                    os.makedirs(os.path.dirname(abs_dst), exist_ok=True)

                shutil.move(abs_src, abs_dst)
                moved.append({"src": src, "dst": dst})
            except Exception as exc:
                failed.append({"src": src, "dst": dst, "error": str(exc)})

        return {
            "ref": effective_ref,
            "status": "moved",
            "moved": moved,
            "failed": failed,
            "ok": len(failed) == 0,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="move_workspace_paths")


def _apply_workspace_operations_write_action_resolver(args: dict[str, Any] | None) -> bool:
    """Determine whether a specific call will mutate the workspace mirror.

    `apply_workspace_operations` supports read-only operations (for example
    `read_sections`) and `preview_only` mode that returns a diff without
    applying it. Those calls should not require write approval.
    """

    if not isinstance(args, dict):
        # Conservative default: treat unknown args as write-capable.
        return True

    if bool(args.get("preview_only")):
        return False

    operations = args.get("operations")
    if not operations:
        # The tool will fail validation, but classify as write-capable.
        return True

    if not isinstance(operations, list):
        return True

    op_names: list[str] = []
    for op in operations:
        if not isinstance(op, dict):
            return True
        name = op.get("op")
        if not isinstance(name, str):
            return True
        op_names.append(name)

    if op_names and all(name == "read_sections" for name in op_names):
        return False

    return True


@mcp_tool(write_action=True, write_action_resolver=_apply_workspace_operations_write_action_resolver)
async def apply_workspace_operations(
    full_name: str,
    ref: str = "main",
    operations: list[dict[str, Any]] | None = None,
    fail_fast: bool = True,
    rollback_on_error: bool = True,
    preview_only: bool = False,
    create_parents: bool = True,
) -> dict[str, Any]:
    """Apply multiple file operations in a single workspace clone.

    This is a higher-level, multi-file alternative to calling the single-file
    primitives repeatedly.

    Supported operations (each item in `operations`):
      - {"op": "write", "path": "...", "content": "..."}
      - {"op": "replace_text", "path": "...", "old": "...", "new": "...", "replace_all": bool, "occurrence": int}
      - {"op": "edit_range", "path": "...", "start": {"line": int, "col": int}, "end": {"line": int, "col": int}, "replacement": "..."}
      - {"op": "delete_lines", "path": "...", "start_line": int, "end_line": int}
      - {"op": "delete_word", "path": "...", "word": "...", "occurrence": int, "replace_all": bool, "case_sensitive": bool, "whole_word": bool}
      - {"op": "delete_chars", "path": "...", "line": int, "col": int, "count": int}
      - {"op": "delete", "path": "...", "allow_missing": bool}
      - {"op": "mkdir", "path": "...", "exist_ok": bool, "parents": bool}
      - {"op": "rmdir", "path": "...", "allow_missing": bool, "allow_recursive": bool}
      - {"op": "move", "src": "...", "dst": "...", "overwrite": bool}
      - {"op": "apply_patch", "patch": "..."}
      - {"op": "read_sections", "path": "...", "start_line": int, "max_sections": int, "max_lines_per_section": int, "max_chars_per_section": int, "overlap_lines": int}
    """

    if operations is None:
        operations = []
    if not isinstance(operations, list) or any(not isinstance(op, dict) for op in operations):
        raise TypeError("operations must be a list of dicts")
    if not operations and not preview_only:
        raise ValueError("operations must contain at least one item")

    def _read_bytes(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def _write_bytes(path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    # Best-effort rollback by restoring prior file bytes.
    backups: dict[str, bytes | None] = {}

    def _backup_path(abs_path: str) -> None:
        if abs_path in backups:
            return
        if os.path.exists(abs_path):
            backups[abs_path] = _read_bytes(abs_path)
        else:
            backups[abs_path] = None

    def _restore_backups() -> None:
        for abs_path, data in backups.items():
            try:
                if data is None:
                    if os.path.exists(abs_path):
                        if os.path.isdir(abs_path):
                            shutil.rmtree(abs_path)
                        else:
                            os.remove(abs_path)
                    continue
                _write_bytes(abs_path, data)
            except Exception:
                # Best-effort rollback.
                pass

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        results: list[dict[str, Any]] = []
        diffs: list[str] = []

        for idx, op in enumerate(operations):
            op_name = op.get("op")
            if not isinstance(op_name, str) or not op_name.strip():
                entry = {"index": idx, "status": "error", "error": "op must be a non-empty string"}
                results.append(entry)
                if fail_fast:
                    raise ValueError(entry["error"])
                continue

            try:
                if op_name == "write":
                    path = op.get("path")
                    content = op.get("content")
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("write.path must be a non-empty string")
                    if content is None:
                        content = ""
                    if not isinstance(content, str):
                        raise TypeError("write.content must be a string")

                    abs_path = _workspace_safe_join(repo_dir, path)
                    _backup_path(abs_path)
                    before = (
                        backups[abs_path].decode("utf-8", errors="replace")
                        if backups[abs_path]
                        else ""
                    )
                    after = content
                    if not preview_only:
                        _workspace_write_text(
                            repo_dir, path, content, create_parents=create_parents
                        )
                    d = _maybe_diff_for_log(
                        path=path,
                        before=before,
                        after=after,
                        before_exists=backups[abs_path] is not None,
                    )
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    results.append({"index": idx, "op": "write", "path": path, "status": "ok"})
                    continue

                if op_name == "read_sections":
                    path = op.get("path")
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("read_sections.path must be a non-empty string")

                    start_line = int(op.get("start_line", 1) or 1)
                    max_sections = int(op.get("max_sections", 5) or 5)
                    max_lines_per_section = int(op.get("max_lines_per_section", 200) or 200)
                    max_chars_per_section = int(op.get("max_chars_per_section", 80_000) or 80_000)
                    overlap_lines = int(op.get("overlap_lines", 20) or 0)

                    if start_line < 1:
                        start_line = 1
                    if max_sections < 1:
                        max_sections = 1
                    if max_lines_per_section < 1:
                        max_lines_per_section = 1
                    if max_chars_per_section < 1:
                        max_chars_per_section = 1
                    if overlap_lines < 0:
                        overlap_lines = 0

                    abs_path = _workspace_safe_join(repo_dir, path)
                    if not os.path.exists(abs_path):
                        results.append(
                            {
                                "index": idx,
                                "op": "read_sections",
                                "path": path,
                                "status": "missing",
                                "sections": {
                                    "start_line": int(start_line),
                                    "end_line": int(start_line),
                                    "parts": [],
                                    "truncated": False,
                                    "next_start_line": None,
                                    "max_sections": int(max_sections),
                                    "max_lines_per_section": int(max_lines_per_section),
                                    "max_chars_per_section": int(max_chars_per_section),
                                    "overlap_lines": int(overlap_lines),
                                    "had_decoding_errors": False,
                                },
                            }
                        )
                        continue

                    if os.path.isdir(abs_path):
                        raise IsADirectoryError(path)
                    if _is_probably_binary(abs_path):
                        results.append(
                            {
                                "index": idx,
                                "op": "read_sections",
                                "path": path,
                                "status": "binary",
                                "sections": {
                                    "start_line": int(start_line),
                                    "end_line": int(start_line),
                                    "parts": [],
                                    "truncated": False,
                                    "next_start_line": None,
                                    "max_sections": int(max_sections),
                                    "max_lines_per_section": int(max_lines_per_section),
                                    "max_chars_per_section": int(max_chars_per_section),
                                    "overlap_lines": int(overlap_lines),
                                    "had_decoding_errors": False,
                                },
                            }
                        )
                        continue

                    sections = _read_lines_sections(
                        abs_path,
                        start_line=int(start_line),
                        max_sections=int(max_sections),
                        max_lines_per_section=int(max_lines_per_section),
                        max_chars_per_section=int(max_chars_per_section),
                        overlap_lines=int(overlap_lines),
                    )

                    results.append(
                        {
                            "index": idx,
                            "op": "read_sections",
                            "path": path,
                            "status": "ok",
                            "sections": sections,
                        }
                    )
                    continue

                if op_name == "replace_text":
                    path = op.get("path")
                    old = op.get("old")
                    new = op.get("new")
                    replace_all = bool(op.get("replace_all", False))
                    occurrence = int(op.get("occurrence", 1) or 1)
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("replace_text.path must be a non-empty string")
                    if not isinstance(old, str) or old == "":
                        raise ValueError("replace_text.old must be a non-empty string")
                    if new is None:
                        new = ""
                    if not isinstance(new, str):
                        raise TypeError("replace_text.new must be a string")

                    abs_path = _workspace_safe_join(repo_dir, path)
                    if not os.path.exists(abs_path):
                        raise FileNotFoundError(path)
                    _backup_path(abs_path)
                    before = (
                        backups[abs_path].decode("utf-8", errors="replace")
                        if backups[abs_path]
                        else ""
                    )

                    if replace_all:
                        after = before.replace(old, new)
                    else:
                        start = 0
                        found_at = -1
                        for _i in range(max(1, occurrence)):
                            found_at = before.find(old, start)
                            if found_at == -1:
                                break
                            start = found_at + len(old)
                        after = before
                        if found_at != -1:
                            after = before[:found_at] + new + before[found_at + len(old) :]

                    if not preview_only and after != before:
                        _workspace_write_text(repo_dir, path, after, create_parents=create_parents)
                    d = _maybe_diff_for_log(
                        path=path, before=before, after=after, before_exists=True
                    )
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    results.append(
                        {
                            "index": idx,
                            "op": "replace_text",
                            "path": path,
                            "status": "ok" if after != before else "noop",
                        }
                    )
                    continue

                if op_name == "edit_range":
                    path = op.get("path")
                    start = op.get("start")
                    end = op.get("end")
                    replacement = op.get("replacement")
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("edit_range.path must be a non-empty string")
                    if replacement is None:
                        replacement = ""
                    if not isinstance(replacement, str):
                        raise TypeError("edit_range.replacement must be a string")
                    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
                        raise TypeError("edit_range.start/end must be objects")
                    start_line = int(start.get("line"))
                    start_col = int(start.get("col"))
                    end_line = int(end.get("line"))
                    end_col = int(end.get("col"))

                    abs_path = _workspace_safe_join(repo_dir, path)
                    if not os.path.exists(abs_path):
                        raise FileNotFoundError(path)
                    _backup_path(abs_path)
                    before = (
                        backups[abs_path].decode("utf-8", errors="replace")
                        if backups[abs_path]
                        else ""
                    )
                    lines = _split_lines_keepends(before)
                    start_offset = _pos_to_offset(lines, start_line, start_col)
                    end_offset = _pos_to_offset(lines, end_line, end_col)
                    if end_offset < start_offset:
                        raise ValueError("edit_range.end must be after start")
                    after = before[:start_offset] + replacement + before[end_offset:]

                    if not preview_only and after != before:
                        _workspace_write_text(repo_dir, path, after, create_parents=create_parents)
                    d = _maybe_diff_for_log(
                        path=path, before=before, after=after, before_exists=True
                    )
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    results.append(
                        {
                            "index": idx,
                            "op": "edit_range",
                            "path": path,
                            "status": "ok" if after != before else "noop",
                        }
                    )
                    continue

                if op_name == "delete_lines":
                    path = op.get("path")
                    start_line = int(op.get("start_line", 1) or 1)
                    end_line = int(op.get("end_line", start_line) or start_line)
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("delete_lines.path must be a non-empty string")
                    if start_line < 1 or end_line < 1:
                        raise ValueError("delete_lines.start_line/end_line must be >= 1")
                    if end_line < start_line:
                        raise ValueError("delete_lines.end_line must be >= start_line")

                    abs_path = _workspace_safe_join(repo_dir, path)
                    if not os.path.exists(abs_path):
                        raise FileNotFoundError(path)
                    _backup_path(abs_path)
                    before = (
                        backups[abs_path].decode("utf-8", errors="replace")
                        if backups[abs_path]
                        else ""
                    )
                    lines = _split_lines_keepends(before)
                    if not lines:
                        raise ValueError("cannot delete lines from an empty file")
                    if start_line > len(lines) or end_line > len(lines):
                        raise ValueError("delete_lines range out of bounds")

                    start_offset = _pos_to_offset(lines, start_line, 1)
                    if end_line < len(lines):
                        end_offset = _pos_to_offset(lines, end_line + 1, 1)
                    else:
                        end_offset = _pos_to_offset(lines, len(lines) + 1, 1)

                    after = before[:start_offset] + before[end_offset:]
                    if not preview_only and after != before:
                        _workspace_write_text(repo_dir, path, after, create_parents=create_parents)
                    d = _maybe_diff_for_log(
                        path=path, before=before, after=after, before_exists=True
                    )
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    results.append(
                        {
                            "index": idx,
                            "op": "delete_lines",
                            "path": path,
                            "status": "ok" if after != before else "noop",
                            "start_line": start_line,
                            "end_line": end_line,
                        }
                    )
                    continue

                if op_name == "delete_chars":
                    path = op.get("path")
                    line = int(op.get("line", 1) or 1)
                    col = int(op.get("col", 1) or 1)
                    count = int(op.get("count", 1) or 1)
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("delete_chars.path must be a non-empty string")
                    if line < 1 or col < 1:
                        raise ValueError("delete_chars.line/col must be >= 1")
                    if count < 1:
                        raise ValueError("delete_chars.count must be >= 1")

                    abs_path = _workspace_safe_join(repo_dir, path)
                    if not os.path.exists(abs_path):
                        raise FileNotFoundError(path)
                    _backup_path(abs_path)
                    before = (
                        backups[abs_path].decode("utf-8", errors="replace")
                        if backups[abs_path]
                        else ""
                    )
                    lines = _split_lines_keepends(before)
                    start_offset = _pos_to_offset(lines, line, col)
                    end_offset = start_offset + count
                    if end_offset > len(before):
                        raise ValueError("delete_chars range extends beyond end of file")
                    after = before[:start_offset] + before[end_offset:]

                    if not preview_only and after != before:
                        _workspace_write_text(repo_dir, path, after, create_parents=create_parents)
                    d = _maybe_diff_for_log(
                        path=path, before=before, after=after, before_exists=True
                    )
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    results.append(
                        {
                            "index": idx,
                            "op": "delete_chars",
                            "path": path,
                            "status": "ok" if after != before else "noop",
                            "line": line,
                            "col": col,
                            "count": count,
                        }
                    )
                    continue

                if op_name == "delete_word":
                    path = op.get("path")
                    word = op.get("word")
                    occurrence = int(op.get("occurrence", 1) or 1)
                    replace_all = bool(op.get("replace_all", False))
                    case_sensitive = bool(op.get("case_sensitive", True))
                    whole_word = bool(op.get("whole_word", True))
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("delete_word.path must be a non-empty string")
                    if not isinstance(word, str) or word == "":
                        raise ValueError("delete_word.word must be a non-empty string")
                    if occurrence < 1:
                        raise ValueError("delete_word.occurrence must be >= 1")

                    abs_path = _workspace_safe_join(repo_dir, path)
                    if not os.path.exists(abs_path):
                        raise FileNotFoundError(path)
                    _backup_path(abs_path)
                    before = (
                        backups[abs_path].decode("utf-8", errors="replace")
                        if backups[abs_path]
                        else ""
                    )

                    flags = 0 if case_sensitive else re.IGNORECASE
                    pat = re.escape(word)
                    if whole_word:
                        pat = r"\b" + pat + r"\b"

                    matches = list(re.finditer(pat, before, flags))
                    if not matches:
                        after = before
                    elif replace_all:
                        after = re.sub(pat, "", before, flags=flags)
                    else:
                        mi = min(len(matches), occurrence) - 1
                        if mi < 0 or mi >= len(matches):
                            after = before
                        else:
                            m = matches[mi]
                            after = before[: m.start()] + before[m.end() :]

                    if not preview_only and after != before:
                        _workspace_write_text(repo_dir, path, after, create_parents=create_parents)
                    d = _maybe_diff_for_log(
                        path=path, before=before, after=after, before_exists=True
                    )
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    results.append(
                        {
                            "index": idx,
                            "op": "delete_word",
                            "path": path,
                            "status": "ok" if after != before else "noop",
                            "word": word,
                            "occurrence": occurrence,
                            "replace_all": replace_all,
                            "case_sensitive": case_sensitive,
                            "whole_word": whole_word,
                        }
                    )
                    continue
                if op_name == "delete":
                    path = op.get("path")
                    allow_missing = bool(op.get("allow_missing", True))
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("delete.path must be a non-empty string")
                    abs_path = _workspace_safe_join(repo_dir, path)
                    _backup_path(abs_path)
                    if backups[abs_path] is None:
                        if allow_missing:
                            results.append(
                                {"index": idx, "op": "delete", "path": path, "status": "noop"}
                            )
                            continue
                        raise FileNotFoundError(path)

                    before = (
                        backups[abs_path].decode("utf-8", errors="replace")
                        if backups[abs_path]
                        else ""
                    )
                    d = _delete_diff_for_log(path=path, before=before)
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    if not preview_only:
                        os.remove(abs_path)
                    results.append({"index": idx, "op": "delete", "path": path, "status": "ok"})
                    continue

                if op_name == "mkdir":
                    path = op.get("path")
                    exist_ok = bool(op.get("exist_ok", True))
                    parents = bool(op.get("parents", create_parents))
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("mkdir.path must be a non-empty string")
                    abs_path = _workspace_safe_join(repo_dir, path)

                    if os.path.exists(abs_path):
                        if not os.path.isdir(abs_path):
                            raise FileExistsError(path)
                        if exist_ok:
                            results.append(
                                {"index": idx, "op": "mkdir", "path": path, "status": "noop"}
                            )
                            continue
                        raise FileExistsError(path)

                    if not preview_only:
                        if parents:
                            os.makedirs(abs_path, exist_ok=exist_ok)
                        else:
                            os.mkdir(abs_path)
                    results.append({"index": idx, "op": "mkdir", "path": path, "status": "ok"})
                    continue

                if op_name == "rmdir":
                    path = op.get("path")
                    allow_missing = bool(op.get("allow_missing", True))
                    allow_recursive = bool(op.get("allow_recursive", False))
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("rmdir.path must be a non-empty string")
                    abs_path = _workspace_safe_join(repo_dir, path)
                    if not os.path.exists(abs_path):
                        if allow_missing:
                            results.append(
                                {"index": idx, "op": "rmdir", "path": path, "status": "noop"}
                            )
                            continue
                        raise FileNotFoundError(path)
                    if not os.path.isdir(abs_path):
                        raise NotADirectoryError(path)
                    if not preview_only:
                        if allow_recursive:
                            shutil.rmtree(abs_path)
                        else:
                            os.rmdir(abs_path)
                    results.append({"index": idx, "op": "rmdir", "path": path, "status": "ok"})
                    continue

                if op_name == "move":
                    src = op.get("src")
                    dst = op.get("dst")
                    overwrite = bool(op.get("overwrite", False))
                    if not isinstance(src, str) or not src.strip():
                        raise ValueError("move.src must be a non-empty string")
                    if not isinstance(dst, str) or not dst.strip():
                        raise ValueError("move.dst must be a non-empty string")
                    abs_src = _workspace_safe_join(repo_dir, src)
                    abs_dst = _workspace_safe_join(repo_dir, dst)
                    if not os.path.exists(abs_src):
                        raise FileNotFoundError(src)
                    _backup_path(abs_src)
                    _backup_path(abs_dst)
                    if os.path.exists(abs_dst) and not overwrite:
                        raise FileExistsError(dst)
                    if not preview_only:
                        if os.path.exists(abs_dst) and overwrite:
                            if os.path.isdir(abs_dst):
                                shutil.rmtree(abs_dst)
                            else:
                                os.remove(abs_dst)
                        if create_parents:
                            os.makedirs(os.path.dirname(abs_dst), exist_ok=True)
                        shutil.move(abs_src, abs_dst)
                    results.append(
                        {"index": idx, "op": "move", "src": src, "dst": dst, "status": "ok"}
                    )
                    continue

                if op_name == "apply_patch":
                    patch = op.get("patch")
                    if not isinstance(patch, str) or not patch.strip():
                        raise ValueError("apply_patch.patch must be a non-empty string")
                    if not preview_only:
                        await deps["apply_patch_to_repo"](repo_dir, patch)
                    # Prefer letting the provider visual handler render this patch directly.
                    if _looks_like_diff(patch):
                        diffs.append(patch)
                    results.append({"index": idx, "op": "apply_patch", "status": "ok"})
                    continue

                raise ValueError(f"Unsupported op: {op_name}")

            except Exception as exc:
                entry = {"index": idx, "op": op_name, "status": "error", "error": str(exc)}
                results.append(entry)
                if fail_fast:
                    raise

        ok = all(r.get("status") not in {"error"} for r in results)
        combined_diff = "\n".join(diffs).strip() if diffs else None
        if combined_diff and not combined_diff.endswith("\n"):
            combined_diff += "\n"

        return {
            "ref": effective_ref,
            "status": "ok" if ok else "partial",
            "ok": ok,
            "preview_only": bool(preview_only),
            "results": results,
            "__log_diff": combined_diff,
        }

    except Exception as exc:
        if rollback_on_error and backups:
            try:
                _restore_backups()
            except Exception:
                pass
        return _structured_tool_error(exc, context="apply_workspace_operations")
