from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hx.cli import main
from hx.policy import load_policy
from hx.ports import check_task_ports
from hx.proof import collect_task_proofs, verify_task_proofs
from hx.repo_ops import commit_patch, load_task, save_task, stage_patch

PATCH = """--- a/src/demo.py
+++ b/src/demo.py
@@ -1 +1,2 @@
 print("hello")
+print("world")
"""


def init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "demo.py").write_text('print("hello")\n')
    (tmp_path / "tests" / "test_demo.py").write_text(
        "from src.demo import *\n\ndef test_smoke():\n    assert True\n"
    )


def commit_task(tmp_path: Path, task_id: str) -> None:
    stage_patch(tmp_path, task_id, PATCH)
    task = load_task(tmp_path, task_id)
    task.active_cell_id = "src"
    task.radius = 0
    task.port_check = check_task_ports(tmp_path, task.to_dict(), "src", 0)
    task.proofs = collect_task_proofs(tmp_path, load_policy(tmp_path), task.to_dict())
    task.proofs["verification"] = verify_task_proofs(tmp_path, task.to_dict())
    save_task(tmp_path, task)
    commit_patch(tmp_path, task_id)


def test_memory_summarize_writes_state_files(tmp_path: Path) -> None:
    init_repo(tmp_path)
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "init"]) == 0
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "hex", "build"]) == 0
    assert (
        main(["--root", str(tmp_path), "--ui-mode", "quiet", "memory", "summarize"])
        == 0
    )
    repo_summary = json.loads((tmp_path / ".hx" / "state" / "repo_summary.json").read_text())
    assert "generated_at" in repo_summary
    assert "recommended_next_actions" in repo_summary
    cell_summaries = json.loads((tmp_path / ".hx" / "state" / "cell_summaries.json").read_text())
    assert cell_summaries


def test_commit_patch_refreshes_memory_state(tmp_path: Path) -> None:
    init_repo(tmp_path)
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "init"]) == 0
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "hex", "build"]) == 0
    commit_task(tmp_path, "memory-commit")
    repo_summary = json.loads((tmp_path / ".hx" / "state" / "repo_summary.json").read_text())
    assert repo_summary["runs"] >= 1
    open_threads = json.loads((tmp_path / ".hx" / "state" / "open_threads.json").read_text())
    assert open_threads["pending_tasks"] == []


def test_resume_surfaces_pending_task(tmp_path: Path, capsys) -> None:
    init_repo(tmp_path)
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "init"]) == 0
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "hex", "build"]) == 0
    capsys.readouterr()
    stage_patch(tmp_path, "resume-task", PATCH)
    task = load_task(tmp_path, "resume-task")
    task.active_cell_id = "src"
    task.radius = 0
    save_task(tmp_path, task)
    assert main(["--root", str(tmp_path), "--ui-mode", "quiet", "resume"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["open_threads"]["pending_tasks"][0]["task_id"] == "resume-task"
    assert "src" in payload["focus_cells"]
