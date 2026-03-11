"""
Homelab MCP server — exposes homelab tools to Home Assistant's conversation agent.

Add tools here with @mcp.tool() and restart the container — no HA config changes needed.

Run: uv run server.py
"""

import asyncio
import base64
import os
import time

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("homelab", host="0.0.0.0", port=8080)

PROMETHEUS = "http://prometheus.home.alexnorum.com"

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
HA_SPOTIFY_ENTITY = os.environ.get("HA_SPOTIFY_ENTITY", "media_player.spotify")

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

_spotify_token_cache: dict = {}


async def _spotify_token() -> str:
    """Get a cached Spotify client-credentials access token (auto-refreshes)."""
    now = time.time()
    if _spotify_token_cache.get("expires_at", 0) > now + 60:
        return _spotify_token_cache["token"]
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}"},
            data={"grant_type": "client_credentials"},
        )
        r.raise_for_status()
        data = r.json()
    _spotify_token_cache["token"] = data["access_token"]
    _spotify_token_cache["expires_at"] = now + data["expires_in"]
    return _spotify_token_cache["token"]


async def _spotify_search(query: str) -> tuple[str, str]:
    """Search Spotify and return (uri, media_content_type) — playlist preferred, fallback to track."""
    token = await _spotify_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://api.spotify.com/v1/search",
            headers=headers,
            params={"q": query, "type": "playlist", "limit": 5, "market": "US"},
        )
        r.raise_for_status()
        playlists = [p for p in r.json()["playlists"]["items"] if p]
        if playlists:
            return playlists[0]["uri"], "SPOTIFY"

        r = await client.get(
            "https://api.spotify.com/v1/search",
            headers=headers,
            params={"q": query, "type": "track", "limit": 1, "market": "US"},
        )
        r.raise_for_status()
        tracks = r.json()["tracks"]["items"]
        if tracks:
            return tracks[0]["uri"], "SPOTIFY"

    raise ValueError(f"No Spotify results found for: {query}")


def _ha_headers() -> dict:
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


async def _ha_call(service_domain: str, service: str, data: dict) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{HA_URL}/api/services/{service_domain}/{service}",
            headers=_ha_headers(),
            json=data,
        )
        if not r.is_success:
            msg = f"HA {service_domain}.{service} {r.status_code}: {r.text}"
            print(msg, flush=True)
            raise RuntimeError(msg)
        r.raise_for_status()


async def _promql(query: str) -> list:
    """Execute a PromQL instant query, return result list."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{PROMETHEUS}/api/v1/query", params={"query": query})
        r.raise_for_status()
        return r.json()["data"]["result"]


def _scalar(result: list, default=None):
    """Extract scalar value from a single-vector PromQL result."""
    if result:
        return float(result[0]["value"][1])
    return default


# ── Cluster status ────────────────────────────────────────────────────────────


@mcp.tool()
async def get_cluster_status() -> dict:
    """
    Get a summary of the k8s homelab cluster health.
    Returns nodes ready, pods running, ArgoCD apps synced, HDD free %, memory free %.
    Call this when the user asks about homelab or cluster status.
    """
    queries = {
        "nodes_ready": 'count(kube_node_status_condition{condition="Ready",status="true"})',
        "pods_running": 'count(kube_pod_status_phase{phase="Running"})',
        "argocd_synced": 'count(argocd_app_info{sync_status="Synced"})',
        "argocd_out_of_sync": 'count(argocd_app_info{sync_status="OutOfSync"})',
        "hdd_free_pct": (
            'node_filesystem_avail_bytes{mountpoint="/mnt/hd"}'
            " / node_filesystem_size_bytes{mountpoint=\"/mnt/hd\"} * 100"
        ),
        "memory_free_pct": (
            "avg(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100)"
        ),
    }
    results = {}
    for key, q in queries.items():
        val = _scalar(await _promql(q))
        results[key] = round(val, 1) if val is not None else None
    return results


@mcp.tool()
async def get_node_metrics(node: str) -> dict:
    """
    Get CPU and memory usage for a specific cluster node.
    node: node name, e.g. 'swagman-1' or 'swagman-2'.
    """
    cpu_q = f'100 - avg(rate(node_cpu_seconds_total{{mode="idle",node="{node}"}}[5m])) * 100'
    mem_q = f'(1 - node_memory_MemAvailable_bytes{{node="{node}"}} / node_memory_MemTotal_bytes{{node="{node}"}}) * 100'
    return {
        "node": node,
        "cpu_used_pct": round(_scalar(await _promql(cpu_q), 0), 1),
        "memory_used_pct": round(_scalar(await _promql(mem_q), 0), 1),
    }


@mcp.tool()
async def get_hdd_usage() -> dict:
    """
    Get disk usage for swagman-2's HDD at /mnt/hd (12TB drive used for Mealie and Loki).
    Returns total_tb, used_tb, free_tb, free_pct.
    """
    free_bytes = _scalar(await _promql('node_filesystem_avail_bytes{mountpoint="/mnt/hd"}'))
    total_bytes = _scalar(await _promql('node_filesystem_size_bytes{mountpoint="/mnt/hd"}'))
    if total_bytes and free_bytes is not None:
        used_bytes = total_bytes - free_bytes
        return {
            "total_tb": round(total_bytes / 1e12, 2),
            "used_tb": round(used_bytes / 1e12, 2),
            "free_tb": round(free_bytes / 1e12, 2),
            "free_pct": round(free_bytes / total_bytes * 100, 1),
        }
    return {"error": "metric unavailable"}


@mcp.tool()
async def query_prometheus(promql: str) -> str:
    """
    Execute an arbitrary PromQL instant query against the homelab Prometheus instance.
    Use this for specific metric lookups not covered by other tools.
    Returns the raw JSON result string.
    promql: a valid PromQL expression, e.g. 'up{job="node-exporter"}'
    """
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{PROMETHEUS}/api/v1/query", params={"query": promql})
        r.raise_for_status()
        return r.text


# ── Spotify ───────────────────────────────────────────────────────────────────


@mcp.tool()
async def play_spotify(query: str) -> str:
    """
    Search Spotify and play the result on the living room Pi speakers.
    query: any music description — genre, mood, artist, song, playlist name.
    Examples: 'relaxing piano', 'punk rock', 'taylor swift', 'sleep music', 'chill'
    Use this whenever the user asks to play music.
    """
    (uri, content_type), _ = await asyncio.gather(
        _spotify_search(query),
        _ha_call("media_player", "select_source", {
            "entity_id": HA_SPOTIFY_ENTITY,
            "source": "Living Room Satellite",
        }),
    )
    # Retry play_media — device activation can take 1-3s after select_source
    last_err: Exception = RuntimeError("play_media never attempted")
    for delay in (0, 1, 2):
        await asyncio.sleep(delay)
        try:
            await _ha_call("media_player", "play_media", {
                "entity_id": HA_SPOTIFY_ENTITY,
                "media_content_id": uri,
                "media_content_type": content_type,
            })
            break
        except RuntimeError as e:
            last_err = e
    else:
        raise last_err
    return f"Playing {query} on Spotify through the living room speakers"


@mcp.tool()
async def pause_spotify() -> str:
    """Pause Spotify music."""
    await _ha_call("media_player", "media_pause", {"entity_id": HA_SPOTIFY_ENTITY})
    return "Music paused"


@mcp.tool()
async def resume_spotify() -> str:
    """Resume Spotify music."""
    await _ha_call("media_player", "media_play", {"entity_id": HA_SPOTIFY_ENTITY})
    return "Music resumed"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
