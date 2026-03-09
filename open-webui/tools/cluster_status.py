"""
title: Cluster Status
author: Alex Norum
version: 0.2.0
description: Query Prometheus for k8s cluster health — nodes, pods, CPU, memory, and active alerts.
"""

import urllib.request
import urllib.parse
import json
from typing import Any


class Tools:
    def __init__(self):
        self.prometheus_url = "http://prometheus-kube-prometheus-prometheus.prometheus:9090"

    def get_cluster_status(self) -> str:
        """
        Get the current health status of the Kubernetes cluster including node status,
        pod counts, CPU and memory usage, and any active alerts.
        Call this when the user asks about cluster health, node status, or system metrics.
        """
        results = []

        queries = {
            "node_count": 'count(kube_node_info)',
            "ready_nodes": 'count(kube_node_status_condition{condition="Ready",status="true"})',
            "running_pods": 'count(kube_pod_status_phase{phase="Running"} == 1)',
            "failed_pods": 'count(kube_pod_status_phase{phase="Failed"} == 1)',
            "cpu_usage_pct": '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))',
            "memory_usage_pct": '100 * (1 - avg(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))',
        }

        for name, query in queries.items():
            try:
                url = f"{self.prometheus_url}/api/v1/query?query={urllib.parse.quote(query)}"
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    if data["data"]["result"]:
                        value = data["data"]["result"][0]["value"][1]
                        results.append(f"{name}: {value}")
                    else:
                        results.append(f"{name}: no data")
            except Exception as e:
                results.append(f"{name}: error ({e})")

        # Get active alerts
        try:
            url = f"{self.prometheus_url}/api/v1/alerts"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                # k3s doesn't expose control plane metrics — these always fire as false positives
                k3s_noise = {"KubeControllerManagerDown", "KubeProxyDown", "KubeSchedulerDown"}
                firing = [
                    a for a in data["data"]["alerts"]
                    if a["state"] == "firing"
                    and a["labels"].get("alertname") not in k3s_noise
                ]
                if firing:
                    alert_names = [a["labels"].get("alertname", "unknown") for a in firing]
                    results.append(f"firing_alerts: {', '.join(alert_names)}")
                else:
                    results.append("firing_alerts: none")
        except Exception as e:
            results.append(f"firing_alerts: error ({e})")

        return "\n".join(results)
