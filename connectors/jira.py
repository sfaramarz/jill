"""Jira Server/Data Center REST API v2 connector.

Supports both:
- Personal Access Token (PAT): Authorization: Bearer <token>  [preferred]
- Basic Auth: username:password or username:api_token
"""

from __future__ import annotations

import requests
from requests.auth import HTTPBasicAuth
from typing import Any


class JiraConnector:
    """Fetches issues and activity from Jira Server/DC via REST API v2."""

    def __init__(self, base_url: str, api_token: str, username: str = "", email: str = ""):
        """
        Args:
            base_url:   e.g. https://jirasw.nvidia.com
            api_token:  Personal Access Token (PAT) — preferred, sent as Bearer token.
                        If username is also provided, falls back to Basic Auth.
            username:   LDAP/AD username for Basic Auth fallback.
            email:      Ignored for Server (kept for API compatibility).
        """
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

        if username and api_token:
            # Basic Auth with username:token (older Jira Server / no PAT support)
            self._session.auth = HTTPBasicAuth(username, api_token)
        elif api_token:
            # PAT — Bearer token (Jira Server 8.14+ / Data Center)
            self._session.headers["Authorization"] = f"Bearer {api_token}"
        else:
            raise ValueError("Either api_token (for PAT) or both username+api_token (for Basic Auth) must be provided.")

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}/rest/api/2{path}"
        resp = self._session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_current_user(self) -> dict:
        """Return the authenticated user's account info."""
        return self._get("/myself")

    def get_assigned_issues(self, max_results: int = 50) -> list[dict]:
        """Return open issues assigned to the current user."""
        jql = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
        data = self._get("/search", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,project,assignee,updated,description,labels,issuetype",
        })
        return self._format_issues(data.get("issues", []))

    def get_sprint_issues(self, max_results: int = 50) -> list[dict]:
        """Return issues in the current active sprint for the authenticated user."""
        jql = (
            "assignee = currentUser() AND sprint in openSprints() "
            "ORDER BY priority ASC, updated DESC"
        )
        data = self._get("/search", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,project,assignee,updated,description,labels,issuetype,sprint",
        })
        return self._format_issues(data.get("issues", []))

    def get_recent_activity(self, max_results: int = 20) -> list[dict]:
        """Return recently updated issues involving the current user."""
        jql = (
            "assignee = currentUser() OR reporter = currentUser() "
            "ORDER BY updated DESC"
        )
        data = self._get("/search", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,project,updated,issuetype",
        })
        return self._format_issues(data.get("issues", []))

    def search_issues(self, query: str, max_results: int = 20) -> list[dict]:
        """Full-text search across issues visible to the current user."""
        jql = f'text ~ "{query}" ORDER BY updated DESC'
        data = self._get("/search", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,project,updated,description,issuetype",
        })
        return self._format_issues(data.get("issues", []))

    def get_project_issues(self, project_key: str, max_results: int = 50) -> list[dict]:
        """Return open issues for a Jira project ordered by priority then recency."""
        jql = (
            f"project = {project_key} AND statusCategory != Done "
            "ORDER BY priority DESC, updated DESC"
        )
        data = self._get("/search", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": (
                "summary,status,priority,project,assignee,updated,"
                "description,labels,issuetype,fixVersions,components"
            ),
        })
        return self._format_issues(data.get("issues", []))

    # -------------------------------------------------------------------------
    # Write methods
    # -------------------------------------------------------------------------

    def _post(self, path: str, json_body: dict) -> Any:
        url = f"{self.base_url}/rest/api/2{path}"
        resp = self._session.post(url, json=json_body, timeout=15)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def create_issue(
        self,
        project_key: str,
        summary: str,
        description: str = "",
        issue_type: str = "Task",
        labels: list[str] | None = None,
    ) -> dict:
        """Create a new Jira issue and return the created issue dict."""
        body: dict = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": issue_type},
            }
        }
        if description:
            body["fields"]["description"] = description
        if labels:
            body["fields"]["labels"] = labels
        data = self._post("/issue", body)
        return {
            "key": data.get("key", ""),
            "url": f"{self.base_url}/browse/{data.get('key', '')}",
        }

    def add_comment(self, issue_key: str, comment: str) -> dict:
        """Add a comment to an existing issue."""
        return self._post(f"/issue/{issue_key}/comment", {"body": comment})

    def get_available_transitions(self, issue_key: str) -> list[dict]:
        """Return the list of available workflow transitions for an issue."""
        data = self._get(f"/issue/{issue_key}/transitions")
        return [
            {"id": t.get("id", ""), "name": t.get("name", "")}
            for t in data.get("transitions", [])
        ]

    def transition_issue(self, issue_key: str, transition_name: str) -> None:
        """Transition an issue by transition name (case-insensitive match)."""
        transitions = self.get_available_transitions(issue_key)
        match = next(
            (t for t in transitions if t["name"].lower() == transition_name.lower()),
            None,
        )
        if not match:
            available = [t["name"] for t in transitions]
            raise ValueError(
                f"Transition '{transition_name}' not found for {issue_key}. "
                f"Available: {available}"
            )
        self._post(f"/issue/{issue_key}/transitions", {"transition": {"id": match["id"]}})

    def _format_issues(self, issues: list[dict]) -> list[dict]:
        """Flatten Jira issue objects into a clean dict for LLM context."""
        result = []
        for issue in issues:
            fields = issue.get("fields", {})
            status = fields.get("status", {})
            priority = fields.get("priority", {})
            project = fields.get("project", {})
            issue_type = fields.get("issuetype", {})

            # Server returns description as plain text or wiki markup (not ADF)
            description = fields.get("description") or ""
            if not isinstance(description, str):
                # Unexpected type — try to stringify
                description = str(description)

            result.append({
                "key": issue.get("key", ""),
                "summary": fields.get("summary", ""),
                "status": status.get("name", "Unknown"),
                "priority": priority.get("name", "None"),
                "project": project.get("name", ""),
                "issue_type": issue_type.get("name", ""),
                "updated": fields.get("updated", ""),
                "labels": fields.get("labels", []),
                "description": description[:500],
                "url": f"{self.base_url}/browse/{issue.get('key', '')}",
            })
        return result
