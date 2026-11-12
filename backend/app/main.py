from __future__ import annotations

import hmac
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import (add_event, create_incident, get_app_setting, get_incident, init_db, list_events,
                       list_incidents, save_incident, set_app_settings)
from .integrations.argocd import application_status
from .integrations.github import GitHubClient, GitHubError
from .integrations.telemetry import integration_status, prometheus_health, prometheus_health_window
from .schemas import AlertmanagerPayload, IncidentCreate, MonitorConfigUpdate, RepositoryConfigUpdate, ReviewRequest
from .services.incident_ops import run_analysis
from .services.monitor import monitor_loop
from .services.runtime_config import auto_monitor_config, normalize_github_repository, repository_config


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    monitor_task = asyncio.create_task(monitor_loop())
    try:
        yield
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Incident-to-PR API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=sorted({settings.frontend_origin, "http://localhost:3000", "http://127.0.0.1:3000"}), allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["Content-Type", "X-Alertmanager-Token"])


def _get_or_404(incident_id: str) -> dict[str, Any]:
    incident = get_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    return incident


@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "incident-to-pr-api", "environment": settings.app_env}


@app.get("/api/v1/integrations")
async def integrations() -> dict[str, Any]:
    status = integration_status()
    repos = repository_config()
    status["github"].update({"code_repository": repos["code_repository"] or None,
                             "gitops_repository": repos["gitops_repository"] or None,
                             "configured": bool(settings.github_token and repos["code_repository"] and repos["gitops_repository"])})
    argo = await application_status()
    status["argocd"].update({"configured": argo.get("configured", False),
                              "synced": argo.get("synced", False), "healthy": argo.get("healthy", False)})
    return status


@app.get("/api/v1/configuration")
async def get_configuration() -> dict[str, Any]:
    repos = repository_config()
    monitoring = auto_monitor_config()
    return {"code_repository": repos["code_repository"], "gitops_repository": repos["gitops_repository"],
            "github_token_configured": bool(settings.github_token),
            "model_configured": bool(settings.llm_model and settings.llm_api_key),
            "monitoring": monitoring, "namespace": settings.k8s_namespace}


@app.put("/api/v1/configuration/repositories")
async def configure_repositories(payload: RepositoryConfigUpdate) -> dict[str, Any]:
    try:
        code_repo = normalize_github_repository(payload.code_repository_url)
        gitops_repo = normalize_github_repository(payload.gitops_repository_url) if payload.gitops_repository_url.strip() else code_repo
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if settings.github_token:
        try:
            github = GitHubClient()
            await github.get_repository(code_repo)
            if gitops_repo != code_repo:
                await github.get_repository(gitops_repo)
        except GitHubError as exc:
            raise HTTPException(422, f"GitHub could not access the selected repository: {exc}") from exc
    set_app_settings({"code_repository": code_repo, "gitops_repository": gitops_repo})
    return {"code_repository": code_repo, "gitops_repository": gitops_repo,
            "verified": bool(settings.github_token), "github_token_configured": bool(settings.github_token)}


@app.put("/api/v1/configuration/monitoring")
async def configure_monitoring(payload: MonitorConfigUpdate) -> dict[str, Any]:
    if payload.enabled and not settings.prometheus_url:
        raise HTTPException(409, "Configure Prometheus before enabling automatic monitoring")
    if payload.enabled and payload.auto_analyze:
        if not settings.llm_api_key:
            raise HTTPException(409, "Configure the model provider before enabling automatic analysis")
    set_app_settings({"auto_monitor_enabled": str(payload.enabled).lower(),
                      "auto_analyze_enabled": str(payload.auto_analyze).lower()})
    return auto_monitor_config()


@app.get("/api/v1/policy")
async def policy_summary() -> dict[str, Any]:
    return {"require_human_approval": settings.require_human_approval,
            "auto_apply_enabled": settings.auto_apply_enabled,
            "code_allowed_paths": settings.code_allowed_paths,
            "infra_allowed_paths": settings.infra_allowed_paths,
            "max_patch_files": settings.max_patch_files,
            "max_patch_bytes": settings.max_patch_bytes,
            "invariant": "The application never writes to Kubernetes and never merges pull requests."}


@app.get("/api/v1/incidents")
async def incidents(limit: int = 50) -> list[dict[str, Any]]:
    return list_incidents(max(1, min(limit, 100)))


