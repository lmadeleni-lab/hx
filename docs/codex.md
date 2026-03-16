# Codex Integration

Configure Codex to launch `hx` as an MCP stdio server.

Example `.codex/config.toml` snippet:

```toml
[mcp_servers.hx]
command = "hx"
args = ["--root", "/absolute/path/to/repo", "mcp", "serve", "--transport", "stdio"]
```

Use the `hx` MCP tools to resolve the active cell, fetch scoped context, stage
patches, verify obligations, and commit only after checks pass.

Current guarantee boundary:

- the stdio transport path is validated end to end in this repository
- replay and benchmark outputs remain best-effort and descriptive respectively
- metric outputs that are not marked normalized should be treated as heuristic

Recommended tool flow:

1. `hex.resolve_cell`
2. `hex.allowed_cells`
3. `hex.context`
4. `repo.read` or `repo.search`
5. `repo.stage_patch`
6. `port.check`
7. `proof.collect`
8. `proof.verify`
9. `repo.commit_patch`

The stdio integration path is covered by an end-to-end test in this repository.
