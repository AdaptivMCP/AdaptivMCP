import asyncio


def test_run_shell_cancellation_terminates_process_group(monkeypatch):
    """Regression: cancelling _run_shell must terminate the subprocess.

    In hosted deployments, client disconnects frequently manifest as task
    cancellation. If we do not terminate the underlying subprocess, it can keep
    running indefinitely and eventually exhaust resources, causing hangs and
    disconnects.
    """

    from github_mcp import workspace

    if workspace.os.name == "nt":
        # The implementation uses process groups on POSIX. Windows termination is
        # best-effort via proc.kill().
        return

    started = asyncio.Event()
    proceed = asyncio.Event()

    class _FakeProc:
        pid = 4242
        returncode = None

        async def communicate(self):
            started.set()
            await proceed.wait()
            return b"", b""

        async def wait(self):
            # Termination waits should complete quickly.
            return 0

        def kill(self):
            return None

    async def _fake_create_subprocess_shell(*_args, **_kwargs):
        return _FakeProc()

    killpg_calls: list[tuple[int, int]] = []

    def _fake_killpg(pid: int, sig: int):
        killpg_calls.append((pid, sig))

    monkeypatch.setattr(workspace.asyncio, "create_subprocess_shell", _fake_create_subprocess_shell)
    monkeypatch.setattr(workspace.os, "killpg", _fake_killpg)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        async def _scenario() -> None:
            task = asyncio.create_task(workspace._run_shell("sleep 999", timeout_seconds=0))
            await started.wait()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        loop.run_until_complete(_scenario())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert killpg_calls, "Expected process group termination on cancellation"
    assert killpg_calls[0][0] == 4242


def test_run_shell_timeout_terminates_process_group(monkeypatch):
    """Regression: timeouts must terminate the subprocess and return promptly."""

    from github_mcp import workspace

    if workspace.os.name == "nt":
        return

    class _FakeProc:
        pid = 4343
        returncode = 124

        async def communicate(self):
            # Sleep longer than the timeout.
            await asyncio.sleep(0.2)
            return b"out", b"err"

        async def wait(self):
            return 0

        def kill(self):
            return None

    async def _fake_create_subprocess_shell(*_args, **_kwargs):
        return _FakeProc()

    killpg_calls: list[tuple[int, int]] = []

    def _fake_killpg(pid: int, sig: int):
        killpg_calls.append((pid, sig))

    monkeypatch.setattr(workspace.asyncio, "create_subprocess_shell", _fake_create_subprocess_shell)
    monkeypatch.setattr(workspace.os, "killpg", _fake_killpg)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(workspace._run_shell("sleep 999", timeout_seconds=0.01))
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert result["timed_out"] is True
    assert killpg_calls, "Expected process group termination on timeout"
    assert killpg_calls[0][0] == 4343
