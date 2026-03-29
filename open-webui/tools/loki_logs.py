"""
title: Loki Logs
author: Alex Norum
version: 0.1.0
description: Query Loki for recent log lines from any Kubernetes namespace, with optional keyword filtering.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any


LOKI_URL = "http://loki.loki:3100"


class Tools:
    def __init__(self):
        self.loki_url = LOKI_URL

    def get_logs(self, namespace: str, minutes: int = 60, filter: str = "") -> str:
        """
        Fetch recent log lines from a Kubernetes namespace via Loki.
        Call this when the user asks to see logs, recent errors, or output from a specific namespace or service.

        :param namespace: Kubernetes namespace to query (e.g. "open-webui", "mealie", "prometheus").
        :param minutes: How many minutes back to look (default 60).
        :param filter: Optional keyword to filter log lines (case-insensitive, e.g. "error", "timeout").
        """
        query = f'{{namespace="{namespace}"}}'
        if filter:
            query += f' |~ "(?i){filter}"'

        now_ns = int(time.time() * 1e9)
        start_ns = now_ns - int(minutes * 60 * 1e9)

        params = urllib.parse.urlencode({
            "query": query,
            "start": str(start_ns),
            "end": str(now_ns),
            "limit": "20",
            "direction": "backward",
        })
        url = f"{self.loki_url}/loki/api/v1/query_range?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            return f"Loki error ({e.code}): {body}"
        except Exception as e:
            return f"Loki connection error: {e}"

        results = data.get("data", {}).get("result", [])
        if not results:
            desc = f'namespace="{namespace}"'
            if filter:
                desc += f' filter="{filter}"'
            return f"No logs found for {desc} in the last {minutes} minutes."

        lines = []
        for stream in results:
            for ts_ns, line in stream.get("values", []):
                ts = datetime.fromtimestamp(int(ts_ns) / 1e9).strftime("%H:%M:%S")
                lines.append((int(ts_ns), f"[{ts}] {line}"))

        # Sort descending (most recent first) and take top 20
        lines.sort(key=lambda x: x[0], reverse=True)
        header = f"Last {min(len(lines), 20)} log lines from namespace={namespace}"
        if filter:
            header += f' (filter="{filter}")'
        header += f" (past {minutes}m):\n"
        return header + "\n".join(l for _, l in lines[:20])
