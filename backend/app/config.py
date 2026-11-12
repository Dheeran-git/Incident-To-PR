from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(value.strip().strip("/") for value in os.getenv(name, default).split(",") if value.strip())


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    database_path: Path = Path(os.getenv("DATABASE_PATH", "./data/incident-to-pr.sqlite3"))
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_api_base: str = os.getenv("LLM_API_BASE", "")
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "3000"))
    llm_fallback_model: str = os.getenv("LLM_FALLBACK_MODEL", "")
    llm_fallback_api_key: str = os.getenv("LLM_FALLBACK_API_KEY", "")
    llm_fallback_api_base: str = os.getenv("LLM_FALLBACK_API_BASE", "")
    llm_trace_enabled: bool = os.getenv("LLM_TRACE_ENABLED", "true").lower() == "true"
    k8s_namespace: str = os.getenv("K8S_NAMESPACE", "online-boutique")
    k8s_context: str = os.getenv("K8S_CONTEXT", "")
    prometheus_url: str = os.getenv("PROMETHEUS_URL", "")
    prometheus_query: str = os.getenv("PROMETHEUS_QUERY", "up")
    prometheus_health_query: str = os.getenv("PROMETHEUS_HEALTH_QUERY", 'up{service="$service"}')
    verification_window_minutes: int = max(15, int(os.getenv("VERIFICATION_WINDOW_MINUTES", "15")))
    verification_minimum_samples: int = max(10, int(os.getenv("VERIFICATION_MINIMUM_SAMPLES", "20")))
    loki_url: str = os.getenv("LOKI_URL", "")
    loki_query: str = os.getenv("LOKI_QUERY", '{namespace="online-boutique"}')
    alertmanager_webhook_token: str = os.getenv("ALERTMANAGER_WEBHOOK_TOKEN", "")
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_argocd_read_token: str = os.getenv("GITHUB_ARGOCD_READ_TOKEN", "")
    github_api_url: str = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    github_code_repository: str = os.getenv("GITHUB_CODE_REPOSITORY", "")
    github_gitops_repository: str = os.getenv("GITHUB_GITOPS_REPOSITORY", "")
    github_base_branch: str = os.getenv("GITHUB_BASE_BRANCH", "main")
    github_bot_name: str = os.getenv("GITHUB_BOT_NAME", "Incident-to-PR Bot")
    github_bot_email: str = os.getenv("GITHUB_BOT_EMAIL", "incident-to-pr[bot]@users.noreply.github.com")
    code_allowed_paths: tuple[str, ...] = _csv("CODE_ALLOWED_PATHS", "src/shippingservice/")
    infra_allowed_paths: tuple[str, ...] = _csv("INFRA_ALLOWED_PATHS", "deploy/online-boutique/")
    code_context_files: tuple[str, ...] = _csv("CODE_CONTEXT_FILES", "src/shippingservice/main.go")
    infra_context_files: tuple[str, ...] = _csv("INFRA_CONTEXT_FILES", "deploy/online-boutique/shippingservice.yaml")
    max_patch_files: int = int(os.getenv("MAX_PATCH_FILES", "3"))
    max_patch_bytes: int = int(os.getenv("MAX_PATCH_BYTES", "200000"))
    argocd_url: str = os.getenv("ARGOCD_URL", "").rstrip("/")
    argocd_application: str = os.getenv("ARGOCD_APPLICATION", "online-boutique")
    argocd_token: str = os.getenv("ARGOCD_TOKEN", "")
    argocd_verify_tls: bool = os.getenv("ARGOCD_VERIFY_TLS", "true").lower() == "true"
    evaluator_url: str = os.getenv("EVALUATOR_URL", "").rstrip("/")
    evaluator_token: str = os.getenv("EVALUATOR_TOKEN", "")
    require_human_approval: bool = True
    max_open_incidents: int = int(os.getenv("MAX_OPEN_INCIDENTS", "20"))
    evidence_max_age_seconds: int = int(os.getenv("EVIDENCE_MAX_AGE_SECONDS", "300"))
    auto_apply_enabled: bool = False


settings = Settings()
