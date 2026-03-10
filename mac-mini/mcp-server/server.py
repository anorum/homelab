"""
Homelab MCP server — exposes homelab tools to Home Assistant's conversation agent.

Add tools here with @mcp.tool() and restart the container — no HA config changes needed.

Run: uv run server.py
"""

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("homelab", host="0.0.0.0", port=8080)

PROMETHEUS = "http://prometheus.home.alexnorum.com"


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


# ── Future tools: add @mcp.tool() functions below ─────────────────────────────
# Ideas:
#   - get_argocd_apps() — list all apps with sync/health status
#   - get_alerts() — active Prometheus alerts
#   - run_kubectl(command) — allowlisted kubectl commands (get pods, describe node, etc.)
#   - get_mealie_meal_plan() — today's meal from Mealie API


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
