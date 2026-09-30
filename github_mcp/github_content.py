            ref=ref or None,
        )
        decoded_bytes = decoded.get("decoded_bytes")
        if not isinstance(decoded_bytes, (bytes, bytearray)):
            raise GitHubAPIError("github: decoded content did not return bytes")
        if isinstance(decoded_bytes, bytearray):
            return bytes(decoded_bytes)
        return decoded_bytes

    def _allowed_local_content_roots() -> list[str]:
        raw = os.getenv("ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS", "")
        roots: list[str] = []
        for value in raw.replace(",", " ").split():
            try:
                root = os.path.realpath(os.path.abspath(value))
            except (OSError, ValueError):
                continue
            roots.append(root)
        return roots

    def _read_local(local_path: str) -> bytes:
        allowed_roots = _allowed_local_content_roots()
        if not allowed_roots:
            raise GitHubAPIError(
                "Local content_url reads are disabled unless "
                "ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS is configured."
            )

        try:
            resolved_path = os.path.realpath(os.path.abspath(local_path))
        except (OSError, ValueError) as exc:
            raise GitHubAPIError("Invalid local content_url path") from exc

        if not any(
            resolved_path == root or resolved_path.startswith(root + os.sep)
            for root in allowed_roots
        ):
            raise GitHubAPIError(
                "content_url local file is outside the configured local content roots"
            )

        try:
            with open(resolved_path, "rb") as f:
                return f.read()
        except FileNotFoundError as exc:
            err = GitHubAPIError(
                f"{context} content_url path not found at {resolved_path}."
            )
            raise err from exc
        except OSError as exc:
            raise GitHubAPIError(
                f"Failed to read content_url from {resolved_path}: {exc}"
            ) from exc

    def _is_windows_absolute_path(path: str) -> bool:
        if not isinstance(path, str) or len(path) < 3:
            return False
        # UNC path
        if path.startswith("\\\\"):
            return True
        # Drive letter + : + separator
        letter = path[0]