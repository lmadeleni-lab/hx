from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from statistics import variance
from time import perf_counter
from typing import Any

from hx.audit import load_run
from hx.metrics import report_markdown
from hx.policy import load_policy
from hx.proof import run_allowed_command

CONFIDENCE_Z = 1.96
REQUIRED_TASK_KEYS = {
    "task_id",
    "difficulty",
    "description",
    "seed_branch",
    "baseline_commands",
    "treatment_commands",
    "acceptance_checks",
}


def load_task_battery(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())


def validate_task_battery(tasks: list[dict[str, Any]]) -> list[str]:
    errors = []
    if not isinstance(tasks, list):
        return ["task battery must be a JSON array"]
    for index, task in enumerate(tasks):
        label = f"task[{index}]"
        if not isinstance(task, dict):
            errors.append(f"{label}: task entry must be an object")
            continue
        missing = sorted(REQUIRED_TASK_KEYS - set(task))
        if missing:
            errors.append(f"{label}: missing required keys: {', '.join(missing)}")
        repeats = task.get("repeats", 1)
        if not isinstance(repeats, int) or repeats < 1:
            errors.append(f"{label}: repeats must be an integer >= 1")
        for key in ["baseline_commands", "treatment_commands", "acceptance_checks"]:
            value = task.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                errors.append(f"{label}: {key} must be a list of strings")
            elif key == "acceptance_checks" and not value:
                errors.append(f"{label}: acceptance_checks must not be empty")
        for key in ["baseline_run_ids", "treatment_run_ids"]:
            run_ids = task.get(key)
            if run_ids is None:
                continue
            if not isinstance(run_ids, list) or not all(isinstance(item, str) for item in run_ids):
                errors.append(f"{label}: {key} must be a list of strings when provided")
                continue
            if len(run_ids) != repeats:
                errors.append(
                    f"{label}: {key} length must equal repeats ({repeats}) when provided"
                )
    return errors


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _sample_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"mean": 0.0, "variance": 0.0, "ci95_margin": None}
    mean_value = _mean(values)
    if len(values) < 2:
        return {
            "mean": round(mean_value, 4),
            "variance": 0.0,
            "ci95_margin": None,
        }
    sample_variance = variance(values)
    ci95_margin = CONFIDENCE_Z * math.sqrt(sample_variance / len(values))
    return {
        "mean": round(mean_value, 4),
        "variance": round(sample_variance, 4),
        "ci95_margin": round(ci95_margin, 4),
    }


def _proportion_summary(successes: list[bool]) -> dict[str, Any]:
    if not successes:
        return {"mean": 0.0, "variance": 0.0, "ci95_margin": None}
    numeric = [1.0 if success else 0.0 for success in successes]
    mean_value = _mean(numeric)
    if len(numeric) < 2:
        return {
            "mean": round(mean_value, 4),
            "variance": 0.0,
            "ci95_margin": None,
        }
    sample_variance = variance(numeric)
    ci95_margin = CONFIDENCE_Z * math.sqrt(max(mean_value * (1 - mean_value), 0.0) / len(numeric))
    return {
        "mean": round(mean_value, 4),
        "variance": round(sample_variance, 4),
        "ci95_margin": round(ci95_margin, 4),
    }


def _run_condition(
    root: Path,
    policy: dict[str, Any],
    commands: list[str],
    acceptance_checks: list[str],
) -> dict[str, Any]:
    started = perf_counter()
    command_runs = [run_allowed_command(root, policy, command) for command in commands]
    acceptance = [run_allowed_command(root, policy, command) for command in acceptance_checks]
    duration_s = round(perf_counter() - started, 4)
    success = all(item["returncode"] == 0 for item in acceptance)
    return {
        "success": success,
        "tool_calls": len(command_runs),
        "duration_s": duration_s,
        "commands": command_runs,
        "acceptance_checks": acceptance,
    }


def _summarize_condition(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "repeats": len(runs),
        "success_rate": _proportion_summary([run["success"] for run in runs]),
        "tool_calls": _sample_summary([float(run["tool_calls"]) for run in runs]),
        "duration_s": _sample_summary([float(run["duration_s"]) for run in runs]),
    }


