"""Tests for token optimization features."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hx.agent import _build_system_prompt, _compress_tool_result
from hx.hexmap import adjacency_summary, load_hexmap
from hx.ports import (
    _load_surface_cache,
    rebuild_surface_cache,
)
from hx.repo_ops import repo_read, repo_search
from hx.setup import run_setup
from hx.templates import policy_toml, starter_hexmap
from hx.tools import ToolRegistry


def _git_init(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True,
    )


def _init_repo(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def hello():\n    return 'hi'\n" * 10)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test(): pass\n")
    run_setup(tmp_path)


def _simple_repo(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.py").write_text('print("hello")\n')
    (tmp_path / "HEXMAP.json").write_text(starter_hexmap())
    (tmp_path / "POLICY.toml").write_text(policy_toml())


# --- Optimization 1: Chunked repo.read ---

class TestRepoReadChunked:
    def test_small_file_returns_full(self, tmp_path: Path) -> None:
        (tmp_path / "small.py").write_text("line1\nline2\nline3\n")
        result = repo_read(tmp_path, "small.py")
        assert result["truncated"] is False
        assert result["total_lines"] == 3
        assert result["lines_returned"] == 3
        assert "line1" in result["content"]
        assert result["warning"] is None

    def test_large_file_truncates(self, tmp_path: Path) -> None:
        big = "x" * 200_000
        (tmp_path / "big.txt").write_text(big)
        result = repo_read(tmp_path, "big.txt", max_bytes=1000)
        assert result["truncated"] is True
        assert result["warning"] is not None
        assert len(result["content"]) <= 1000

    def test_offset_limit(self, tmp_path: Path) -> None:
        lines = "\n".join(f"line{i}" for i in range(50)) + "\n"
        (tmp_path / "lines.txt").write_text(lines)
        result = repo_read(tmp_path, "lines.txt", offset=10, limit=5)
        assert result["offset"] == 10
        assert result["lines_returned"] == 5
        assert result["total_lines"] == 50
        assert "line10" in result["content"]

    def test_offset_beyond_eof(self, tmp_path: Path) -> None:
        (tmp_path / "short.txt").write_text("a\nb\n")
        result = repo_read(tmp_path, "short.txt", offset=100, limit=10)
        assert result["lines_returned"] == 0
        assert result["content"] == ""

    def test_tool_backward_compat(self, tmp_path: Path) -> None:
        _simple_repo(tmp_path)
        registry = ToolRegistry(tmp_path)
        result = registry.call("repo.read", {
            "active_cell_id": "root",
            "radius": 0,
            "path": "src/demo.py",
        })
        assert "content" in result
        assert "path" in result
        assert result["path"] == "src/demo.py"


# --- Optimization 2: Pre-filtered repo.search ---

class TestRepoSearchFiltered:
    def test_limits_to_max_results(self, tmp_path: Path) -> None:
        # Create many matchable lines
        content = "\n".join(f"match_target_{i}" for i in range(50))
        (tmp_path / "many.txt").write_text(content)
        result = repo_search(tmp_path, "match_target", max_results=5)
        assert len(result["matches"]) == 5
        assert result["total_count"] == 50
        assert result["capped"] is True

    def test_cell_paths_prefilter(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("target_line\n")
        (tmp_path / "outside").mkdir()
        (tmp_path / "outside" / "b.py").write_text("target_line\n")
        result = repo_search(
            tmp_path, "target_line", cell_paths=["src/**"],
        )
        paths = [m["path"] for m in result["matches"]]
        assert "src/a.py" in paths
        assert "outside/b.py" not in paths

    def test_no_matches(self, tmp_path: Path) -> None:
        (tmp_path / "empty.txt").write_text("nothing here\n")
        result = repo_search(tmp_path, "nonexistent_query")
        assert result["matches"] == []
        assert result["total_count"] == 0
        assert result["capped"] is False

    def test_text_truncated_at_200(self, tmp_path: Path) -> None:
        long_line = "match " + "x" * 300
        (tmp_path / "long.txt").write_text(long_line)
        result = repo_search(tmp_path, "match")
        assert len(result["matches"][0]["text"]) <= 200


# --- Optimization 3: Sparse graph prompt ---

class TestSparseGraphPrompt:
    def test_adjacency_summary_no_neighbors(self, tmp_path: Path) -> None:
        _simple_repo(tmp_path)
        hexmap = load_hexmap(tmp_path)
        edges = adjacency_summary(hexmap, ["root"])
        assert edges == []

    def test_adjacency_summary_with_neighbors(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        hexmap = load_hexmap(tmp_path)
        cell_ids = [c.cell_id for c in hexmap.cells]
        edges = adjacency_summary(hexmap, cell_ids)
        # May or may not have edges depending on auto-build
        assert isinstance(edges, list)

    def test_system_prompt_uses_graph_not_port_describe(
        self, tmp_path: Path,
    ) -> None:
        _simple_repo(tmp_path)
        registry = ToolRegistry(tmp_path)
        prompt = _build_system_prompt(registry, "root", 1)
        assert "Cell Graph" in prompt
        assert "Governance Rules" in prompt
        # Should not contain "Active Ports" (old label)
        assert "Active Ports" not in prompt


# --- Optimization 4: Cached surfaces ---

class TestSurfaceCache:
    def test_rebuild_writes_cache(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        hexmap = load_hexmap(tmp_path)
        cache = rebuild_surface_cache(tmp_path, hexmap)
        assert len(cache) >= 1
        loaded = _load_surface_cache(tmp_path)
        assert loaded == cache

    def test_cache_fallback_without_file(self, tmp_path: Path) -> None:
        loaded = _load_surface_cache(tmp_path)
        assert loaded == {}

    def test_port_surface_uses_cache(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        hexmap = load_hexmap(tmp_path)
        rebuild_surface_cache(tmp_path, hexmap)
        # port_surface should work (uses cache internally)
        from hx.ports import port_surface
        result = port_surface(tmp_path, hexmap, hexmap.cells[0].cell_id, 0)
        assert "exports" in result


# --- Optimization 5: Progressive context loading ---

class TestProgressiveContext:
    def test_summary_mode_default(self, tmp_path: Path) -> None:
        _simple_repo(tmp_path)
        registry = ToolRegistry(tmp_path)
        result = registry.call("hex.context", {
            "active_cell_id": "root", "radius": 0,
        })
        assert result["detail"] == "summary"
        assert "cell_count" in result
        assert "file_count" in result
        assert "graph" in result
        assert "hint" in result

    def test_full_mode_explicit(self, tmp_path: Path) -> None:
        _simple_repo(tmp_path)
        registry = ToolRegistry(tmp_path)
        result = registry.call("hex.context", {
            "active_cell_id": "root", "radius": 0, "detail": "full",
        })
        assert result["detail"] == "full"
        assert "files" in result
        assert "summaries" in result
        assert "ports" in result

    def test_summary_cheaper_than_full(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        registry = ToolRegistry(tmp_path)
        summary = registry.call("hex.context", {
            "active_cell_id": registry.root.name if False else
            load_hexmap(tmp_path).cells[0].cell_id,
            "radius": 0,
        })
        full = registry.call("hex.context", {
            "active_cell_id": load_hexmap(tmp_path).cells[0].cell_id,
            "radius": 0, "detail": "full",
        })
        summary_size = len(json.dumps(summary))
        full_size = len(json.dumps(full))
        assert summary_size < full_size


# --- Optimization 6: Tool result compression ---

class TestToolResultCompression:
    def test_strips_null_ports(self) -> None:
        result = {
            "ports": [
                {"neighbor_cell_id": None, "port_contract": None},
                {"neighbor_cell_id": "B", "port_contract": {"id": "p1"}},
                {"neighbor_cell_id": None, "port_contract": None},
            ]
        }
        compressed = _compress_tool_result("hex.context", result)
        assert len(compressed["ports"]) == 1
        assert compressed["ports"][0]["neighbor_cell_id"] == "B"

    def test_deduplicates_identical_ports(self) -> None:
        port = {"neighbor_cell_id": "B", "port_contract": {"id": "p1"}}
        result = {"ports": [port, dict(port), dict(port)]}
        compressed = _compress_tool_result("hex.context", result)
        assert len(compressed["ports"]) == 1

    def test_port_check_strips_verbose(self) -> None:
        result = {
            "classification": "breaking",
            "requires_approval": True,
            "impacted_ports": [{"port_id": "p1"}],
            "risk_summary": {
                "ports": [{"detail": "verbose"}],
                "high_risk_ports": [{"port_id": "p1"}],
                "reporting_note": "some note",
            },
            "obligations": {
                "required_checks": ["pytest"],
                "check_specs": [{"value": "pytest", "weight": 1.0}],
                "artifact_specs": [{"value": "x.json", "weight": 0.5}],
            },
        }
        compressed = _compress_tool_result("port.check", result)
        assert "reporting_note" not in compressed["risk_summary"]
        assert "ports" not in compressed["risk_summary"]
        assert "check_specs" not in compressed["obligations"]
        assert "artifact_specs" not in compressed["obligations"]
        # Key fields preserved
        assert compressed["classification"] == "breaking"
        assert compressed["requires_approval"] is True

    def test_small_result_unchanged(self) -> None:
        result = {"cell_id": "root"}
        compressed = _compress_tool_result("hex.resolve_cell", result)
        assert compressed == result

    def test_truncates_oversized(self) -> None:
        result = {"big_list": list(range(10000))}
        compressed = _compress_tool_result("some.tool", result)
        # Should have been truncated
        size = len(json.dumps(compressed, default=str))
        original = len(json.dumps(result, default=str))
        assert size < original
