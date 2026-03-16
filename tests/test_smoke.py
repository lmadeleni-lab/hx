from __future__ import annotations

import subprocess
from pathlib import Path

from hx.audit import load_run
from hx.cli import main
from hx.mcp_server import create_server
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


def test_smoke_flow(tmp_path: Path) -> None:
    init_repo(tmp_path)
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "hex", "build"]) == 0
    server = create_server(tmp_path)
    assert server is not None
    stage_patch(tmp_path, "smoke-task", PATCH)
    task = load_task(tmp_path, "smoke-task")
    task.active_cell_id = "src"
    task.radius = 0
    task.port_check = check_task_ports(tmp_path, task.to_dict(), "src", 0)
    task.proofs = collect_task_proofs(tmp_path, load_policy(tmp_path), task.to_dict())
    task.proofs["verification"] = verify_task_proofs(tmp_path, task.to_dict())
    save_task(tmp_path, task)
    commit_patch(tmp_path, "smoke-task")
    committed_task = load_task(tmp_path, "smoke-task")
    assert committed_task.metrics["proof_coverage"] == 1.0
    assert task.audit_run_id is not None
    audit_run = load_run(tmp_path, task.audit_run_id)
    assert audit_run.metrics["proof_coverage"] == 1.0
    assert (tmp_path / ".hx" / "audit" / f"{task.audit_run_id}.json").exists()
