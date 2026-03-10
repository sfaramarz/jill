"""NVBugs REST API connector.

Uses a Bearer token (NVAuth) for authentication.
Set NVBUGS_API_TOKEN in your .env file.
"""

from __future__ import annotations

import json
from typing import Any

import requests


_DEFAULT_BASE_URL = "https://prod.api.nvidia.com/int/nvbugs"


class NVBugsConnector:
    """Fetches and searches NVBugs via the NVBugs REST API."""

    def __init__(self, token: str, base_url: str = _DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get_bug(self, bug_id: int) -> dict:
        """Return full details for a single bug."""
        resp = self._session.get(
            f"{self.base_url}/api/Bug/GetBug/{bug_id}", timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
        return self._format_bug(data.get("ReturnValue", data))

    def search_bugs(
        self,
        filters: list[dict[str, str]],
        limit: int = 50,
        page: int = 1,
    ) -> list[dict]:
        """Search bugs by field filters.

        Each filter is {"FieldName": "...", "FieldValue": "..."}.
        Common fields: ModuleName, AssignedTo, Status, Priority,
        Synopsis, CustomKeyword, ReportedBy, DaysOpen.
        """
        resp = self._session.post(
            f"{self.base_url}/api/Search/GetBugs",
            params={"page": page, "limit": limit},
            data=json.dumps(filters),
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        bugs = result.get("ReturnValue") or []
        return [self._format_bug(b) for b in bugs]

    def get_assigned_bugs(self, username: str, limit: int = 25) -> list[dict]:
        """Return open bugs assigned to a specific user."""
        return self.search_bugs(
            filters=[
                {"FieldName": "AssignedTo", "FieldValue": username},
                {"FieldName": "Status", "FieldValue": "Open"},
            ],
            limit=limit,
        )

    def search_by_module(self, module_name: str, limit: int = 25) -> list[dict]:
        """Return bugs for a given component/module."""
        return self.search_bugs(
            filters=[{"FieldName": "ModuleName", "FieldValue": module_name}],
            limit=limit,
        )

    def search_by_keyword(self, keyword: str, limit: int = 25) -> list[dict]:
        """Full-text search via Synopsis field."""
        return self.search_bugs(
            filters=[{"FieldName": "Synopsis", "FieldValue": keyword}],
            limit=limit,
        )

    def add_comment(self, bug_id: int, text: str, notify: bool = True) -> dict:
        """Add a comment to an NVBug."""
        resp = self._session.post(
            f"{self.base_url}/api/Bug/Comments/{bug_id}",
            data=json.dumps({"Text": text, "Notification": notify}),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_bug(self, bug: dict) -> dict:
        """Normalize a raw NVBugs API dict into a clean flat dict."""
        if not bug:
            return {}
        bug_id = bug.get("BugId") or bug.get("BugID") or ""
        return {
            "id": bug_id,
            "synopsis": bug.get("Synopsis", ""),
            "status": bug.get("BugAction", bug.get("Status", "")),
            "disposition": bug.get("Disposition", ""),
            "priority": bug.get("BugPriority", ""),
            "severity": bug.get("BugSeverity", ""),
            "module": bug.get("ModuleName", ""),
            "assigned_to": bug.get("BugEngineerFullName", bug.get("AssignedTo", "")),
            "reported_by": bug.get("BugRequesterFullName", bug.get("ReportedBy", "")),
            "submitted": (bug.get("RequestDate") or "")[:10],
            "days_open": bug.get("DaysOpen", ""),
            "os": bug.get("OperatingSystem", ""),
            "version": bug.get("Version", ""),
            "keywords": bug.get("CustomKeyword", ""),
            "url": f"https://nvbugs/Bug/{bug_id}" if bug_id else "",
        }
