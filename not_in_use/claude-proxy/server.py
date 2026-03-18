"""
OpenAI-compatible proxy for Claude Pro via the claude.ai unofficial API.

Uses a browser sessionKey cookie to authenticate. Exposes /v1/chat/completions
so Home Assistant's OpenAI Conversation integration can use Claude.

NOTE: Text-only. The claude.ai internal API does not support the tool-calling
format that Home Assistant uses, so HA tools (device control, MCP) won't work.
For full tool support, use the official Anthropic API with an API key.

Setup:
  1. Log into claude.ai in your browser
  2. DevTools → Application → Cookies → claude.ai → copy sessionKey value
  3. Set CLAUDE_SESSION_KEY=<value> in mac-mini/.env
"""

import json
import os
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()

SESSION_KEY = os.environ.get("CLAUDE_SESSION_KEY", "")
BASE_URL = "https://claude.ai/api"
_org_id: str | None = None


def _headers() -> dict:
    return {
        "Cookie": f"sessionKey={SESSION_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }


async def _get_org_id() -> str:
    global _org_id
    if _org_id:
        return _org_id
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE_URL}/organizations", headers=_headers())
        r.raise_for_status()
        _org_id = r.json()[0]["uuid"]
        return _org_id


def _build_prompt(messages: list) -> str:
    """Convert OpenAI messages to Human/Assistant prompt format."""
    parts = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content") or ""
        if role == "system":
            parts.append(f"\n\nHuman: <system>{content}</system>")
        elif role == "user":
            parts.append(f"\n\nHuman: {content}")
        elif role == "assistant":
            parts.append(f"\n\nAssistant: {content}")
    parts.append("\n\nAssistant:")
    return "".join(parts)


async def _complete(org_id: str, prompt: str) -> str:
    """Create a conversation, send the prompt, collect and return the full response text."""
    conv_id = str(uuid.uuid4())

    async with httpx.AsyncClient(timeout=60) as client:
        # Create conversation
        r = await client.post(
            f"{BASE_URL}/organizations/{org_id}/chat_conversations",
            headers=_headers(),
            json={"uuid": conv_id, "name": ""},
        )
        if not r.is_success:
            raise HTTPException(status_code=502, detail=f"Create conversation failed: {r.text}")

        # Send completion request and collect SSE
        async with client.stream(
            "POST",
            f"{BASE_URL}/organizations/{org_id}/chat_conversations/{conv_id}/completion",
            headers=_headers(),
            json={
                "prompt": prompt,
                "timezone": "UTC",
                "model": None,
                "attachments": [],
                "files": [],
                "tools": [],
            },
        ) as resp:
            if not resp.is_success:
                body = await resp.aread()
                raise HTTPException(status_code=502, detail=f"Completion failed: {body.decode()}")

            text_parts = []
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                chunk = event.get("completion", "")
                if chunk:
                    text_parts.append(chunk)

    return "".join(text_parts)


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": "claude-pro", "object": "model", "created": 0, "owned_by": "anthropic"}],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if not SESSION_KEY:
        raise HTTPException(status_code=500, detail="CLAUDE_SESSION_KEY not set")

    body = await request.json()
    messages = body.get("messages", [])

    try:
        org_id = await _get_org_id()
        prompt = _build_prompt(messages)
        text = await _complete(org_id, prompt)
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            raise HTTPException(status_code=401, detail="sessionKey invalid or expired")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "claude-pro",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
