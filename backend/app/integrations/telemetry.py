from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

from ..config import settings


async def prometheus_evidence(service: str) -> dict[str, Any]:
    if not settings.prometheus_url:
        return {"source": "prometheus", "configured": False, "items": [], "error": "PROMETHEUS_URL is not configured"}
    query = settings.prometheus_query.replace("$service", service)
    try:
        async with httpx.AsyncClient(timeout=8) as http:
            response = await http.get(f"{settings.prometheus_url}/api/v1/query", params={"query": query})
            response.raise_for_status()
            payload = response.json()
        result = payload.get("data", {}).get("result", [])[:40]
        return {"source": "prometheus", "configured": True, "query": query, "items": result}
    except Exception as exc:
        return {"source": "prometheus", "configured": True, "items": [], "error": f"query failed: {type(exc).__name__}"}


async def loki_evidence(service: str) -> dict[str, Any]:
    if not settings.loki_url:
        return {"source": "loki", "configured": False, "items": [], "error": "LOKI_URL is not configured"}
    query = settings.loki_query.replace("$service", service)
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=10)
    try:
        async with httpx.AsyncClient(timeout=8) as http:
            response = await http.get(f"{settings.loki_url}/loki/api/v1/query_range", params={
                "query": query, "start": str(int(start.timestamp() * 1e9)),
                "end": str(int(end.timestamp() * 1e9)), "limit": "50", "direction": "backward"})
            response.raise_for_status()
            payload = response.json()
        result = payload.get("data", {}).get("result", [])[:20]
        return {"source": "loki", "configured": True, "query": query, "items": result}
    except Exception as exc:
        return {"source": "loki", "configured": True, "items": [], "error": f"query failed: {type(exc).__name__}"}


async def prometheus_health(service: str) -> dict[str, Any]:
    if not settings.prometheus_url:
        return {"configured": False, "healthy": False, "reason": "Prometheus is not configured"}
    query = settings.prometheus_health_query.replace("$service", service)
    try:
        async with httpx.AsyncClient(timeout=8) as http:
            response = await http.get(f"{settings.prometheus_url}/api/v1/query", params={"query": query})
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data", {}).get("result", [])
        values = [float(row["value"][1]) for row in rows if row.get("value")]
        return {"configured": True, "healthy": bool(values) and all(v > 0 for v in values),
                "query": query, "series": len(values), "values": values[:20]}
    except Exception as exc:
        return {"configured": True, "healthy": False, "reason": f"health query failed: {type(exc).__name__}"}


async def prometheus_unhealthy_deployments() -> dict[str, Any]:
    if not settings.prometheus_url:
        return {"configured": False, "items": [], "error": "Prometheus is not configured"}
    namespace = settings.k8s_namespace.replace('"', '')
    queries = {
        "replica_shortfall": (f'(kube_deployment_spec_replicas{{namespace="{namespace}"}} - '
                              f'kube_deployment_status_replicas_available{{namespace="{namespace}"}}) > 0'),
        "crash_loop": f'kube_pod_container_status_waiting_reason{{namespace="{namespace}",reason="CrashLoopBackOff"}} == 1',
        "restarts": f'sum by (pod) (increase(kube_pod_container_status_restarts_total{{namespace="{namespace}"}}[5m])) > 3',
        "deployments": f'kube_deployment_spec_replicas{{namespace="{namespace}"}}',
    }
    try:
        services: set[str] = set()
        signals: dict[str, dict[str, Any]] = {}
        async with httpx.AsyncClient(timeout=8) as http:
            responses = {}
            for name, query in queries.items():
                response = await http.get(f"{settings.prometheus_url}/api/v1/query", params={"query": query})
                response.raise_for_status()
                responses[name] = response.json().get("data", {}).get("result", [])
        for row in responses["deployments"]:
            name = row.get("metric", {}).get("deployment")
            if name and not name.startswith(("incident-to-pr", "prometheus", "grafana", "loki", "alloy")):
                services.add(name)
        for row in responses["replica_shortfall"]:
            labels = row.get("metric", {})
            service = labels.get("deployment")
            if service and service in services:
                signals[service] = {"service": service, "namespace": labels.get("namespace", namespace),
                                    "missing_replicas": float(row.get("value", [0, 0])[1]),
                                    "signals": ["deployment_replica_shortfall"]}
        for signal_name in ("crash_loop", "restarts"):
            for row in responses[signal_name]:
                pod = row.get("metric", {}).get("pod", "")
                service = next((name for name in sorted(services, key=len, reverse=True)
                                if pod.startswith(name + "-")), None)
                if service:
                    item = signals.setdefault(service, {"service": service, "namespace": namespace,
                        "missing_replicas": 0, "signals": []})
                    item["signals"].append("crash_loop" if signal_name == "crash_loop" else "repeated_container_restarts")
                    item.setdefault("affected_pods", []).append(pod)
        return {"configured": True, "queries": queries, "items": list(signals.values())}
    except Exception as exc:
        return {"configured": True, "items": [], "error": f"monitor query failed: {type(exc).__name__}"}


