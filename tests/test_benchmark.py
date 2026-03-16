from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hx.audit import finish_run, start_run, update_run
from hx.benchmark import report_benchmark, run_benchmark, validate_task_battery
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


def commit_task(tmp_path: Path, task_id: str) -> str:
    stage_patch(tmp_path, task_id, PATCH)
    task = load_task(tmp_path, task_id)
    task.active_cell_id = "src"
    task.radius = 0
    task.port_check = check_task_ports(tmp_path, task.to_dict(), "src", 0)
    task.proofs = collect_task_proofs(tmp_path, load_policy(tmp_path), task.to_dict())
    task.proofs["verification"] = verify_task_proofs(tmp_path, task.to_dict())
    save_task(tmp_path, task)
    commit_patch(tmp_path, task_id)
    return load_task(tmp_path, task_id).audit_run_id


def test_benchmark_run_and_report(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init"]) == 0
    baseline_run_ids = []
    treatment_run_ids = []
    for locality, proof_coverage in [(0.9, 0.7), (0.8, 0.6)]:
        run = start_run(tmp_path, "benchmark.baseline")
        update_run(
            tmp_path,
            run.run_id,
            metrics={"locality": locality, "proof_coverage": proof_coverage},
        )
        finish_run(tmp_path, run.run_id, "ok")
        baseline_run_ids.append(run.run_id)
    for locality, proof_coverage in [(1.0, 1.0), (0.95, 0.9)]:
        run = start_run(tmp_path, "benchmark.treatment")
        update_run(
            tmp_path,
            run.run_id,
            metrics={"locality": locality, "proof_coverage": proof_coverage},
        )
        finish_run(tmp_path, run.run_id, "ok")
        treatment_run_ids.append(run.run_id)

    battery = [
        {
            "task_id": "bench-1",
            "difficulty": "easy",
            "description": "smoke benchmark task",
            "seed_branch": "main",
            "repeats": 2,
            "baseline_commands": ["python3 -c 'print(1)'"],
            "treatment_commands": ["python3 -c 'print(2)'"],
            "acceptance_checks": ["python3 -c 'print(3)'"],
            "baseline_run_ids": baseline_run_ids,
            "treatment_run_ids": treatment_run_ids,
        }
    ]
    battery_path = tmp_path / "battery.json"
    battery_path.write_text(json.dumps(battery) + "\n")

    report = run_benchmark(tmp_path, battery_path)
    assert report["methodology"]["paired_runs"] is True
    assert report["baseline_success_rate"]["mean"] == 1.0
    assert report["treatment_success_rate"]["mean"] == 1.0
    assert report["tasks"][0]["repeats"] == 2
    assert report["baseline_locality"]["mean"] == 0.85
    assert report["treatment_locality"]["mean"] == 0.975
    assert report["paired_proof_coverage_delta"]["mean"] == 0.3
    assert report["tasks"][0]["baseline"]["proof_coverage"]["variance"] == 0.005

    rendered = report_benchmark(tmp_path)
    assert "Benchmark Report" in rendered
    assert "descriptive output only" in rendered
    assert "baseline_locality_mean" in rendered
    assert "baseline_proof_coverage_var" in rendered


def test_benchmark_validate_reports_invalid_battery(tmp_path: Path) -> None:
    invalid_battery = [
        {
            "task_id": "broken",
            "difficulty": "easy",
            "description": "missing acceptance checks",
            "seed_branch": "main",
            "baseline_commands": ["python3 -c 'print(1)'"],
            "treatment_commands": ["python3 -c 'print(2)'"],
            "acceptance_checks": [],
            "repeats": 2,
            "baseline_run_ids": ["run-a"],
        }
    ]
    battery_path = tmp_path / "invalid-battery.json"
    battery_path.write_text(json.dumps(invalid_battery) + "\n")

    errors = validate_task_battery(invalid_battery)
    assert errors
    assert main(["--root", str(tmp_path), "benchmark", "validate", str(battery_path)]) == 1


def test_shipped_example_benchmark_battery_is_valid() -> None:
    battery_path = Path(__file__).resolve().parents[1] / "examples" / "benchmark_battery.json"
    battery = json.loads(battery_path.read_text())
    assert validate_task_battery(battery) == []


def test_benchmark_can_use_metrics_from_normal_committed_runs(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init"]) == 0
    init_repo(tmp_path)
    assert main(["--root", str(tmp_path), "hex", "build"]) == 0

    baseline_run_id = commit_task(tmp_path, "bench-baseline")
    (tmp_path / "src" / "demo.py").write_text('print("hello")\n')
    treatment_run_id = commit_task(tmp_path, "bench-treatment")

    battery = [
        {
            "task_id": "bench-committed",
            "difficulty": "easy",
            "description": "uses metrics from normal committed runs",
            "seed_branch": "main",
            "repeats": 1,
            "baseline_commands": ["python3 -c 'print(1)'"],
            "treatment_commands": ["python3 -c 'print(2)'"],
            "acceptance_checks": ["python3 -c 'print(3)'"],
            "baseline_run_ids": [baseline_run_id],
            "treatment_run_ids": [treatment_run_id],
        }
    ]
    battery_path = tmp_path / "committed-battery.json"
    battery_path.write_text(json.dumps(battery) + "\n")

    report = run_benchmark(tmp_path, battery_path)
    assert report["baseline_locality"] is not None
    assert report["baseline_proof_coverage"] is not None
    assert report["tasks"][0]["metric_source"] == "audit_runs"
