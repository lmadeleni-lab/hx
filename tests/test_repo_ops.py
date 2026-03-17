from __future__ import annotations

import subprocess
from pathlib import Path

from hx.repo_ops import commit_patch, load_task, stage_patch
from hx.templates import policy_toml

PATCH = """--- a/src/demo.py
+++ b/src/demo.py
@@ -1 +1,2 @@
 print("hello")
+print("world")
"""

APPLY_PATCH = """*** Begin Patch
*** Update File: src/demo.py
@@
 print("hello")
+print("world")
*** End Patch
"""


def init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.py").write_text('print("hello")\n')
    (tmp_path / "POLICY.toml").write_text(policy_toml())


def test_stage_patch_tracks_files(tmp_path: Path) -> None:
    init_repo(tmp_path)
    result = stage_patch(tmp_path, "task-1", PATCH)
    assert result["files_touched"] == ["src/demo.py"]
    task = load_task(tmp_path, "task-1")
    assert task.patch_sha256


def test_stage_patch_accepts_apply_patch_format(tmp_path: Path) -> None:
    init_repo(tmp_path)
    result = stage_patch(tmp_path, "task-1", APPLY_PATCH)
    assert result["files_touched"] == ["src/demo.py"]
    task = load_task(tmp_path, "task-1")
    patch_text = (tmp_path / task.patch_path).read_text()
    assert "diff --git" in patch_text


def test_commit_patch_applies_after_proofs(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage_patch(tmp_path, "task-1", PATCH)
    task = load_task(tmp_path, "task-1")
    task.port_check = {"requires_approval": False}
    task.proofs = {"verification": {"ok": True}}
    from hx.repo_ops import save_task

    save_task(tmp_path, task)
    commit_patch(tmp_path, "task-1")
    assert 'print("world")' in (tmp_path / "src" / "demo.py").read_text()