def _metric_summary(metric_runs: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    if not metric_runs:
        return None
    return _sample_summary([float(run.get(key, 0.0)) for run in metric_runs])


def _load_metric_runs(root: Path, run_ids: list[str], *, repeats: int) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    if len(run_ids) != repeats:
        raise ValueError(
            f"Expected {repeats} audit run ids for benchmark metrics, received {len(run_ids)}"
        )
    metric_runs = []
    for run_id in run_ids:
        run = load_run(root, run_id)
        if not run.metrics:
            raise ValueError(f"Audit run {run_id} does not contain metrics")
        metric_runs.append(run.metrics)
    return metric_runs


def _paired_metric_summary(
    baseline_metrics: list[dict[str, Any]],
    treatment_metrics: list[dict[str, Any]],
    key: str,
) -> dict[str, Any] | None:
    if not baseline_metrics or not treatment_metrics:
        return None
    return _sample_summary(
        [
            float(treatment_metrics[index].get(key, 0.0))
            - float(baseline_metrics[index].get(key, 0.0))
            for index in range(min(len(baseline_metrics), len(treatment_metrics)))
        ]
    )


def run_benchmark(
    root: Path,
    battery_path: Path,
    *,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    progress = progress or (lambda _event, _payload: None)
    progress("load_policy", {"root": str(root)})
    policy = load_policy(root)
    progress("load_battery", {"battery_path": str(battery_path)})
    tasks = load_task_battery(battery_path)
    errors = validate_task_battery(tasks)
    if errors:
        raise ValueError("Invalid benchmark battery:\n- " + "\n- ".join(errors))
    progress("battery_valid", {"task_count": len(tasks)})
    results = []
    baseline_successes: list[bool] = []
    treatment_successes: list[bool] = []
    baseline_durations: list[float] = []
    treatment_durations: list[float] = []
    baseline_tool_calls: list[float] = []
    treatment_tool_calls: list[float] = []
    paired_duration_deltas: list[float] = []
    paired_tool_call_deltas: list[float] = []
    baseline_locality: list[float] = []
    treatment_locality: list[float] = []
    baseline_proof_coverage: list[float] = []
    treatment_proof_coverage: list[float] = []
    paired_locality_deltas: list[float] = []
    paired_proof_coverage_deltas: list[float] = []

    for task in tasks:
        repeats = max(int(task.get("repeats", 1)), 1)
        progress(
            "task_start",
            {
                "task_id": task["task_id"],
                "repeats": repeats,
            },
        )
        baseline_runs = []
        treatment_runs = []
        baseline_metric_runs = _load_metric_runs(
            root,
            task.get("baseline_run_ids", []),
            repeats=repeats,
        )
        treatment_metric_runs = _load_metric_runs(
            root,
            task.get("treatment_run_ids", []),
            repeats=repeats,
        )
        for repeat_index in range(repeats):
            baseline_run = _run_condition(
                root,
                policy,
                task.get("baseline_commands", []),
                task.get("acceptance_checks", []),
            )
            progress(
                "condition_done",
                {
                    "task_id": task["task_id"],
                    "condition": "baseline",
                    "repeat": repeat_index + 1,
                    "repeats": repeats,
                    "success": baseline_run["success"],
                },
            )
            treatment_run = _run_condition(
                root,
                policy,
                task.get("treatment_commands", []),
                task.get("acceptance_checks", []),
            )
            progress(
                "condition_done",
                {
                    "task_id": task["task_id"],
                    "condition": "treatment",
                    "repeat": repeat_index + 1,
                    "repeats": repeats,
                    "success": treatment_run["success"],
                },
            )
            baseline_runs.append(baseline_run)
            treatment_runs.append(treatment_run)
            baseline_successes.append(baseline_run["success"])
            treatment_successes.append(treatment_run["success"])
            baseline_durations.append(baseline_run["duration_s"])
            treatment_durations.append(treatment_run["duration_s"])
            baseline_tool_calls.append(float(baseline_run["tool_calls"]))
            treatment_tool_calls.append(float(treatment_run["tool_calls"]))
            paired_duration_deltas.append(
                round(treatment_run["duration_s"] - baseline_run["duration_s"], 4)
            )
            paired_tool_call_deltas.append(
                float(treatment_run["tool_calls"] - baseline_run["tool_calls"])
            )

        if baseline_metric_runs:
            baseline_locality.extend(
                float(run.get("locality", 0.0)) for run in baseline_metric_runs
            )
            baseline_proof_coverage.extend(
                float(run.get("proof_coverage", 0.0)) for run in baseline_metric_runs
            )
        if treatment_metric_runs:
            treatment_locality.extend(
                float(run.get("locality", 0.0)) for run in treatment_metric_runs
            )
            treatment_proof_coverage.extend(
                float(run.get("proof_coverage", 0.0)) for run in treatment_metric_runs
            )
        if baseline_metric_runs and treatment_metric_runs:
            paired_locality_deltas.extend(
                [
                    float(treatment_metric_runs[index].get("locality", 0.0))
                    - float(baseline_metric_runs[index].get("locality", 0.0))
                    for index in range(repeats)
                ]
            )
            paired_proof_coverage_deltas.extend(
                [
                    float(treatment_metric_runs[index].get("proof_coverage", 0.0))
                    - float(baseline_metric_runs[index].get("proof_coverage", 0.0))
                    for index in range(repeats)
                ]
            )

        baseline_summary = _summarize_condition(baseline_runs)
        baseline_summary["locality"] = _metric_summary(baseline_metric_runs, "locality")
        baseline_summary["proof_coverage"] = _metric_summary(
            baseline_metric_runs,
            "proof_coverage",
        )
        treatment_summary = _summarize_condition(treatment_runs)
        treatment_summary["locality"] = _metric_summary(treatment_metric_runs, "locality")
        treatment_summary["proof_coverage"] = _metric_summary(
            treatment_metric_runs,
            "proof_coverage",
        )
        results.append(
            {
                "task_id": task["task_id"],
                "difficulty": task.get("difficulty"),
                "repeats": repeats,
                "baseline": baseline_summary,
                "treatment": treatment_summary,
                "paired_delta": {
                    "duration_s": _sample_summary(
                        [
                            run["duration_s"] - baseline_runs[index]["duration_s"]
                            for index, run in enumerate(treatment_runs)
                        ]
                    ),
                    "tool_calls": _sample_summary(
                        [
                            float(run["tool_calls"] - baseline_runs[index]["tool_calls"])
                            for index, run in enumerate(treatment_runs)
                        ]
                    ),
                    "success_rate": round(
                        treatment_summary["success_rate"]["mean"]
                        - baseline_summary["success_rate"]["mean"],
                        4,
                    ),
                    "locality": _paired_metric_summary(
                        baseline_metric_runs,
                        treatment_metric_runs,
                        "locality",
                    ),
                    "proof_coverage": _paired_metric_summary(
                        baseline_metric_runs,
                        treatment_metric_runs,
                        "proof_coverage",
                    ),
                },
                "descriptive_only": repeats < 2,
                "metric_source": (
                    "audit_runs"
                    if baseline_metric_runs or treatment_metric_runs
                    else None
                ),
            }
        )
        progress("task_done", {"task_id": task["task_id"], "repeats": repeats})

    report = {
        "methodology": {
            "paired_runs": True,
            "repeat_rule": (
                "Each task is executed in baseline and treatment conditions "
                "for the same repeat count."
            ),
            "confidence_rule": "95% confidence margins are reported only when repeats >= 2.",
            "interpretation_rule": (
                "Benchmark output is descriptive and must not be treated as "
                "inferential proof of superiority."
            ),
        },
        "tasks": results,
        "baseline_success_rate": _proportion_summary(baseline_successes),
        "treatment_success_rate": _proportion_summary(treatment_successes),
        "baseline_duration_s": _sample_summary(baseline_durations),
        "treatment_duration_s": _sample_summary(treatment_durations),
        "baseline_tool_calls": _sample_summary(baseline_tool_calls),
        "treatment_tool_calls": _sample_summary(treatment_tool_calls),
        "paired_duration_delta_s": _sample_summary(paired_duration_deltas),
        "paired_tool_call_delta": _sample_summary(paired_tool_call_deltas),
        "baseline_locality": _sample_summary(baseline_locality) if baseline_locality else None,
        "treatment_locality": (
            _sample_summary(treatment_locality) if treatment_locality else None
        ),
        "paired_locality_delta": (
            _sample_summary(paired_locality_deltas) if paired_locality_deltas else None
        ),
        "baseline_proof_coverage": (
            _sample_summary(baseline_proof_coverage) if baseline_proof_coverage else None
        ),
        "treatment_proof_coverage": (
            _sample_summary(treatment_proof_coverage) if treatment_proof_coverage else None
        ),
        "paired_proof_coverage_delta": (
            _sample_summary(paired_proof_coverage_deltas)
            if paired_proof_coverage_deltas
            else None
        ),
        "warnings": [
            "Benchmark output is descriptive, not inferential.",
            (
                "Confidence margins require repeated paired runs and do not "
                "by themselves establish statistical significance."
            ),
            (
                "Locality and proof coverage summaries are only included when "
                "tasks provide audit run ids with recorded metrics."
            ),
        ],
    }
    progress("report_ready", {"task_count": len(results)})
    output_path = root / "benchmark_report.md"
    lines = ["# Benchmark Report", ""]
    lines.append("- methodology: paired baseline/treatment runs")
    lines.append("- confidence_reporting: 95% CI margins shown only when repeats >= 2")
    lines.append("- warning: descriptive output only; do not treat as inferential evidence")
    lines.append(
        f"- baseline_success_rate: {report['baseline_success_rate']['mean']}"
    )
    lines.append(
        f"- treatment_success_rate: {report['treatment_success_rate']['mean']}"
    )
    lines.append(
        f"- paired_tool_call_delta_mean: {report['paired_tool_call_delta']['mean']}"
    )
    lines.append(
        f"- paired_duration_delta_mean_s: {report['paired_duration_delta_s']['mean']}"
    )
    if report["baseline_locality"] is not None:
        lines.append(
            f"- baseline_locality_mean: {report['baseline_locality']['mean']}"
        )
        lines.append(
            f"- treatment_locality_mean: {report['treatment_locality']['mean']}"
        )
        lines.append(
            f"- paired_locality_delta_mean: {report['paired_locality_delta']['mean']}"
        )
    if report["baseline_proof_coverage"] is not None:
        lines.append(
            "- baseline_proof_coverage_mean: "
            f"{report['baseline_proof_coverage']['mean']}"
        )
        lines.append(
            "- treatment_proof_coverage_mean: "
            f"{report['treatment_proof_coverage']['mean']}"
        )
        lines.append(
            "- paired_proof_coverage_delta_mean: "
            f"{report['paired_proof_coverage_delta']['mean']}"
        )
    lines.append("")
    for item in results:
        line = (
            f"- {item['task_id']}: repeats={item['repeats']}, "
            f"baseline_success={item['baseline']['success_rate']['mean']}, "
            f"treatment_success={item['treatment']['success_rate']['mean']}, "
            f"baseline_duration_var={item['baseline']['duration_s']['variance']}, "
            f"treatment_duration_var={item['treatment']['duration_s']['variance']}, "
            f"paired_tool_call_delta={item['paired_delta']['tool_calls']['mean']}"
        )
        if item["baseline"]["locality"] is not None:
            line += (
                f", baseline_locality_var={item['baseline']['locality']['variance']}, "
                f"treatment_locality_var={item['treatment']['locality']['variance']}"
            )
        if item["baseline"]["proof_coverage"] is not None:
            line += (
                ", baseline_proof_coverage_var="
                f"{item['baseline']['proof_coverage']['variance']}, "
                "treatment_proof_coverage_var="
                f"{item['treatment']['proof_coverage']['variance']}"
            )
        lines.append(line)
    lines.append("")
    lines.append(report_markdown(root))
    output_path.write_text("\n".join(lines) + "\n")
    return report


def report_benchmark(root: Path) -> str:
    path = root / "benchmark_report.md"
    if not path.exists():
        raise FileNotFoundError("benchmark_report.md not found; run `hx benchmark run` first")
    return path.read_text()
