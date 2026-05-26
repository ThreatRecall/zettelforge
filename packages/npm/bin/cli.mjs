#!/usr/bin/env node

/**
 * Thin wrapper that launches the ZettelForge MCP server via uvx (Python).
 *
 * Requirements:
 *   - Python 3.10+ with `uv` (https://docs.astral.sh/uv/) available on PATH,
 *     OR the `zettelforge` Python package installed globally/in a virtualenv.
 *
 * The wrapper first attempts `uvx zettelforge-mcp` (zero-install from PyPI),
 * then falls back to a direct `zettelforge-mcp` invocation.
 */

import { spawn } from "node:child_process";

const args = process.argv.slice(2);

function launch(command, commandArgs) {
  const child = spawn(command, commandArgs, {
    stdio: "inherit",
    env: process.env,
  });

  child.on("error", () => {
    // If uvx is not found, fall back to direct invocation.
    if (command === "uvx") {
      launch("zettelforge-mcp", args);
    } else {
      console.error(
        "Error: Could not start zettelforge-mcp.\n" +
          "Please install Python 3.10+ and run: pip install zettelforge\n" +
          "Or install uv: https://docs.astral.sh/uv/getting-started/installation/"
      );
      process.exit(1);
    }
  });

  child.on("exit", (code) => {
    process.exit(code ?? 0);
  });
}

launch("uvx", ["zettelforge-mcp", ...args]);
