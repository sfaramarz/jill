"""Slack Web API connector.

Supports both:
- User token (xoxp-...): full access including search.messages and DMs  [preferred]
- Bot token (xoxb-...):  channel history only (bot must be in the channel)

Required OAuth scopes for user token: channels:history, channels:read,
groups:history, groups:read, im:history, im:read, mpim:history, mpim:read,
search:read, users:read
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class SlackConnector:
    """Fetches messages, DMs, and search results from Slack via Web API."""

    def __init__(self, token: str, channel_ids: list[str] | None = None):
        """
        Args:
            token:       User token (xoxp-) or bot token (xoxb-).
            channel_ids: Optional list of channel IDs to scope briefing context.
                         If empty the connector will fall back to listing joined
                         channels and picking the most recent ones.
        """
        self._client = WebClient(token=token)
        self.channel_ids: list[str] = channel_ids or []
        self._is_user_token = token.startswith("xoxp-")

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get_current_user(self) -> dict:
        """Return the authenticated user's Slack identity."""
        if self._is_user_token:
            resp = self._client.auth_test()
            return {
                "user_id": resp.get("user_id", ""),
                "user": resp.get("user", ""),
                "team": resp.get("team", ""),
            }
        resp = self._client.auth_test()
        return {
            "user_id": resp.get("bot_id", ""),
            "user": resp.get("user", ""),
            "team": resp.get("team", ""),
        }

    def get_channel_messages(
        self, channel_id: str, limit: int = 20
    ) -> list[dict]:
        """Return recent messages from a channel or DM thread."""
        try:
            resp = self._client.conversations_history(
                channel=channel_id,
                limit=limit,
            )
        except SlackApiError as e:
            raise RuntimeError(
                f"Could not fetch messages from channel {channel_id}: {e.response['error']}"
            ) from e
        return self._format_messages(resp.get("messages", []), channel_id=channel_id)

    def search_messages(self, query: str, count: int = 20) -> list[dict]:
        """Full-text search across Slack (requires user token with search:read scope)."""
        if not self._is_user_token:
            raise RuntimeError(
                "search.messages requires a user token (xoxp-). "
                "Set SLACK_TOKEN to a user token to enable search."
            )
        try:
            resp = self._client.search_messages(query=query, count=count, sort="timestamp")
        except SlackApiError as e:
            raise RuntimeError(
                f"Slack search failed: {e.response['error']}"
            ) from e
        matches = resp.get("messages", {}).get("matches", [])
        return self._format_search_results(matches)

    def get_mentions(self, count: int = 20) -> list[dict]:
        """Return recent messages that mention the authenticated user.

        Requires a user token; falls back gracefully if unavailable.
        """
        if not self._is_user_token:
            raise RuntimeError(
                "get_mentions requires a user token (xoxp-) with search:read scope."
            )
        try:
            resp = self._client.search_messages(
                query="to:me", count=count, sort="timestamp"
            )
        except SlackApiError as e:
            raise RuntimeError(
                f"Slack mention search failed: {e.response['error']}"
            ) from e
        matches = resp.get("messages", {}).get("matches", [])
        return self._format_search_results(matches)

    def list_channels(self, limit: int = 200) -> list[dict]:
        """Return public and private channels the token has access to."""
        try:
            resp = self._client.conversations_list(
                limit=limit,
                types="public_channel,private_channel,im,mpim",
                exclude_archived=True,
            )
        except SlackApiError as e:
            raise RuntimeError(
                f"Could not list channels: {e.response['error']}"
            ) from e
        channels = []
        for ch in resp.get("channels", []):
            channels.append({
                "id": ch.get("id", ""),
                "name": ch.get("name", ch.get("id", "")),
                "is_im": ch.get("is_im", False),
                "is_mpim": ch.get("is_mpim", False),
                "is_private": ch.get("is_private", False),
            })
        return channels

    def get_recent_messages_across_channels(
        self, limit_per_channel: int = 10, max_channels: int = 5
    ) -> list[dict]:
        """Fetch recent messages from configured channels (or top joined channels)."""
        channel_ids = self.channel_ids
        if not channel_ids:
            try:
                channels = self.list_channels(limit=max_channels)
                channel_ids = [ch["id"] for ch in channels[:max_channels]]
            except RuntimeError:
                return []

        messages: list[dict] = []
        for cid in channel_ids[:max_channels]:
            try:
                msgs = self.get_channel_messages(cid, limit=limit_per_channel)
                messages.extend(msgs)
            except RuntimeError:
                continue
        return messages

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_messages(self, raw: list[dict], channel_id: str = "") -> list[dict]:
        """Flatten Slack message objects into clean dicts for LLM context."""
        result = []
        for msg in raw:
            # Skip bot messages and join/leave notices
            if msg.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
                continue
            ts = msg.get("ts", "")
            dt_str = self._ts_to_iso(ts)
            text = msg.get("text", "")
            result.append({
                "channel_id": channel_id,
                "user": msg.get("user", msg.get("username", "unknown")),
                "text": text[:800],
                "timestamp": dt_str,
                "thread_ts": msg.get("thread_ts"),
                "reply_count": msg.get("reply_count", 0),
            })
        return result

    def _format_search_results(self, matches: list[dict]) -> list[dict]:
        """Flatten Slack search result objects into clean dicts for LLM context."""
        result = []
        for m in matches:
            channel = m.get("channel", {})
            ts = m.get("ts", "")
            dt_str = self._ts_to_iso(ts)
            result.append({
                "channel_id": channel.get("id", ""),
                "channel_name": channel.get("name", ""),
                "user": m.get("username", ""),
                "text": (m.get("text") or "")[:800],
                "timestamp": dt_str,
                "permalink": m.get("permalink", ""),
            })
        return result

    @staticmethod
    def _ts_to_iso(ts: str) -> str:
        """Convert a Slack timestamp string (e.g. '1707123456.789') to ISO-8601."""
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
        except (ValueError, TypeError):
            return ts
