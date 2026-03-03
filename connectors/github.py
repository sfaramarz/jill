"""GitHub REST API v3 connector (PAT Bearer auth)."""

from __future__ import annotations

from typing import Any

import requests


class GitHubConnector:
    """Fetches PRs, issues, and commits from GitHub via REST API v3."""

    BASE = "https://api.github.com"

    def __init__(self, token: str, username: str, org: str = ""):
        """
        Args:
            token:    Personal Access Token — sent as Bearer token.
            username: GitHub username of the authenticated user.
            org:      Optional GitHub org/owner to scope searches.
        """
        self.username = username
        self.org = org
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = path if path.startswith("https://") else f"{self.BASE}{path}"
        resp = self._session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_my_prs(self, limit: int = 20) -> list[dict]:
        """Return open PRs authored by the configured user."""
        q = f"is:pr is:open author:{self.username}"
        if self.org:
            q += f" org:{self.org}"
        data = self._get("/search/issues", params={"q": q, "per_page": limit, "sort": "updated"})
        return self._format_issues(data.get("items", []), kind="PR")

    def get_review_requests(self, limit: int = 20) -> list[dict]:
        """Return open PRs where the user is a requested reviewer."""
        q = f"is:pr is:open review-requested:{self.username}"
        if self.org:
            q += f" org:{self.org}"
        data = self._get("/search/issues", params={"q": q, "per_page": limit, "sort": "updated"})
        return self._format_issues(data.get("items", []), kind="PR")

    def get_my_issues(self, limit: int = 20) -> list[dict]:
        """Return open issues assigned to the configured user."""
        q = f"is:issue is:open assignee:{self.username}"
        if self.org:
            q += f" org:{self.org}"
        data = self._get("/search/issues", params={"q": q, "per_page": limit, "sort": "updated"})
        return self._format_issues(data.get("items", []), kind="Issue")

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across issues and PRs."""
        q = query
        if self.org:
            q += f" org:{self.org}"
        data = self._get("/search/issues", params={"q": q, "per_page": limit, "sort": "updated"})
        return self._format_issues(data.get("items", []), kind="")

    def get_recent_commits(self, repo: str, branch: str = "main", limit: int = 20) -> list[dict]:
        """Return recent commits on a repo branch.

        Args:
            repo:   Full repo name, e.g. ``nvidia/my-repo`` or just ``my-repo``
                    (org will be prepended if configured and absent).
            branch: Branch name (default: main).
            limit:  Number of commits to return.
        """
        if "/" not in repo and self.org:
            repo = f"{self.org}/{repo}"
        data = self._get(f"/repos/{repo}/commits", params={"sha": branch, "per_page": limit})
        commits = []
        for c in data:
            commit = c.get("commit", {})
            author = commit.get("author", {})
            commits.append({
                "sha": c.get("sha", "")[:7],
                "message": commit.get("message", "").split("\n")[0],
                "author": author.get("name", ""),
                "date": author.get("date", ""),
                "url": c.get("html_url", ""),
                "repo": repo,
            })
        return commits

    def _format_issues(self, items: list[dict], kind: str = "") -> list[dict]:
        """Flatten GitHub search result items into clean dicts."""
        result = []
        for item in items:
            # Determine kind from item if not forced
            item_kind = kind
            if not item_kind:
                item_kind = "PR" if "pull_request" in item else "Issue"
            # Extract repo from url: https://api.github.com/repos/OWNER/REPO/issues/N
            url = item.get("html_url", "")
            repo = ""
            parts = url.replace("https://github.com/", "").split("/")
            if len(parts) >= 2:
                repo = f"{parts[0]}/{parts[1]}"

            result.append({
                "number": item.get("number"),
                "title": item.get("title", ""),
                "state": item.get("state", ""),
                "kind": item_kind,
                "repo": repo,
                "labels": [lb.get("name", "") for lb in item.get("labels", [])],
                "updated_at": item.get("updated_at", ""),
                "url": url,
                "body_preview": (item.get("body") or "")[:300],
            })
        return result
