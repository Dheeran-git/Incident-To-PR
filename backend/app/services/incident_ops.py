from __future__ import annotations

from typing import Any

from ..config import settings
from ..database import add_event, save_incident
from .runtime_config import repository_config
from .workflow import WorkflowUnavailable, analyze_incident


async def run_analysis(incident: dict[str, Any]) -> dict[str, Any]:
    incident["status"] = "analyzing"
    incident["failure"] = None
    save_incident(incident)
    add_event(incident["id"], "workflow", "analysis.started", {})
    try:
        result = await analyze_incident(incident)
        repos = repository_config()
        incident["evidence"] = result.get("evidence", [])
        incident["diagnosis"] = result.get("diagnosis")
        incident["decision"] = result.get("decision")
        incident["proposal"] = {"patches": result.get("patches", []),
                                "summary": result.get("engineer_summary", ""),
                                "rollback_plan": result.get("rollback_plan", ""),
                                "repository": repos["gitops_repository"] if incident["decision"]["action"] == "INFRA_FIX" else repos["code_repository"],
                                "base_branch": settings.github_base_branch}
        incident["policy"] = result.get("policy", {"allowed": False,
            "reasons": [result.get("workflow_error", "No policy result")]})
        if result.get("workflow_error"):
            incident["policy"].setdefault("reasons", []).append(result["workflow_error"])
        if incident["decision"]["action"] in {"ESCALATE_HUMAN", "ROLLBACK"}:
            incident["status"] = "escalated"
        elif incident["policy"].get("allowed"):
            incident["status"] = "awaiting_review" if incident["policy"].get("requires_approval", True) else "ready_for_pr"
        else:
            incident["status"] = "policy_denied"
        add_event(incident["id"], "workflow", "analysis.completed", {
            "decision": incident["decision"], "policy": incident["policy"],
            "evidence_count": len(incident["evidence"])})
    except WorkflowUnavailable as exc:
        incident["status"] = "open"
        incident["failure"] = str(exc)
        add_event(incident["id"], "workflow", "analysis.unavailable", {"reason": str(exc)})
    except Exception as exc:
        incident["status"] = "failed"
        incident["failure"] = f"Analysis stopped safely: {type(exc).__name__}"
        add_event(incident["id"], "workflow", "analysis.failed", {"reason": type(exc).__name__})
    return save_incident(incident)
