from __future__ import annotations

import asyncio
import logging

from ..config import settings
from ..database import (add_event, create_incident, get_incident, get_monitor_state,
                        list_incidents, list_monitor_states, save_monitor_state)
from ..integrations.telemetry import prometheus_unhealthy_deployments
from .incident_ops import run_analysis
from .runtime_config import auto_monitor_config

logger = logging.getLogger(__name__)
POLL_SECONDS = 30
CONSECUTIVE_UNHEALTHY_POLLS = 2
TERMINAL_STATES = {"verified", "denied", "rejected", "failed", "escalated"}


async def _monitor_once() -> None:
    options = auto_monitor_config()
    if not options["enabled"]:
        return
    result = await prometheus_unhealthy_deployments()
    if not result.get("configured") or result.get("error"):
        logger.warning("Automatic monitoring skipped: %s", result.get("error", "Prometheus is unavailable"))
        return
    unhealthy = {item["service"]: item for item in result.get("items", [])}
    known = {state["service"] for state in list_monitor_states()}
    for service in sorted(known | set(unhealthy)):
        state = get_monitor_state(service)
        incident_id = state.get("active_incident_id")
        incident = get_incident(incident_id) if incident_id else None
        if service in unhealthy:
            state["recovery_noted"] = 0
            state["unhealthy_polls"] += 1
            if incident is None and state["unhealthy_polls"] >= CONSECUTIVE_UNHEALTHY_POLLS:
                open_count = sum(row.get("status") not in TERMINAL_STATES for row in list_incidents(100))
                if open_count >= settings.max_open_incidents:
                    logger.warning("Automatic incident skipped for %s: open incident limit reached", service)
                    save_monitor_state(state)
                    continue
                item = unhealthy[service]
                signal_summary = ", ".join(item.get("signals", []))
                incident = create_incident(service,
                    f"Automatic monitor detected {signal_summary} for deployment {service} in namespace {item['namespace']}. "
                    f"Unavailable replicas: {item['missing_replicas']:g}.",
                    "prometheus_auto", {"detector": "prometheus_kubernetes_health",
                                        "namespace": item["namespace"],
                                        "missing_replicas": item["missing_replicas"],
                                        "signals": item.get("signals", []),
                                        "affected_pods": item.get("affected_pods", []),
                                        "queries": result.get("queries", {})})
                incident_id = incident["id"]
                state["active_incident_id"] = incident_id
                add_event(incident_id, "automatic-monitor", "health.anomaly_confirmed", {
                    "consecutive_polls": state["unhealthy_polls"], "poll_interval_seconds": POLL_SECONDS,
                    "missing_replicas": item["missing_replicas"]})
                if options["auto_analyze"]:
                    await run_analysis(incident)
                    add_event(incident_id, "automatic-monitor", "analysis.triggered_automatically", {
                        "human_approval_still_required": True})
            elif incident and incident.get("status") in TERMINAL_STATES:
                # Keep the same incident attached while the fault persists; never create an alert loop.
                pass
        else:
            state["unhealthy_polls"] = 0
            if incident and incident.get("status") not in TERMINAL_STATES and not state.get("recovery_noted"):
                add_event(incident_id, "automatic-monitor", "health.returned_to_baseline", {
                    "note": "The signal recovered. The incident remains open for human review."})
                state["recovery_noted"] = 1
            elif incident and incident.get("status") in TERMINAL_STATES:
                state["active_incident_id"] = None
                state["recovery_noted"] = 0
        save_monitor_state(state)


async def monitor_loop() -> None:
    while True:
        try:
            await _monitor_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic incident monitor cycle failed safely")
        await asyncio.sleep(POLL_SECONDS)