@app.post("/api/v1/incidents", status_code=201)
async def create_incident_route(payload: IncidentCreate) -> dict[str, Any]:
    active = [i for i in list_incidents(100) if i["status"] not in {"verified", "denied", "rejected", "failed", "escalated"}]
    if len(active) >= settings.max_open_incidents:
        raise HTTPException(429, "Open incident limit reached; resolve or escalate existing incidents")
    incident = create_incident(payload.service, payload.summary, payload.source, payload.labels)
    return incident


@app.get("/api/v1/incidents/{incident_id}")
async def incident_detail(incident_id: str) -> dict[str, Any]:
    incident = _get_or_404(incident_id)
    incident["events"] = list_events(incident_id)
    return incident


@app.post("/api/v1/incidents/{incident_id}/analyze")
async def analyze(incident_id: str) -> dict[str, Any]:
    incident = _get_or_404(incident_id)
    if incident["status"] not in {"open", "failed"}:
        raise HTTPException(409, f"Cannot analyze incident in status {incident['status']}")
    return await run_analysis(incident)


@app.post("/api/v1/incidents/{incident_id}/review")
async def review(incident_id: str, payload: ReviewRequest) -> dict[str, Any]:
    incident = _get_or_404(incident_id)
    if incident["status"] != "awaiting_review" or not incident.get("policy", {}).get("allowed"):
        raise HTTPException(409, "Incident is not waiting for an eligible PR review")
    incident["review"] = {"decision": payload.decision, "reviewer": payload.reviewer,
                           "comment": payload.comment, "at": datetime.now(timezone.utc).isoformat()}
    if payload.decision == "reject":
        incident["status"] = "rejected"
        add_event(incident_id, payload.reviewer, "proposal.rejected", {"comment": payload.comment})
    else:
        incident["status"] = "ready_for_pr"
        add_event(incident_id, payload.reviewer, "proposal.approved_for_pr", {"comment": payload.comment})
    return save_incident(incident)


@app.post("/api/v1/incidents/{incident_id}/open-pr")
async def open_pr(incident_id: str) -> dict[str, Any]:
    incident = _get_or_404(incident_id)
    if incident["status"] != "ready_for_pr":
        raise HTTPException(409, "Incident must pass policy and human review before creating a PR")
    if not incident.get("policy", {}).get("allowed"):
        raise HTTPException(403, "Policy denied this proposal")
    if incident.get("policy", {}).get("requires_approval", True) and incident.get("review", {}).get("decision") != "approve_pr":
        raise HTTPException(403, "Human approval is required")
    proposal = incident.get("proposal") or {}
    repo = proposal.get("repository")
    if not repo:
        raise HTTPException(503, "Target repository is not configured")
    try:
        gh = GitHubClient()
        pr = await gh.create_pull_request(repo, settings.github_base_branch,
            f"Incident {incident_id[:8]}: {incident['decision']['action']} for {incident['service']}",
            _pr_body(incident), proposal.get("patches", []), incident_id)
        incident["pull_request"] = pr
        if pr.get("merged"):
            incident["verification_started_at"] = pr.get("merged_at") or datetime.now(timezone.utc).isoformat()
            incident["status"] = "merged_waiting_verification"
        else:
            incident["status"] = "pr_open" if pr.get("state") == "open" else "rejected"
        add_event(incident_id, "github-integration", "pull_request.created", pr)
        return save_incident(incident)
    except GitHubError as exc:
        add_event(incident_id, "github-integration", "pull_request.failed", {"reason": str(exc)[:500]})
        raise HTTPException(502, str(exc)) from exc


def _pr_body(incident: dict[str, Any]) -> str:
    diagnosis = incident.get("diagnosis") or {}
    decision = incident.get("decision") or {}
    proposal = incident.get("proposal") or {}
    evidence = ", ".join(diagnosis.get("evidence_ids", [])) or "No evidence IDs"
    return (f"## Incident-to-PR proposal\n\n"
            f"- Incident: `{incident['id']}`\n- Service: `{incident['service']}`\n"
            f"- Decision: `{decision.get('action')}`\n- Evidence: {evidence}\n\n"
            f"### Diagnosis\n{diagnosis.get('root_cause', 'Not provided')}\n\n"
            f"### Proposal\n{proposal.get('summary', 'Review the diff and CI checks.')}\n\n"
            f"### Rollback plan\n{proposal.get('rollback_plan', 'Revert this pull request.')}\n\n"
            "This bot opens a pull request only. CI, required reviews, branch protection, and the GitOps controller govern deployment.")


