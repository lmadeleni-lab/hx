"""Tests for v1.5 config improvements."""
from __future__ import annotations

from pathlib import Path

from hx.config import repo_root


class TestRepoRootWalksUp:
    """repo_root walks up directories to find .hx or .git."""

    def test_finds_hx_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".hx").mkdir()
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        assert repo_root(deep) == tmp_path

    def test_finds_git_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        deep = tmp_path / "src" / "pkg"
        deep.mkdir(parents=True)
        assert repo_root(deep) == tmp_path

    def test_falls_back_to_cwd(self, tmp_path: Path) -> None:
        deep = tmp_path / "no" / "markers"
        deep.mkdir(parents=True)
        result = repo_root(deep)
        assert result == deep

    def test_prefers_nearest_marker(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / ".hx").mkdir()
        assert repo_root(sub) == sub
