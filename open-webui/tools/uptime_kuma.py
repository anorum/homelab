"""
title: Uptime Kuma
author: Alex Norum
version: 0.1.0
description: Query Uptime Kuma for monitor status — which services are up or down and their response times.
"""

import json
import urllib.request


UPTIME_KUMA_URL = "http://uptime-kuma.uptime-kuma:80"
DEFAULT_SLUG = "home"


class Tools:
    def __init__(self):
        self.uptime_kuma_url = UPTIME_KUMA_URL
        self.slug = DEFAULT_SLUG

    def get_monitor_status(self) -> str:
        """
        Get the current up/down status and response time for all monitors in Uptime Kuma.
        Call this when the user asks which services are up, down, or having issues.
        """
        url = f"{self.uptime_kuma_url}/api/status-page/heartbeat/{self.slug}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            return f"Uptime Kuma error ({e.code}): {body}"
        except Exception as e:
            return f"Uptime Kuma connection error: {e}"

        heartbeat_list = data.get("heartbeatList", {})
        if not heartbeat_list:
            return "No monitor data returned. Check that the status page slug is correct."

        lines = [f"{'MONITOR':<35} {'STATUS':<8} {'PING (ms)'}"]
        lines.append("-" * 55)

        up_count = 0
        down_count = 0

        for monitor_id, heartbeats in heartbeat_list.items():
            if not heartbeats:
                continue
            latest = heartbeats[-1]
            status_code = latest.get("status", 0)
            status_str = "UP" if status_code == 1 else "DOWN"
            ping = latest.get("ping", "—")
            name = latest.get("name", f"monitor-{monitor_id}")

            if status_code == 1:
                up_count += 1
            else:
                down_count += 1

            ping_str = f"{ping}ms" if isinstance(ping, (int, float)) else str(ping)
            lines.append(f"{name:<35} {status_str:<8} {ping_str}")

        summary = f"\nSummary: {up_count} up, {down_count} down"
        return "\n".join(lines) + summary
