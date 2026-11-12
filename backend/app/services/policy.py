from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

import yaml
import re

from ..config import settings

FORBIDDEN_PARTS = {".github/workflows", "secrets", "rbac", "networkpolicy", "clusterrole", "clusterrolebinding"}
ALLOWED_DECISIONS = {"INFRA_FIX", "CODE_FIX", "ROLLBACK", "ESCALATE_HUMAN"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{24,}"),
    re.compile(r"(?im)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*[\"']?(?!\$\{|\{\{)[^\"'\s,;#]{12,}"),
)


def _within(path: str, prefixes: tuple[str, ...]) -> bool:
    normalized = PurePosixPath(path.replace("\\", "/")).as_posix().lstrip("/")
    return ".." not in PurePosixPath(normalized).parts and any(
        normalized == p or normalized.startswith(p.rstrip("/") + "/") for p in prefixes)


def _changed_paths(before: Any, after: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changed: list[tuple[str, ...]] = []
        for key in before.keys() | after.keys():
            if key not in before or key not in after:
                changed.append((*prefix, str(key)))
            else:
                changed.extend(_changed_paths(before[key], after[key], (*prefix, str(key))))
        return changed
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [prefix]
        changed = []
        for index, (old_item, new_item) in enumerate(zip(before, after)):
            changed.extend(_changed_paths(old_item, new_item, (*prefix, str(index))))
        return changed
    return [] if before == after else [prefix]


def validate_proposal(decision: dict[str, Any], patches: list[dict[str, str]]) -> dict[str, Any]:
    action = decision.get("action")
    if action not in ALLOWED_DECISIONS:
        return {"allowed": False, "requires_approval": False, "reasons": ["Unknown decision type"]}
    if action == "ESCALATE_HUMAN":
        return {"allowed": False, "requires_approval": True, "reasons": ["Decision requires human escalation"]}
    if not patches:
        return {"allowed": False, "requires_approval": False, "reasons": ["No patch was generated"]}
    if len(patches) > settings.max_patch_files:
        return {"allowed": False, "requires_approval": False, "reasons": ["Patch changes too many files"]}
    total = sum(len(p.get("content", "").encode("utf-8")) for p in patches)
    if total > settings.max_patch_bytes:
        return {"allowed": False, "requires_approval": False, "reasons": ["Patch exceeds byte limit"]}
    reasons: list[str] = []
    seen_paths: set[str] = set()
    for patch in patches:
        path = patch.get("path", "")
        normalized = path.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        if not path or path.startswith(("/", "\\")) or ".." in parts or "\x00" in path or ":" in path:
            reasons.append(f"Unsafe path: {path!r}")
            continue
        lowered = path.lower()
        if normalized in seen_paths:
            reasons.append(f"Duplicate patch path: {normalized}")
        seen_paths.add(normalized)
        if any(word in lowered for word in FORBIDDEN_PARTS):
            reasons.append(f"Protected path is forbidden: {path}")
        content = patch.get("content", "")
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            reasons.append(f"Patch appears to contain a credential or private key: {path}")
        if action == "INFRA_FIX":
            if not _within(normalized, settings.infra_allowed_paths):
                reasons.append(f"Infrastructure path is outside allowlist: {path}")
            if not normalized.lower().endswith((".yaml", ".yml")):
                reasons.append(f"Infrastructure changes must target YAML manifests: {path}")
            try:
                base_doc = yaml.safe_load(patch.get("base_content", ""))
                proposed_doc = yaml.safe_load(content)
                if not isinstance(base_doc, dict) or not isinstance(proposed_doc, dict):
                    reasons.append(f"Infrastructure patch must replace a single YAML object: {path}")
                else:
                    for field in ("apiVersion", "kind"):
                        if base_doc.get(field) != proposed_doc.get(field):
                            reasons.append(f"Infrastructure identity field cannot change: {path} ({field})")
                    for field in ("name", "namespace"):
                        if base_doc.get("metadata", {}).get(field) != proposed_doc.get("metadata", {}).get(field):
                            reasons.append(f"Infrastructure object identity cannot change: {path} ({field})")
                    changed = _changed_paths(base_doc, proposed_doc)
                    if not changed:
                        reasons.append(f"Infrastructure patch has no effective change: {path}")
                    for field_path in changed:
                        if field_path != ("spec", "replicas"):
                            reasons.append(f"Infrastructure field is outside the Phase I change policy: {path} ({'.'.join(field_path)})")
                    replicas = proposed_doc.get("spec", {}).get("replicas")
                    if any(field_path == ("spec", "replicas") for field_path in changed) and (
                            not isinstance(replicas, int) or replicas < 1 or replicas > 10):
                        reasons.append(f"Replica count must be an integer from 1 to 10: {path}")
            except yaml.YAMLError:
                reasons.append(f"Invalid YAML: {path}")
        elif action == "CODE_FIX" and not _within(normalized, settings.code_allowed_paths):
            reasons.append(f"Code path is outside allowlist: {path}")
        if not patch.get("sha"):
            reasons.append(f"Missing base file SHA: {path}")
    if reasons:
        return {"allowed": False, "requires_approval": False, "reasons": reasons}
    return {"allowed": True, "requires_approval": True,
            "reasons": [], "rule_version": "phase1-v1", "patch_files": [p["path"] for p in patches],
            "patch_bytes": total}
