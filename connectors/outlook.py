"""Microsoft Outlook / M365 connector via Microsoft Graph API.

Uses MSAL PublicClientApplication with interactive browser auth on first run.
A local HTTP server captures the OAuth redirect automatically — no codes to copy.
Token is cached to ~/.jill_outlook_token.json and auto-refreshed via MSAL cache.

Required Graph API permissions (delegated):
    Mail.Read, offline_access

Azure app registration redirect URI required:
    http://localhost  (Mobile and desktop applications platform)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import msal
import requests

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["Mail.Read", "offline_access"]
_TOKEN_CACHE_PATH = Path.home() / ".jill_outlook_token.json"


class OutlookConnector:
    """Reads emails from Outlook / Microsoft 365 via the Graph API."""

    def __init__(self, tenant_id: str, client_id: str):
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._cache = msal.SerializableTokenCache()
        if _TOKEN_CACHE_PATH.exists():
            self._cache.deserialize(_TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
        self._app = msal.PublicClientApplication(
            client_id=client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            token_cache=self._cache,
        )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def authenticate(self) -> str:
        """Return a valid access token, opening the browser on first run."""
        # Try silent refresh first (uses cached token)
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache()
                return result["access_token"]

        # Interactive browser flow — opens default browser, captures redirect on localhost
        print("Opening browser for Microsoft sign-in...")
        result = self._app.acquire_token_interactive(
            scopes=_SCOPES,
            prompt="select_account",
        )
        if "access_token" not in result:
            raise RuntimeError(
                f"Authentication failed: {result.get('error_description', result.get('error'))}"
            )
        self._save_cache()
        return result["access_token"]

    def _save_cache(self) -> None:
        if self._cache.has_state_changed:
            _TOKEN_CACHE_PATH.write_text(self._cache.serialize(), encoding="utf-8")

    # ------------------------------------------------------------------
    # Public read methods
    # ------------------------------------------------------------------

    def get_recent_emails(self, count: int = 10) -> list[dict]:
        """Return the top N most recent emails from the inbox."""
        token = self.authenticate()
        params = {
            "$top": count,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,body",
        }
        data = self._get("/me/messages", token, params)
        return [self._parse_email(m) for m in data.get("value", [])]

    def get_unread_emails(self, count: int = 10) -> list[dict]:
        """Return unread emails from the inbox."""
        token = self.authenticate()
        params = {
            "$top": count,
            "$orderby": "receivedDateTime desc",
            "$filter": "isRead eq false",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,body",
        }
        data = self._get("/me/messages", token, params)
        return [self._parse_email(m) for m in data.get("value", [])]

    def get_last_email(self) -> dict | None:
        """Return the single most recent email."""
        emails = self.get_recent_emails(count=1)
        return emails[0] if emails else None

    def search_emails(self, query: str, count: int = 10) -> list[dict]:
        """Search emails by subject, body, or sender using Graph $search."""
        token = self.authenticate()
        params = {
            "$top": count,
            "$search": f'"{query}"',
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,body",
        }
        data = self._get("/me/messages", token, params)
        return [self._parse_email(m) for m in data.get("value", [])]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, token: str, params: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        resp = requests.get(f"{_GRAPH_BASE}{path}", headers=headers, params=params, timeout=15)
        if not resp.ok:
            raise RuntimeError(
                f"Graph API error {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()

    def _parse_email(self, msg: dict) -> dict:
        """Normalize a Graph API message object into a clean dict."""
        sender = msg.get("from", {})
        sender_addr = sender.get("emailAddress", {})
        body_preview = msg.get("bodyPreview", "")
        return {
            "id": msg.get("id", ""),
            "subject": msg.get("subject", "(no subject)"),
            "from_name": sender_addr.get("name", ""),
            "from_email": sender_addr.get("address", ""),
            "received": msg.get("receivedDateTime", ""),
            "is_read": msg.get("isRead", True),
            "preview": body_preview[:500],
        }
