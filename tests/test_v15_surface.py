"""Tests for v1.5 multi-language surface extraction."""
from __future__ import annotations

from pathlib import Path

from hx.models import Cell
from hx.ports import (
    SURFACE_EXTRACTORS,
    _go_exports,
    _python_exports,
    _typescript_exports,
    extract_cell_surface,
)


class TestPythonExports:
    def test_extracts_functions_and_classes(self, tmp_path: Path) -> None:
        (tmp_path / "mod.py").write_text(
            "def foo(a, b):\n    pass\n\n"
            "class Bar:\n    pass\n\n"
            "async def baz(x):\n    pass\n"
        )
        result = _python_exports(tmp_path / "mod.py")
        assert sorted(result["exports"]) == ["Bar", "baz", "foo"]
        assert result["signatures"]["foo"] == "foo(a, b)"
        assert result["signatures"]["Bar"] == "class Bar"
        assert result["signatures"]["baz"] == "baz(x)"


class TestTypeScriptExports:
    def test_extracts_exported_functions(self, tmp_path: Path) -> None:
        (tmp_path / "mod.ts").write_text(
            "export function greet(name: string): string {\n"
            "  return name;\n"
            "}\n\n"
            "export async function fetchData(url: string) {\n"
            "  return fetch(url);\n"
            "}\n"
        )
        result = _typescript_exports(tmp_path / "mod.ts")
        assert "greet" in result["exports"]
        assert "fetchData" in result["exports"]
        assert "greet(name: string)" in result["signatures"]["greet"]

    def test_extracts_exported_classes(self, tmp_path: Path) -> None:
        (tmp_path / "widget.tsx").write_text(
            "export class Widget {\n"
            "  render() { return null; }\n"
            "}\n"
        )
        result = _typescript_exports(tmp_path / "widget.tsx")
        assert "Widget" in result["exports"]
        assert result["signatures"]["Widget"] == "class Widget"

    def test_extracts_exported_consts(self, tmp_path: Path) -> None:
        (tmp_path / "config.js").write_text(
            "export const MAX_SIZE = 100;\n"
            "export let count = 0;\n"
        )
        result = _typescript_exports(tmp_path / "config.js")
        assert "MAX_SIZE" in result["exports"]
        assert "count" in result["exports"]

    def test_extracts_default_export(self, tmp_path: Path) -> None:
        (tmp_path / "app.tsx").write_text(
            "export default function App() {\n"
            "  return null;\n"
            "}\n"
        )
        result = _typescript_exports(tmp_path / "app.tsx")
        assert "App" in result["exports"]


class TestGoExports:
    def test_extracts_exported_functions(self, tmp_path: Path) -> None:
        (tmp_path / "main.go").write_text(
            "package main\n\n"
            "func Hello(name string) string {\n"
            "    return name\n"
            "}\n\n"
            "func internal() {}\n\n"
            "func (s *Server) Start(port int) error {\n"
            "    return nil\n"
            "}\n"
        )
        result = _go_exports(tmp_path / "main.go")
        assert "Hello" in result["exports"]
        assert "Start" in result["exports"]
        # internal starts with lowercase, should not be exported
        assert "internal" not in result["exports"]

    def test_extracts_exported_types(self, tmp_path: Path) -> None:
        (tmp_path / "types.go").write_text(
            "package main\n\n"
            "type Server struct {\n"
            "    Port int\n"
            "}\n\n"
            "type Handler interface {\n"
            "    Handle()\n"
            "}\n"
        )
        result = _go_exports(tmp_path / "types.go")
        assert "Server" in result["exports"]
        assert "Handler" in result["exports"]


class TestSurfaceExtractorRegistry:
    def test_python_registered(self) -> None:
        assert ".py" in SURFACE_EXTRACTORS

    def test_typescript_registered(self) -> None:
        for ext in [".ts", ".tsx", ".js", ".jsx", ".mjs"]:
            assert ext in SURFACE_EXTRACTORS, f"{ext} not registered"

    def test_go_registered(self) -> None:
        assert ".go" in SURFACE_EXTRACTORS


class TestExtractCellSurfaceMultiLanguage:
    def test_python_and_typescript_combined(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "api.py").write_text("def hello():\n    pass\n")
        (src / "utils.ts").write_text("export function format(s: string) { return s; }\n")

        cell = Cell(cell_id="src", paths=["src/**"], summary="Source")
        surface = extract_cell_surface(tmp_path, cell)
        assert "hello" in surface["exports"]
        assert "format" in surface["exports"]

    def test_reports_unsupported_extensions(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.rs").write_text("fn main() {}\n")

        cell = Cell(cell_id="src", paths=["src/**"], summary="Source")
        surface = extract_cell_surface(tmp_path, cell)
        assert ".rs" in surface["unsupported_extensions"]

    def test_schema_files_tracked(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "schema.graphql").write_text("type Query { hello: String }\n")

        cell = Cell(cell_id="src", paths=["src/**"], summary="Source")
        surface = extract_cell_surface(tmp_path, cell)
        assert "src/schema.graphql" in surface["schemas"]
