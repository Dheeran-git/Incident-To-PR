from __future__ import annotations

import re
from urllib.parse import urlparse

from ..config import settings
from ..database import get_app_setting


def normalize_github_repository(value: str) -> str:
    raw = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", raw):
        owner, repository = raw.split("/", 1)
    else:
        parsed = urlparse(raw)
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
            raise ValueError("Enter an HTTPS github.com repository link (or owner/repository).")
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) != 2:
            raise ValueError("A repository link must point directly to https://github.com/OWNER/REPOSITORY.")
        owner, repository = parts
        if repository.lower().endswith(".git"):
            repository = repository[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repository owner or name contains unsupported characters.")
    return f"{owner}/{repository}"


def repository_config() -> dict[str, str]:
    return {
        "code_repository": get_app_setting("code_repository", settings.github_code_repository),
        "gitops_repository": get_app_setting("gitops_repository", settings.github_gitops_repository),
    }


def auto_monitor_config() -> dict[str, bool]:
    return {
        "enabled": get_app_setting("auto_monitor_enabled", "false").lower() == "true",
        "auto_analyze": get_app_setting("auto_analyze_enabled", "false").lower() == "true",
    }
