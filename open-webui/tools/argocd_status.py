"""
title: ArgoCD Status
author: Alex Norum
version: 0.1.0
description: Query ArgoCD for application sync and health status, and trigger syncs.
"""

import json
import os
import urllib.parse
import urllib.request
from typing import Any


ARGOCD_URL = "http://argocd-server.argocd:80"


class Tools:
    def __init__(self):
        self.argocd_url = ARGOCD_URL
        self.token = os.environ.get("ARGOCD_TOKEN", "")

    def _request(self, method: str, path: str, data: dict | None = None) -> tuple[int, Any]:
        url = f"{self.argocd_url}{path}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method=method)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            try:
                return e.code, json.loads(body)
            except json.JSONDecodeError:
                return e.code, {"error": body}

    def get_apps_status(self) -> str:
        """
        Get the sync and health status of all ArgoCD applications.
        Call this when the user asks about ArgoCD apps, deployment status, or which apps are out of sync.
        """
        if not self.token:
            return "Error: ARGOCD_TOKEN environment variable not set."

        status, data = self._request("GET", "/api/v1/applications")
        if status != 200:
            return f"Error fetching apps ({status}): {data.get('error', data)}"

        apps = data.get("items", [])
        if not apps:
            return "No ArgoCD applications found."

        lines = [f"{'APP':<30} {'SYNC':<15} {'HEALTH':<15}"]
        lines.append("-" * 60)
        for app in sorted(apps, key=lambda a: a["metadata"]["name"]):
            name = app["metadata"]["name"]
            sync = app.get("status", {}).get("sync", {}).get("status", "Unknown")
            health = app.get("status", {}).get("health", {}).get("status", "Unknown")
            lines.append(f"{name:<30} {sync:<15} {health:<15}")

        return "\n".join(lines)

    def sync_app(self, app_name: str) -> str:
        """
        Trigger a sync for a specific ArgoCD application.
        Call this when the user asks to sync, refresh, or redeploy a specific app.

        :param app_name: The name of the ArgoCD application to sync (e.g. "mealie", "open-webui").
        """
        if not self.token:
            return "Error: ARGOCD_TOKEN environment variable not set."

        status, data = self._request("POST", f"/api/v1/applications/{urllib.parse.quote(app_name)}/sync", {})
        if status == 200:
            sync_status = data.get("status", {}).get("sync", {}).get("status", "unknown")
            return f"Sync triggered for '{app_name}'. Current sync status: {sync_status}"
        return f"Error syncing '{app_name}' ({status}): {data.get('error', data.get('message', data))}"
