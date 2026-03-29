#!/bin/bash
# Load secrets and env vars, then run the MCP server natively.
# Called by the com.homelab.mcp LaunchAgent.
set -a
# shellcheck source=/dev/null
source "$(dirname "$0")/../.env"
set +a

exec uv run --with-requirements "$(dirname "$0")/requirements.txt" \
    "$(dirname "$0")/server.py"
