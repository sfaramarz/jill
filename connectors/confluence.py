"""Confluence Server/Data Center REST API connector.

Supports both:
- Personal Access Token (PAT): Authorization: Bearer <token>  [preferred]
- Basic Auth: username:password or username:api_token
"""

from __future__ import annotations

import requests
from requests.auth import HTTPBasicAuth
from typing import Any


class ConfluenceConnector:
    """Fetches pages and content from Confluence Server/DC via REST API."""

    def __init__(self, base_url: str, api_token: str, username: str = "", email: str = ""):
        """
        Args:
            base_url:   e.g. https://confluence.nvidia.com
            api_token:  PAT (Bearer) or password for Basic Auth.
            username:   LDAP/AD username; if provided, uses Basic Auth instead of Bearer.
            email:      Ignored for Server (kept for API compatibility).
        """
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

        if username and api_token:
            self._session.auth = HTTPBasicAuth(username, api_token)
        elif api_token:
            self._session.headers["Authorization"] = f"Bearer {api_token}"
        else:
            raise ValueError("Either api_token (PAT) or both username+api_token required.")

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}/rest/api{path}"
        resp = self._session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_recent_pages(self, limit: int = 20) -> list[dict]:
        """Return recently modified pages accessible to the current user."""
        data = self._get("/content", params={
            "type": "page",
            "status": "current",
            "orderby": "modified",
            "limit": limit,
            "expand": "body.storage,space,version,history.lastUpdated",
        })
        return self._format_pages(data.get("results", []))

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search Confluence using CQL (Confluence Query Language)."""
        cql = f'type = page AND text ~ "{query}" ORDER BY lastmodified DESC'
        data = self._get("/content/search", params={
            "cql": cql,
            "limit": limit,
            "expand": "body.storage,space,version,history.lastUpdated",
        })
        return self._format_pages(data.get("results", []))

    def get_spaces(self) -> list[dict]:
        """Return a list of spaces accessible to the current user."""
        data = self._get("/space", params={"limit": 50, "type": "global"})
        return [
            {"key": s.get("key", ""), "name": s.get("name", "")}
            for s in data.get("results", [])
        ]

    @staticmethod
    def extract_page_id_from_url(url: str) -> str:
        """Parse a Confluence page ID from a URL.

        Supported formats:
        - ?pageId=12345  (older Server query-param style)
        - /pages/12345   (path-based, Cloud / newer Server)
        - /wiki/spaces/X/pages/12345
        """
        import re
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "pageId" in qs:
            return qs["pageId"][0]
        match = re.search(r"/pages/(\d+)", parsed.path)
        if match:
            return match.group(1)
        raise ValueError(
            f"Cannot extract page ID from URL: {url}\n"
            "Supported formats: /pages/<id>, ?pageId=<id>"
        )

    def get_page_by_id(self, page_id: str) -> dict:
        """Fetch a single page by its numeric ID.

        Returns full metadata plus raw storage XHTML and stripped plain text.
        """
        data = self._get(
            f"/content/{page_id}",
            params={"expand": "body.storage,space,version,history.lastUpdated"},
        )
        space = data.get("space", {})
        version = data.get("version", {})
        history = data.get("history", {})
        last_updated = history.get("lastUpdated", {})
        raw_html = data.get("body", {}).get("storage", {}).get("value", "")
        page_id_val = data.get("id", page_id)
        return {
            "id": page_id_val,
            "title": data.get("title", ""),
            "space": space.get("name", space.get("key", "")),
            "space_key": space.get("key", ""),
            "version": version.get("number", 1),
            "last_modified": last_updated.get("when", version.get("when", "")),
            "last_modified_by": last_updated.get("by", {}).get("displayName", ""),
            "storage_html": raw_html,
            "content": self._strip_html(raw_html)[:3000],
            "url": f"{self.base_url}/pages/{page_id_val}",
        }

    # -------------------------------------------------------------------------
    # Write methods
    # -------------------------------------------------------------------------

    def _post(self, path: str, json_body: dict) -> Any:
        url = f"{self.base_url}/rest/api{path}"
        resp = self._session.post(url, json=json_body, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, json_body: dict) -> Any:
        url = f"{self.base_url}/rest/api{path}"
        resp = self._session.put(url, json=json_body, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def create_page(
        self,
        space_key: str,
        title: str,
        body_html: str,
        parent_id: str | None = None,
    ) -> dict:
        """Create a new Confluence page and return its id, title, and url."""
        payload: dict = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage",
                }
            },
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        data = self._post("/content", payload)
        page_id = data.get("id", "")
        return {
            "id": page_id,
            "title": data.get("title", title),
            "url": f"{self.base_url}/pages/{page_id}",
        }

    def update_page(self, page_id: str, title: str, body_html: str) -> dict:
        """Update an existing page (fetches current version first, then PUTs)."""
        current = self._get(f"/content/{page_id}", params={"expand": "version"})
        current_version = current.get("version", {}).get("number", 1)
        payload = {
            "version": {"number": current_version + 1},
            "title": title,
            "type": "page",
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage",
                }
            },
        }
        data = self._put(f"/content/{page_id}", payload)
        return {
            "id": page_id,
            "title": data.get("title", title),
            "url": f"{self.base_url}/pages/{page_id}",
        }

    def _format_pages(self, pages: list[dict]) -> list[dict]:
        """Flatten Confluence page objects into clean dicts for LLM context."""
        result = []
        for page in pages:
            space = page.get("space", {})
            version = page.get("version", {})
            history = page.get("history", {})
            last_updated = history.get("lastUpdated", {})

            # Strip HTML from body.storage to get plain text
            body_storage = page.get("body", {}).get("storage", {})
            raw_html = body_storage.get("value", "")
            plain_text = self._strip_html(raw_html)

            page_id = page.get("id", "")
            title = page.get("title", "")

            result.append({
                "id": page_id,
                "title": title,
                "space": space.get("name", space.get("key", "")),
                "version": version.get("number", 1),
                "last_modified": last_updated.get("when", version.get("when", "")),
                "last_modified_by": last_updated.get("by", {}).get("displayName", ""),
                "content": plain_text[:3000],  # cap per page to avoid token overflow
                "url": f"{self.base_url}/pages/{page_id}" if page_id else "",
            })
        return result

    def _strip_html(self, html: str) -> str:
        """Very lightweight HTML stripping — removes tags, decodes common entities."""
        import re
        # Remove script/style blocks
        html = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        # Remove all tags
        html = re.sub(r"<[^>]+>", " ", html)
        # Decode common HTML entities
        html = (
            html.replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&nbsp;", " ")
                .replace("&quot;", '"')
                .replace("&#39;", "'")
        )
        # Collapse whitespace
        html = re.sub(r"\s+", " ", html).strip()
        return html
