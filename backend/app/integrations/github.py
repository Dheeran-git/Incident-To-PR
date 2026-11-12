from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import quote

import httpx

from ..config import settings


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self) -> None:
        if not settings.github_token:
            raise GitHubError("GITHUB_TOKEN is not configured")
        self.headers = {"Authorization": f"Bearer {settings.github_token}",
                        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    async def get_repository(self, repository: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise GitHubError("Repository must be owner/name")
        item = await self._request("GET", f"/repos/{repository}")
        return {"full_name": item.get("full_name"), "private": bool(item.get("private")),
                "default_branch": item.get("default_branch")}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.request(method, settings.github_api_url + path, headers=self.headers, **kwargs)
        if response.status_code >= 400:
            raise GitHubError(f"GitHub API returned {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else {}

    async def get_file(self, repository: str, branch: str, path: str) -> dict[str, str]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise GitHubError("Repository must be owner/name")
        encoded_path = "/".join(quote(segment, safe="") for segment in path.strip("/").split("/"))
        item = await self._request("GET", f"/repos/{repository}/contents/{encoded_path}", params={"ref": branch})
        if item.get("type") != "file" or not item.get("content"):
            raise GitHubError(f"{path} is not a readable file")
        content = base64.b64decode(item["content"]).decode("utf-8")
        return {"path": path, "sha": item["sha"], "content": content}

    async def create_pull_request(self, repository: str, base: str, title: str, body: str,
                                  patches: list[dict[str, str]], incident_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise GitHubError("Repository must be owner/name")
        if not patches:
            raise GitHubError("No validated patches supplied")
        # Make retries safe after a timeout that happened after GitHub created the PR.
        branch = f"incident-to-pr/{incident_id[:8]}"
        existing = await self._request("GET", f"/repos/{repository}/pulls",
                                       params={"state": "all", "head": f"{repository.split('/')[0]}:{branch}", "base": base})
        if existing:
            pr = existing[0]
            return {"number": pr["number"], "url": pr["html_url"], "state": pr["state"],
                    "merged": bool(pr.get("merged_at")), "merged_at": pr.get("merged_at"),
                    "head_branch": branch, "base_branch": base, "repository": repository}
        ref_path = "/".join(quote(segment, safe="") for segment in f"heads/{base}".split("/"))
        ref = await self._request("GET", f"/repos/{repository}/git/ref/{ref_path}")
        base_sha = ref["object"]["sha"]
        await self._request("POST", f"/repos/{repository}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha})
        for patch in patches:
            path = "/".join(quote(segment, safe="") for segment in patch["path"].strip("/").split("/"))
            payload = {"message": f"Incident {incident_id[:8]}: propose remediation",
                       "content": base64.b64encode(patch["content"].encode("utf-8")).decode("ascii"),
                       "branch": branch, "committer": {"name": settings.github_bot_name, "email": settings.github_bot_email}}
            payload["sha"] = patch["sha"]
            await self._request("PUT", f"/repos/{repository}/contents/{path}", json=payload)
        pr = await self._request("POST", f"/repos/{repository}/pulls", json={
            "title": title[:250], "body": body[:6000], "head": branch, "base": base, "draft": False})
        return {"number": pr["number"], "url": pr["html_url"], "state": pr["state"],
                "merged": bool(pr.get("merged_at")), "merged_at": pr.get("merged_at"),
                "head_branch": branch, "base_branch": base, "repository": repository}

    async def get_pull_request(self, repository: str, number: int) -> dict[str, Any]:
        pr = await self._request("GET", f"/repos/{repository}/pulls/{number}")
        return {"number": pr["number"], "url": pr["html_url"], "state": pr["state"],
                "merged": bool(pr["merged"]), "merged_at": pr.get("merged_at"),
                "head_sha": pr["head"]["sha"], "base_sha": pr["base"]["sha"]}
