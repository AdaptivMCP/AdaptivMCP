import asyncio

from github_mcp.workspace import _apply_patch_to_repo


def test_apply_patch_accepts_rangeless_git_hunks(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("a\nb\nc\n", encoding="utf-8")

    patch = """diff --git a/hello.txt b/hello.txt
index 1111111..2222222 100644
--- a/hello.txt
+++ b/hello.txt
@@
 a
-b
+B
 c
"""

    asyncio.run(_apply_patch_to_repo(str(tmp_path), patch))

    assert target.read_text(encoding="utf-8") == "a\nB\nc\n"
