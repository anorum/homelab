#!/usr/bin/env python3
"""Deploy Open WebUI tools and configure the Jarvis model via the REST API.

Usage:
    OPEN_WEBUI_API_KEY=<key> python3 open-webui/tools/deploy.py

Environment variables:
    OPEN_WEBUI_API_KEY  API key (required). Generate at Settings → Account → API Keys.
    OPEN_WEBUI_URL      Base URL (default: http://chat.home.alexnorum.com)
    JARVIS_MODEL_ID     Model ID in Open WebUI (default: jarvis)

Reads all *.py files in this directory (excluding itself), creates or updates
each tool via the Open WebUI API, then configures the Jarvis model entry to
reference those tools.
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BASE_URL = os.environ.get("OPEN_WEBUI_URL", "http://chat.home.alexnorum.com")
API_KEY = os.environ.get("OPEN_WEBUI_API_KEY", "")
JARVIS_MODEL_ID = os.environ.get("JARVIS_MODEL_ID", "jarvis")


def parse_metadata(content: str) -> dict:
    """Extract title, author, version, description from the tool's docstring header."""
    meta = {}
    match = re.search(r'"""(.*?)"""', content, re.DOTALL)
    if match:
        block = match.group(1)
        for field in ("title", "author", "version", "description"):
            m = re.search(rf"^{field}:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
            if m:
                meta[field] = m.group(1).strip()
    return meta


def tool_id_from_filename(filename: str) -> str:
    return filename.removesuffix(".py")


def api_request(method: str, path: str, data: dict | None = None) -> tuple[int, dict]:
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {API_KEY}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"detail": body}


def deploy_tool(filepath: Path) -> None:
    tool_id = tool_id_from_filename(filepath.name)
    content = filepath.read_text()
    meta = parse_metadata(content)

    payload = {
        "id": tool_id,
        "name": meta.get("title", tool_id),
        "content": content,
        "meta": {
            "manifest": {
                "title": meta.get("title", tool_id),
                "author": meta.get("author", ""),
                "version": meta.get("version", "0.1.0"),
                "description": meta.get("description", ""),
            }
        },
    }

    # Try create first
    status, resp = api_request("POST", "/api/v1/tools/create", payload)
    if status == 200:
        print(f"  + {tool_id}: created")
        return

    # If already exists, update
    status, resp = api_request("POST", f"/api/v1/tools/id/{tool_id}/update", payload)
    if status == 200:
        print(f"  ~ {tool_id}: updated")
    else:
        print(f"  ! {tool_id}: failed ({status}) {resp.get('detail', resp)}")


def deploy_model(tool_ids: list[str]) -> None:
    payload = {
        "id": JARVIS_MODEL_ID,
        "name": "Jarvis",
        "base_model_id": "jarvis:latest",
        "meta": {"description": "Jarvis homelab assistant"},
        "params": {},
        "tool_ids": tool_ids,
    }

    # Try update first (model likely already exists), fall back to create
    status, resp = api_request("POST", "/api/v1/models/model/update", payload)
    if status == 200:
        print(f"  ~ {JARVIS_MODEL_ID}: model updated (tools: {', '.join(tool_ids)})")
        return

    status, resp = api_request("POST", "/api/v1/models/create", payload)
    if status == 200:
        print(f"  + {JARVIS_MODEL_ID}: model created (tools: {', '.join(tool_ids)})")
    else:
        print(f"  ! {JARVIS_MODEL_ID}: model config failed ({status}) {resp.get('detail', resp)}")


def main():
    if not API_KEY:
        print("Error: OPEN_WEBUI_API_KEY not set")
        print("Generate one at: Open WebUI → Settings → Account → API Keys")
        sys.exit(1)

    tool_files = sorted(
        f for f in SCRIPT_DIR.glob("*.py") if f.name != "deploy.py"
    )

    if not tool_files:
        print("No tool files found.")
        return

    print(f"Deploying {len(tool_files)} tool(s) to {BASE_URL}...")
    tool_ids = []
    for filepath in tool_files:
        deploy_tool(filepath)
        tool_ids.append(tool_id_from_filename(filepath.name))

    print("Configuring Jarvis model...")
    deploy_model(tool_ids)
    print("Done.")


if __name__ == "__main__":
    main()