async def prometheus_health_window(service: str, window_minutes: int, since: datetime | None = None) -> dict[str, Any]:
    """Evaluate every Prometheus sample in a bounded recovery window."""
    if not settings.prometheus_url:
        return {"configured": False, "stable": False, "reason": "Prometheus is not configured"}
    end = datetime.now(timezone.utc)
    start = max(end - timedelta(minutes=window_minutes), since or end - timedelta(minutes=window_minutes))
    elapsed = max(0.0, (end - start).total_seconds())
    query = settings.prometheus_health_query.replace("$service", service)
    try:
        async with httpx.AsyncClient(timeout=12) as http:
            response = await http.get(f"{settings.prometheus_url}/api/v1/query_range", params={
                "query": query, "start": str(start.timestamp()), "end": str(end.timestamp()), "step": "30s"})
            response.raise_for_status()
            payload = response.json()
        series = payload.get("data", {}).get("result", [])
        values = [float(sample[1]) for row in series for sample in row.get("values", []) if len(sample) > 1]
        healthy = sum(value > 0 for value in values)
        enough_time = elapsed >= window_minutes * 60
        required_samples = max(1, min(settings.verification_minimum_samples, int(elapsed // 30)))
        enough_samples = len(values) >= required_samples
        return {"configured": True, "stable": enough_time and enough_samples and healthy == len(values),
                "query": query, "window_minutes": window_minutes, "elapsed_seconds": round(elapsed),
                "samples": len(values), "healthy_samples": healthy,
                "minimum_samples": required_samples,
                "reason": None if enough_time and enough_samples and healthy == len(values) else
                    "Recovery window is incomplete, under-sampled, or contains an unhealthy interval"}
    except Exception as exc:
        return {"configured": True, "stable": False, "window_minutes": window_minutes,
                "reason": f"range query failed: {type(exc).__name__}"}


def kubernetes_evidence(service: str) -> dict[str, Any]:
    try:
        try:
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config(context=settings.k8s_context or None)
        v1 = client.CoreV1Api()
        apps = client.AppsV1Api()
        namespace = settings.k8s_namespace
        deployments = apps.list_namespaced_deployment(namespace=namespace, limit=100).items
        selected = [d for d in deployments if service.lower() in d.metadata.name.lower()]
        pods = v1.list_namespaced_pod(namespace=namespace, limit=200).items
        selected_pods = [p for p in pods if service.lower() in p.metadata.name.lower()]
        events = v1.list_namespaced_event(namespace=namespace, limit=100).items
        return {"source": "kubernetes", "configured": True,
                "deployments": [{"name": d.metadata.name, "desired": d.spec.replicas,
                                 "ready": d.status.ready_replicas or 0,
                                 "available": d.status.available_replicas or 0} for d in selected],
                "pods": [{"name": p.metadata.name, "phase": p.status.phase,
                          "restarts": sum(c.restart_count for c in (p.status.container_statuses or [])),
                          "reasons": [c.state.waiting.reason for c in (p.status.container_statuses or [])
                                      if c.state and c.state.waiting]} for p in selected_pods],
                "events": [{"reason": e.reason, "message": (e.message or "")[:500],
                            "type": e.type, "object": e.involved_object.name}
                           for e in events if service.lower() in (e.involved_object.name or "").lower()][:30]}
    except Exception as exc:
        return {"source": "kubernetes", "configured": True, "deployments": [], "pods": [], "events": [],
                "error": f"read failed: {type(exc).__name__}"}


def integration_status() -> dict[str, Any]:
    return {
        "kubernetes": {"configured": bool(settings.k8s_namespace), "mode": "read-only client"},
        "prometheus": {"configured": bool(settings.prometheus_url), "url": settings.prometheus_url or None},
        "loki": {"configured": bool(settings.loki_url), "url": settings.loki_url or None},
        "github": {"configured": bool(settings.github_token and (settings.github_code_repository or settings.github_gitops_repository)),
                   "code_repository": settings.github_code_repository or None,
                   "gitops_repository": settings.github_gitops_repository or None},
        "model": {"configured": bool(settings.llm_model and settings.llm_api_key), "model": settings.llm_model or None},
        "argocd": {"configured": False, "mode": "read-only Kubernetes API", "application": settings.argocd_application},
        "evaluator": {"configured": bool(settings.evaluator_url)},
    }
