"""Jill MCP Server — exposes all work connectors as Claude tools."""

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
from connectors.github import GitHubConnector
from connectors.gitlab import GitLabConnector
from connectors.slack import SlackConnector
from connectors.outlook import OutlookConnector
from connectors.nvbugs import NVBugsConnector

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
github: GitHubConnector | None = None
gitlab: GitLabConnector | None = None
slack: SlackConnector | None = None
outlook: OutlookConnector | None = None
nvbugs: NVBugsConnector | None = None

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

if config.github_enabled:
    github = GitHubConnector(
        token=config.github_token,
        username=config.github_username,
        org=config.github_org,
    )

if config.gitlab_enabled:
    gitlab = GitLabConnector(
        base_url=config.gitlab_base_url,
        token=config.gitlab_token,
    )

if config.slack_enabled:
    slack = SlackConnector(
        token=config.slack_token,
        channel_ids=config.slack_channel_ids,
    )

if config.outlook_enabled:
    outlook = OutlookConnector(
        tenant_id=config.outlook_tenant_id,
        client_id=config.outlook_client_id,
    )

if config.nvbugs_enabled:
    nvbugs = NVBugsConnector(
        token=config.nvbugs_api_token,
        base_url=config.nvbugs_base_url,
    )

mcp = FastMCP(
    "Jill",
    instructions=(
        "Jill is a personal work assistant with access to Jira, Confluence, Obsidian, "
        "GitHub, GitLab, Slack, Outlook, and NVBugs. "
        "Use these tools to answer questions about the user's tickets, documentation, notes, "
        "code reviews, messages, emails, and bugs. "
        "Always cite sources with URLs, issue keys, or note paths when available."
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
# GitHub tools
# ---------------------------------------------------------------------------

@mcp.tool()
def github_my_prs() -> str:
    """Get open GitHub pull requests authored by you."""
    if not github:
        return "GitHub is not configured. Set GITHUB_TOKEN and GITHUB_USERNAME in .env"
    try:
        prs = github.get_my_prs()
        return _format_github_items(prs, "Your Open GitHub PRs")
    except Exception as e:
        return f"GitHub error: {e}"


@mcp.tool()
def github_review_requests() -> str:
    """Get open GitHub PRs where you are a requested reviewer."""
    if not github:
        return "GitHub is not configured."
    try:
        prs = github.get_review_requests()
        return _format_github_items(prs, "GitHub PRs Awaiting Your Review")
    except Exception as e:
        return f"GitHub error: {e}"


@mcp.tool()
def github_my_issues() -> str:
    """Get open GitHub issues assigned to you."""
    if not github:
        return "GitHub is not configured."
    try:
        issues = github.get_my_issues()
        return _format_github_items(issues, "Your Open GitHub Issues")
    except Exception as e:
        return f"GitHub error: {e}"


@mcp.tool()
def github_search(query: str) -> str:
    """Search GitHub issues and pull requests by keyword.

    Args:
        query: Search term or phrase to find across issues and PRs.
    """
    if not github:
        return "GitHub is not configured."
    try:
        items = github.search(query)
        return _format_github_items(items, f"GitHub results for '{query}'")
    except Exception as e:
        return f"GitHub error: {e}"


@mcp.tool()
def github_recent_commits(repo: str, branch: str = "main") -> str:
    """Get recent commits for a GitHub repository.

    Args:
        repo:   Full repo name like ``owner/repo`` or just ``repo`` if org is configured.
        branch: Branch to fetch commits from (default: main).
    """
    if not github:
        return "GitHub is not configured."
    try:
        commits = github.get_recent_commits(repo, branch=branch)
        return _format_github_commits(commits, f"Recent commits on {repo}/{branch}")
    except Exception as e:
        return f"GitHub error: {e}"


# ---------------------------------------------------------------------------
# GitLab tools
# ---------------------------------------------------------------------------

@mcp.tool()
def gitlab_my_mrs() -> str:
    """Get open GitLab merge requests authored by you."""
    if not gitlab:
        return "GitLab is not configured. Set GITLAB_BASE_URL and GITLAB_TOKEN in .env"
    try:
        mrs = gitlab.get_my_mrs()
        return _format_gitlab_items(mrs, "Your Open GitLab MRs")
    except Exception as e:
        return f"GitLab error: {e}"


@mcp.tool()
def gitlab_review_mrs() -> str:
    """Get open GitLab merge requests assigned to you for review."""
    if not gitlab:
        return "GitLab is not configured."
    try:
        mrs = gitlab.get_review_mrs()
        return _format_gitlab_items(mrs, "GitLab MRs Awaiting Your Review")
    except Exception as e:
        return f"GitLab error: {e}"


@mcp.tool()
def gitlab_my_issues() -> str:
    """Get open GitLab issues assigned to you."""
    if not gitlab:
        return "GitLab is not configured."
    try:
        issues = gitlab.get_my_issues()
        return _format_gitlab_items(issues, "Your Open GitLab Issues")
    except Exception as e:
        return f"GitLab error: {e}"


@mcp.tool()
def gitlab_search(query: str) -> str:
    """Search GitLab issues and merge requests by keyword.

    Args:
        query: Search term to find across issues and MRs.
    """
    if not gitlab:
        return "GitLab is not configured."
    try:
        items = gitlab.search(query)
        return _format_gitlab_items(items, f"GitLab results for '{query}'")
    except Exception as e:
        return f"GitLab error: {e}"


# ---------------------------------------------------------------------------
# Slack tools
# ---------------------------------------------------------------------------

@mcp.tool()
def slack_recent_messages() -> str:
    """Get recent Slack messages from your configured channels."""
    if not slack:
        return "Slack is not configured. Set SLACK_TOKEN in .env"
    try:
        messages = slack.get_recent_messages_across_channels()
        return _format_slack_messages(messages, "Recent Slack Messages")
    except Exception as e:
        return f"Slack error: {e}"


@mcp.tool()
def slack_search(query: str) -> str:
    """Search Slack messages by keyword (requires user token with search:read scope).

    Args:
        query: The search term to look up across all Slack messages.
    """
    if not slack:
        return "Slack is not configured."
    try:
        messages = slack.search_messages(query)
        return _format_slack_messages(messages, f"Slack results for '{query}'")
    except Exception as e:
        return f"Slack error: {e}"


@mcp.tool()
def slack_mentions() -> str:
    """Get recent Slack messages that mention you (requires user token)."""
    if not slack:
        return "Slack is not configured."
    try:
        messages = slack.get_mentions()
        return _format_slack_messages(messages, "Recent Slack Mentions")
    except Exception as e:
        return f"Slack error: {e}"


@mcp.tool()
def slack_channel_messages(channel_id: str) -> str:
    """Get recent messages from a specific Slack channel or DM.

    Args:
        channel_id: The Slack channel ID (e.g. C01234ABCDE).
    """
    if not slack:
        return "Slack is not configured."
    try:
        messages = slack.get_channel_messages(channel_id)
        return _format_slack_messages(messages, f"Messages from channel {channel_id}")
    except Exception as e:
        return f"Slack error: {e}"


# ---------------------------------------------------------------------------
# Outlook tools
# ---------------------------------------------------------------------------

@mcp.tool()
def outlook_recent_emails() -> str:
    """Get your most recent Outlook emails."""
    if not outlook:
        return "Outlook is not configured. Set OUTLOOK_TENANT_ID and OUTLOOK_CLIENT_ID in .env"
    try:
        emails = outlook.get_recent_emails(count=15)
        return _format_emails(emails, "Recent Outlook Emails")
    except Exception as e:
        return f"Outlook error: {e}"


@mcp.tool()
def outlook_unread_emails() -> str:
    """Get your unread Outlook emails."""
    if not outlook:
        return "Outlook is not configured."
    try:
        emails = outlook.get_unread_emails(count=15)
        return _format_emails(emails, "Unread Outlook Emails")
    except Exception as e:
        return f"Outlook error: {e}"


@mcp.tool()
def outlook_search_emails(query: str) -> str:
    """Search Outlook emails by subject, body, or sender.

    Args:
        query: The search term to look up across your mailbox.
    """
    if not outlook:
        return "Outlook is not configured."
    try:
        emails = outlook.search_emails(query)
        return _format_emails(emails, f"Outlook results for '{query}'")
    except Exception as e:
        return f"Outlook error: {e}"


# ---------------------------------------------------------------------------
# NVBugs tools
# ---------------------------------------------------------------------------

@mcp.tool()
def nvbugs_get_bug(bug_id: int) -> str:
    """Get full details for a single NVBug by ID.

    Args:
        bug_id: The numeric NVBug ID.
    """
    if not nvbugs:
        return "NVBugs is not configured. Set NVBUGS_API_TOKEN in .env"
    try:
        bug = nvbugs.get_bug(bug_id)
        return _format_bugs([bug], f"NVBug {bug_id}")
    except Exception as e:
        return f"NVBugs error: {e}"


@mcp.tool()
def nvbugs_my_bugs(username: str) -> str:
    """Get open NVBugs assigned to a user.

    Args:
        username: The NVIDIA username to look up (e.g. sfaramarz).
    """
    if not nvbugs:
        return "NVBugs is not configured."
    try:
        bugs = nvbugs.get_assigned_bugs(username)
        return _format_bugs(bugs, f"Open NVBugs assigned to {username}")
    except Exception as e:
        return f"NVBugs error: {e}"


@mcp.tool()
def nvbugs_search_module(module: str) -> str:
    """Search NVBugs by component or module name.

    Args:
        module: The module/component name to search for (e.g. NVDRV, Display).
    """
    if not nvbugs:
        return "NVBugs is not configured."
    try:
        bugs = nvbugs.search_by_module(module)
        return _format_bugs(bugs, f"NVBugs for module '{module}'")
    except Exception as e:
        return f"NVBugs error: {e}"


@mcp.tool()
def nvbugs_search_keyword(keyword: str) -> str:
    """Search NVBugs by keyword in the synopsis/title.

    Args:
        keyword: The keyword or phrase to search for.
    """
    if not nvbugs:
        return "NVBugs is not configured."
    try:
        bugs = nvbugs.search_by_keyword(keyword)
        return _format_bugs(bugs, f"NVBugs matching '{keyword}'")
    except Exception as e:
        return f"NVBugs error: {e}"


@mcp.tool()
def nvbugs_add_comment(bug_id: int, comment: str) -> str:
    """Add a comment to an NVBug.

    Args:
        bug_id:  The numeric NVBug ID.
        comment: The comment text to add.
    """
    if not nvbugs:
        return "NVBugs is not configured."
    try:
        result = nvbugs.add_comment(bug_id, comment)
        return f"Comment added to NVBug {bug_id}. Response: {result}"
    except Exception as e:
        return f"NVBugs error: {e}"


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


def _format_github_items(items: list[dict], label: str) -> str:
    if not items:
        return f"{label}: Nothing found."
    lines = [f"{label} ({len(items)} items)\n{'─' * 40}"]
    for item in items:
        labels = ", ".join(item["labels"]) if item["labels"] else ""
        lines.append(
            f"\n[{item['kind']} #{item['number']}] {item['title']}\n"
            f"  Repo: {item['repo']}  |  State: {item['state']}"
            + (f"  |  Labels: {labels}" if labels else "")
            + f"\n  Updated: {item['updated_at'][:10] if item['updated_at'] else 'N/A'}\n"
            f"  URL: {item['url']}"
            + (f"\n  Preview: {item['body_preview']}" if item["body_preview"] else "")
        )
    return "\n".join(lines)


def _format_github_commits(commits: list[dict], label: str) -> str:
    if not commits:
        return f"{label}: No commits found."
    lines = [f"{label} ({len(commits)} commits)\n{'─' * 40}"]
    for c in commits:
        lines.append(
            f"\n[{c['sha']}] {c['message']}\n"
            f"  Author: {c['author']}  |  Date: {c['date'][:10] if c['date'] else 'N/A'}\n"
            f"  URL: {c['url']}"
        )
    return "\n".join(lines)


def _format_gitlab_items(items: list[dict], label: str) -> str:
    if not items:
        return f"{label}: Nothing found."
    lines = [f"{label} ({len(items)} items)\n{'─' * 40}"]
    for item in items:
        extra = ""
        if item["kind"] == "MR":
            extra = f"  Branch: {item.get('source_branch', '')} → {item.get('target_branch', '')}\n"
        else:
            labels = ", ".join(item.get("labels", []))
            extra = (f"  Labels: {labels}\n" if labels else "")
        lines.append(
            f"\n[{item['kind']} !{item['iid']}] {item['title']}\n"
            f"  Project: {item['project']}  |  State: {item['state']}\n"
            + extra
            + f"  Updated: {item['updated_at'][:10] if item['updated_at'] else 'N/A'}\n"
            f"  URL: {item['url']}"
            + (f"\n  Preview: {item.get('description_preview', '')}" if item.get("description_preview") else "")
        )
    return "\n".join(lines)


def _format_slack_messages(messages: list[dict], label: str) -> str:
    if not messages:
        return f"{label}: No messages found."
    lines = [f"{label} ({len(messages)} messages)\n{'─' * 40}"]
    for msg in messages:
        channel = msg.get("channel_name") or msg.get("channel_id", "")
        permalink = msg.get("permalink", "")
        lines.append(
            f"\n[{msg['timestamp']}] {msg.get('user', 'unknown')}"
            + (f" in #{channel}" if channel else "")
            + f"\n  {msg['text'][:400]}"
            + (f"\n  Link: {permalink}" if permalink else "")
        )
    return "\n".join(lines)


def _format_emails(emails: list[dict], label: str) -> str:
    if not emails:
        return f"{label}: No emails found."
    lines = [f"{label} ({len(emails)} emails)\n{'─' * 40}"]
    for email in emails:
        read_flag = "" if email["is_read"] else " [UNREAD]"
        lines.append(
            f"\n{email['received'][:16]}{read_flag} — {email['subject']}\n"
            f"  From: {email['from_name']} <{email['from_email']}>"
            + (f"\n  Preview: {email['preview'][:300]}" if email["preview"] else "")
        )
    return "\n".join(lines)


def _format_bugs(bugs: list[dict], label: str) -> str:
    if not bugs:
        return f"{label}: No bugs found."
    lines = [f"{label} ({len(bugs)} bugs)\n{'─' * 40}"]
    for bug in bugs:
        if not bug:
            continue
        lines.append(
            f"\n[Bug {bug['id']}] {bug['synopsis']}\n"
            f"  Status: {bug['status']}  |  Priority: {bug['priority']}  |  Severity: {bug['severity']}\n"
            f"  Module: {bug['module']}  |  Assigned: {bug['assigned_to']}  |  Days open: {bug['days_open']}\n"
            f"  URL: {bug['url']}"
            + (f"\n  Keywords: {bug['keywords']}" if bug["keywords"] else "")
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
