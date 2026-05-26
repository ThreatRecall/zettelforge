# ZettelForge MCP Server (npm)

This npm package is a thin wrapper that launches the [ZettelForge](https://github.com/rolandpg/zettelforge) MCP server.

ZettelForge provides agentic memory for cyber threat intelligence — STIX graphs, actor aliasing, offline RAG, Sigma/YARA rule management, and more.

## Quick Start

```bash
npx zettelforge-mcp
```

## Requirements

One of the following:

- **[uv](https://docs.astral.sh/uv/)** (recommended) — the wrapper invokes `uvx zettelforge-mcp` automatically.
- **Python 3.10+** with the `zettelforge` package installed (`pip install zettelforge`).

## Configuration

Add to your MCP client configuration (e.g. Claude Desktop):

```json
{
  "mcpServers": {
    "zettelforge": {
      "command": "npx",
      "args": ["zettelforge-mcp"]
    }
  }
}
```

## License

MIT
