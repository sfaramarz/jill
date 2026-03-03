"""Jill MCP Server — exposes Jira, Confluence, and Obsidian as Claude tools."""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Ensure the jill package directory is on the path when invoked from anywhere
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
from config import load_config, ConfigError
from connectors.jira import JiraConnector
from connectors.confluence import ConfluenceConnector
from connectors.obsidian import ObsidianConnector

# ---------------------------------------------------------------------------
# Startup — load config and initialise connectors
# ---------------------------------------------------------------------------

try:
    config = load_config()
except ConfigError as e:
    print(f"Jill config error: {e}", file=sys.stderr)
    sys.exit(1)

jira: JiraConnector | None = None
confluence: ConfluenceConnector | None = None
obsidian: ObsidianConnector | None = None

if config.jira_enabled:
    jira = JiraConnector(
        base_url=config.jira_base_url,
        api_token=config.jira_api_token,
        username=config.jira_username,
    )

if config.confluence_enabled:
    confluence = ConfluenceConnector(
        base_url=config.confluence_base_url,
        api_token=config.confluence_api_token,
        username=config.confluence_username,
    )

if config.obsidian_enabled:
    try:
        obsidian = ObsidianConnector(config.obsidian_vault_path)
    except ValueError as e:
        print(f"Warning: {e}", file=sys.stderr)

mcp = FastMCP(
    "Jill",
    instructions=(
        "Jill is a personal work assistant with access to Jira, Confluence, and Obsidian. "
        "Use these tools to answer questions about the user's tickets, documentation, and notes. "
        "Always cite sources: include Jira issue keys and URLs, Confluence page titles and URLs, "
        "and Obsidian note titles and paths."
    ),
)

# ---------------------------------------------------------------------------
# Jira tools
# ---------------------------------------------------------------------------

@mcp.tool()
def jira_my_issues() -> str:
    """Get all open Jira issues currently assigned to you."""
    if not jira:
        return "Jira is not configured. Set JIRA_BASE_URL, JIRA_USERNAME, and JIRA_API_TOKEN in .env"
    try:
        issues = jira.get_assigned_issues()
        return _format_jira_issues(issues, "Your Open Jira Issues")
    except Exception as e:
        return f"Jira error: {e}"


@mcp.tool()
def jira_sprint_issues() -> str:
    """Get Jira issues in your current active sprint."""
    if not jira:
        return "Jira is not configured."
    try:
        issues = jira.get_sprint_issues()
        return _format_jira_issues(issues, "Current Sprint Issues")
    except Exception as e:
        return f"Jira error: {e}"


@mcp.tool()
def jira_search(query: str) -> str:
    """Search Jira issues by keyword or phrase.

    Args:
        query: The search term — can be a keyword, ticket topic, or phrase.
    """
    if not jira:
        return "Jira is not configured."
    try:
        issues = jira.search_issues(query)
        return _format_jira_issues(issues, f"Jira results for '{query}'")
    except Exception as e:
        return f"Jira error: {e}"


@mcp.tool()
def jira_recent_activity() -> str:
    """Get recently updated Jira issues you were assigned to or reported."""
    if not jira:
        return "Jira is not configured."
    try:
        issues = jira.get_recent_activity()
        return _format_jira_issues(issues, "Recent Jira Activity")
    except Exception as e:
        return f"Jira error: {e}"


# ---------------------------------------------------------------------------
# Confluence tools
# ---------------------------------------------------------------------------

@mcp.tool()
def confluence_recent_pages() -> str:
    """Get recently modified Confluence pages."""
    if not confluence:
        return "Confluence is not configured. Set CONFLUENCE_BASE_URL, CONFLUENCE_USERNAME, and CONFLUENCE_API_TOKEN in .env"
    try:
        pages = confluence.get_recent_pages(limit=15)
        return _format_confluence_pages(pages, "Recent Confluence Pages")
    except Exception as e:
        return f"Confluence error: {e}"


@mcp.tool()
def confluence_search(query: str) -> str:
    """Search Confluence pages by keyword or phrase.

    Args:
        query: The search term to look up across all Confluence spaces you have access to.
    """
    if not confluence:
        return "Confluence is not configured."
    try:
        pages = confluence.search(query)
        return _format_confluence_pages(pages, f"Confluence results for '{query}'")
    except Exception as e:
        return f"Confluence error: {e}"


# ---------------------------------------------------------------------------
# Obsidian tools
# ---------------------------------------------------------------------------

@mcp.tool()
def obsidian_recent_notes() -> str:
    """Get your most recently modified Obsidian notes."""
    if not obsidian:
        return "Obsidian is not configured. Set OBSIDIAN_VAULT_PATH in .env"
    try:
        notes = obsidian.get_recent_notes(limit=15)
        return _format_obsidian_notes(notes, "Recent Obsidian Notes")
    except Exception as e:
        return f"Obsidian error: {e}"


@mcp.tool()
def obsidian_search(query: str) -> str:
    """Search your Obsidian vault by keyword — searches both note titles and content.

    Args:
        query: The search term to look up across all notes in your vault.
    """
    if not obsidian:
        return "Obsidian is not configured."
    try:
        notes = obsidian.search(query, limit=20)
        return _format_obsidian_notes(notes, f"Obsidian results for '{query}'")
    except Exception as e:
        return f"Obsidian error: {e}"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_jira_issues(issues: list[dict], label: str) -> str:
    if not issues:
        return f"{label}: No issues found."
    lines = [f"{label} ({len(issues)} issues)\n{'─' * 40}"]
    for issue in issues:
        desc = issue["description"]
        if len(desc) > 200:
            desc = desc[:200] + "..."
        lines.append(
            f"\n[{issue['key']}] {issue['summary']}\n"
            f"  Status: {issue['status']}  |  Priority: {issue['priority']}  |  Type: {issue['issue_type']}\n"
            f"  Project: {issue['project']}  |  Updated: {issue['updated'][:10] if issue['updated'] else 'N/A'}\n"
            f"  URL: {issue['url']}"
            + (f"\n  Description: {desc}" if desc else "")
        )
    return "\n".join(lines)


def _format_confluence_pages(pages: list[dict], label: str) -> str:
    if not pages:
        return f"{label}: No pages found."
    lines = [f"{label} ({len(pages)} pages)\n{'─' * 40}"]
    for page in pages:
        preview = page["content"]
        if len(preview) > 300:
            preview = preview[:300] + "..."
        lines.append(
            f"\n{page['title']} (Space: {page['space']})\n"
            f"  Last modified: {page['last_modified'][:10] if page['last_modified'] else 'N/A'}"
            + (f" by {page['last_modified_by']}" if page["last_modified_by"] else "")
            + f"\n  URL: {page['url']}"
            + (f"\n  Preview: {preview}" if preview else "")
        )
    return "\n".join(lines)


def _format_obsidian_notes(notes: list[dict], label: str) -> str:
    if not notes:
        return f"{label}: No notes found."
    lines = [f"{label} ({len(notes)} notes)\n{'─' * 40}"]
    for note in notes:
        preview = note["content"]
        if len(preview) > 300:
            preview = preview[:300] + "..."
        tags = ", ".join(note["tags"][:5]) if note["tags"] else "none"
        lines.append(
            f"\n{note['title']}\n"
            f"  Path: {note['path']}\n"
            f"  Tags: {tags}"
            + (f"\n  Preview: {preview}" if preview else "")
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