@app.post("/api/v1/incidents/{incident_id}/refresh")
async def refresh_status(incident_id: str) -> dict[str, Any]:
    incident = _get_or_404(incident_id)
    pr = incident.get("pull_request")
    if not pr:
        raise HTTPException(409, "No pull request is associated with this incident")
    try:
        gh = GitHubClient()
        pr_state = await gh.get_pull_request(pr["repository"], int(pr["number"]))
        incident["pull_request"].update(pr_state)
        if pr_state["merged"]:
            if not incident.get("verification_started_at"):
                incident["verification_started_at"] = pr_state.get("merged_at") or datetime.now(timezone.utc).isoformat()
            argo = await application_status()
            health = await prometheus_health(incident["service"])
            incident["verification"] = {"argocd": argo, "prometheus": health,
                                         "checked_at": datetime.now(timezone.utc).isoformat()}
            if argo.get("configured") and argo.get("synced") and argo.get("healthy") and health.get("configured") and health.get("healthy"):
                incident["status"] = "deployed_verifying"
                add_event(incident_id, "verifier", "deployment.healthy_initial", incident["verification"])
            else:
                incident["status"] = "merged_waiting_verification"
                add_event(incident_id, "verifier", "verification.pending", incident["verification"])
        elif pr_state.get("state") == "closed":
            incident["status"] = "rejected"
            add_event(incident_id, "verifier", "pull_request.closed_unmerged", pr_state)
        else:
            incident["status"] = "pr_open"
        return save_incident(incident)
    except GitHubError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/v1/incidents/{incident_id}/verify")
async def verify_incident(incident_id: str) -> dict[str, Any]:
    incident = _get_or_404(incident_id)
    pr = incident.get("pull_request") or {}
    if not pr.get("merged"):
        raise HTTPException(409, "Pull request must be merged through GitHub before verification")
    if not incident.get("verification_started_at"):
        incident["verification_started_at"] = pr.get("merged_at") or datetime.now(timezone.utc).isoformat()
    try:
        merged_at = datetime.fromisoformat(incident["verification_started_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError):
        merged_at = datetime.now(timezone.utc)
    argo = await application_status()
    health = await prometheus_health(incident["service"])
    since = merged_at.astimezone(timezone.utc)
    windows = {}
    for minutes in (5, settings.verification_window_minutes):
        windows[str(minutes)] = await prometheus_health_window(incident["service"], minutes, since)
    checks = {"argocd": argo, "prometheus": health, "prometheus_windows": windows,
              "checked_at": datetime.now(timezone.utc).isoformat(), "started_at": since.isoformat()}
    incident["verification"] = checks
    long_window = windows[str(settings.verification_window_minutes)]
    if (argo.get("configured") and argo.get("synced") and argo.get("healthy") and
            long_window.get("configured") and long_window.get("stable")):
        incident["status"] = "verified"
        add_event(incident_id, "verifier", "incident.verified", checks)
    else:
        incident["status"] = "merged_waiting_verification"
        add_event(incident_id, "verifier", "incident.not_verified", checks)
    return save_incident(incident)


@app.post("/api/v1/webhooks/alertmanager", status_code=202)
async def alertmanager_webhook(payload: AlertmanagerPayload, x_alertmanager_token: str = Header(default="")) -> dict[str, Any]:
    if not settings.alertmanager_webhook_token or not hmac.compare_digest(x_alertmanager_token, settings.alertmanager_webhook_token):
        raise HTTPException(401, "Invalid webhook token")
    accepted = []
    for alert in payload.alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        if labels.get("severity", "warning").lower() == "resolved":
            continue
        service = labels.get("service") or labels.get("app") or labels.get("job") or "unknown-service"
        summary = annotations.get("summary") or annotations.get("description") or labels.get("alertname") or "Alertmanager alert"
        incident = create_incident(str(service)[:200], str(summary)[:2000], "alertmanager", labels)
        accepted.append({"id": incident["id"], "service": service})
    return {"accepted": accepted}


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": f"Request failed safely ({type(exc).__name__})"})
