from __future__ import annotations

from pathlib import Path

from hx.cli import main
from hx.mcp_server import create_server


def test_server_creation(tmp_path: Path) -> None:
    main(["--root", str(tmp_path), "init"])
    server = create_server(tmp_path)
    assert server is not None
