"""GitLab REST API v4 connector (PRIVATE-TOKEN auth)."""

from __future__ import annotations

from typing import Any

import requests


class GitLabConnector:
    """Fetches MRs, issues from GitLab via REST API v4."""

    def __init__(self, base_url: str, token: str):
        """
        Args:
            base_url: e.g. https://gitlab-master.nvidia.com
            token:    GitLab personal access token.
        """
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "PRIVATE-TOKEN": token,
            "Accept": "application/json",
        })

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}/api/v4{path}"
        resp = self._session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_my_mrs(self, limit: int = 20) -> list[dict]:
        """Return open MRs authored by the authenticated user."""
        data = self._get("/merge_requests", params={
            "scope": "created_by_me",
            "state": "opened",
            "per_page": limit,
            "order_by": "updated_at",
            "sort": "desc",
        })
        return self._format_mrs(data)

    def get_review_mrs(self, limit: int = 20) -> list[dict]:
        """Return open MRs assigned to the authenticated user for review."""
        data = self._get("/merge_requests", params={
            "scope": "assigned_to_me",
            "state": "opened",
            "per_page": limit,
            "order_by": "updated_at",
            "sort": "desc",
        })
        return self._format_mrs(data)

    def get_my_issues(self, limit: int = 20) -> list[dict]:
        """Return open issues assigned to the authenticated user."""
        data = self._get("/issues", params={
            "scope": "assigned_to_me",
            "state": "opened",
            "per_page": limit,
            "order_by": "updated_at",
            "sort": "desc",
        })
        return self._format_issues(data)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search issues and MRs by keyword."""
        issues = self._get("/issues", params={
            "search": query,
            "scope": "all",
            "per_page": limit // 2 or 10,
            "order_by": "updated_at",
            "sort": "desc",
        })
        mrs = self._get("/merge_requests", params={
            "search": query,
            "scope": "all",
            "per_page": limit // 2 or 10,
            "order_by": "updated_at",
            "sort": "desc",
        })
        return self._format_issues(issues) + self._format_mrs(mrs)

    def _format_mrs(self, items: list[dict]) -> list[dict]:
        result = []
        for mr in items:
            result.append({
                "iid": mr.get("iid"),
                "title": mr.get("title", ""),
                "state": mr.get("state", ""),
                "kind": "MR",
                "project": mr.get("references", {}).get("full", mr.get("web_url", "")),
                "source_branch": mr.get("source_branch", ""),
                "target_branch": mr.get("target_branch", ""),
                "updated_at": mr.get("updated_at", ""),
                "url": mr.get("web_url", ""),
                "description_preview": (mr.get("description") or "")[:300],
            })
        return result

    def _format_issues(self, items: list[dict]) -> list[dict]:
        result = []
        for issue in items:
            result.append({
                "iid": issue.get("iid"),
                "title": issue.get("title", ""),
                "state": issue.get("state", ""),
                "kind": "Issue",
                "project": issue.get("references", {}).get("full", ""),
                "labels": issue.get("labels", []),
                "updated_at": issue.get("updated_at", ""),
                "url": issue.get("web_url", ""),
                "description_preview": (issue.get("description") or "")[:300],
            })
        return result
