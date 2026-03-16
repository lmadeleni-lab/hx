# Gemini CLI Integration

Connect Gemini CLI to the `hx` MCP server over stdio.

Example concept:

- command: `hx`
- args: `["--root", "/absolute/path/to/repo", "mcp", "serve", "--transport", "stdio"]`

Once connected, use the same hex-aware tools for scoped reading, staged diffs,
port checks, proof collection, and metrics reporting.

Current guarantee boundary:

- the stdio server path is validated end to end in this repository
- replay remains permission-preserving and best-effort
- benchmark outputs remain descriptive, not inferential

Recommended MCP usage order:

1. resolve the active cell first
2. fetch allowed cells for the current radius
3. load scoped context only inside that radius
4. stage patches before attempting proof or commit
5. run port and proof checks before commit

The stdio server path is verified end to end in the `hx` test suite.
