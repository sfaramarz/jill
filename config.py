"""Configuration loader — reads and validates environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass
class Config:
    anthropic_api_key: str
    jira_base_url: str
    jira_username: str       # LDAP/AD username (used for Basic Auth fallback)
    jira_api_token: str      # PAT preferred; or password for Basic Auth
    confluence_base_url: str
    confluence_username: str
    confluence_api_token: str
    obsidian_vault_path: str

    # GitHub
    github_token: str = ""
    github_username: str = ""
    github_org: str = ""

    # GitLab
    gitlab_base_url: str = ""
    gitlab_token: str = ""

    # Slack
    slack_token: str = ""
    slack_channel_ids: list = field(default_factory=list)

    # Pinned Obsidian notes — always injected into every context build.
    # Each entry is either a relative vault path or an obsidian:// URL.
    obsidian_pinned_notes: list = field(default_factory=list)

    # Outlook / Microsoft 365
    outlook_tenant_id: str = ""
    outlook_client_id: str = ""

    # NVBugs
    nvbugs_api_token: str = ""
    nvbugs_base_url: str = "https://prod.api.nvidia.com/int/nvbugs"

    # Derived flags for graceful fallback
    jira_enabled: bool = True
    confluence_enabled: bool = True
    obsidian_enabled: bool = True
    github_enabled: bool = False
    gitlab_enabled: bool = False
    slack_enabled: bool = False
    outlook_enabled: bool = False
    nvbugs_enabled: bool = False


def load_config() -> Config:
    """Load configuration from .env file and environment variables.

    Raises ConfigError if ANTHROPIC_API_KEY is missing.
    Connectors with incomplete config are disabled with a warning rather than
    raising an error, allowing the assistant to still run with available sources.
    """
    load_dotenv()

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")

    # Jira config — Server/DC uses username + PAT or just PAT (Bearer)
    jira_url = os.getenv("JIRA_BASE_URL", "").strip()
    jira_username = os.getenv("JIRA_USERNAME", "").strip()
    jira_token = os.getenv("JIRA_API_TOKEN", "").strip()
    jira_enabled = bool(jira_url and jira_token)
    if not jira_enabled:
        _warn_missing("Jira", ["JIRA_BASE_URL", "JIRA_API_TOKEN"], {
            "JIRA_BASE_URL": jira_url,
            "JIRA_API_TOKEN": jira_token,
        })

    # Confluence config
    conf_url = os.getenv("CONFLUENCE_BASE_URL", "").strip()
    conf_username = os.getenv("CONFLUENCE_USERNAME", "").strip()
    conf_token = os.getenv("CONFLUENCE_API_TOKEN", "").strip()
    confluence_enabled = bool(conf_url and conf_token)
    if not confluence_enabled:
        _warn_missing("Confluence", ["CONFLUENCE_BASE_URL", "CONFLUENCE_API_TOKEN"], {
            "CONFLUENCE_BASE_URL": conf_url,
            "CONFLUENCE_API_TOKEN": conf_token,
        })

    # Obsidian config
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    obsidian_enabled = bool(vault_path)
    if not obsidian_enabled:
        print("Warning: OBSIDIAN_VAULT_PATH not set — Obsidian connector disabled.")

    pinned_raw = os.getenv("OBSIDIAN_PINNED_NOTES", "").strip()
    obsidian_pinned_notes = [p.strip() for p in pinned_raw.split(";") if p.strip()]

    # GitHub config
    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    github_username = os.getenv("GITHUB_USERNAME", "").strip()
    github_org = os.getenv("GITHUB_ORG", "").strip()
    github_enabled = bool(github_token and github_username)
    if not github_enabled:
        _warn_missing("GitHub", ["GITHUB_TOKEN", "GITHUB_USERNAME"], {
            "GITHUB_TOKEN": github_token,
            "GITHUB_USERNAME": github_username,
        })

    # GitLab config
    gitlab_base_url = os.getenv("GITLAB_BASE_URL", "").strip()
    gitlab_token = os.getenv("GITLAB_TOKEN", "").strip()
    gitlab_enabled = bool(gitlab_base_url and gitlab_token)
    if not gitlab_enabled:
        _warn_missing("GitLab", ["GITLAB_BASE_URL", "GITLAB_TOKEN"], {
            "GITLAB_BASE_URL": gitlab_base_url,
            "GITLAB_TOKEN": gitlab_token,
        })

    # Slack config
    slack_token = os.getenv("SLACK_TOKEN", "").strip()
    slack_enabled = bool(slack_token)
    if not slack_enabled:
        _warn_missing("Slack", ["SLACK_TOKEN"], {"SLACK_TOKEN": slack_token})
    slack_channel_raw = os.getenv("SLACK_CHANNEL_IDS", "").strip()
    slack_channel_ids = [c.strip() for c in slack_channel_raw.split(",") if c.strip()]

    # Outlook / Microsoft 365
    outlook_tenant_id = os.getenv("OUTLOOK_TENANT_ID", "").strip()
    outlook_client_id = os.getenv("OUTLOOK_CLIENT_ID", "").strip()
    outlook_enabled = bool(outlook_tenant_id and outlook_client_id)
    if not outlook_enabled:
        _warn_missing("Outlook", ["OUTLOOK_TENANT_ID", "OUTLOOK_CLIENT_ID"], {
            "OUTLOOK_TENANT_ID": outlook_tenant_id,
            "OUTLOOK_CLIENT_ID": outlook_client_id,
        })

    # NVBugs
    nvbugs_api_token = os.getenv("NVBUGS_API_TOKEN", "").strip()
    nvbugs_base_url = os.getenv("NVBUGS_API_URL", "https://prod.api.nvidia.com/int/nvbugs").strip()
    nvbugs_enabled = bool(nvbugs_api_token)
    if not nvbugs_enabled:
        _warn_missing("NVBugs", ["NVBUGS_API_TOKEN"], {"NVBUGS_API_TOKEN": nvbugs_api_token})

    return Config(
        anthropic_api_key=api_key,
        jira_base_url=jira_url,
        jira_username=jira_username,
        jira_api_token=jira_token,
        confluence_base_url=conf_url,
        confluence_username=conf_username,
        confluence_api_token=conf_token,
        obsidian_vault_path=vault_path,
        obsidian_pinned_notes=obsidian_pinned_notes,
        github_token=github_token,
        github_username=github_username,
        github_org=github_org,
        gitlab_base_url=gitlab_base_url,
        gitlab_token=gitlab_token,
        slack_token=slack_token,
        slack_channel_ids=slack_channel_ids,
        outlook_tenant_id=outlook_tenant_id,
        outlook_client_id=outlook_client_id,
        nvbugs_api_token=nvbugs_api_token,
        nvbugs_base_url=nvbugs_base_url,
        jira_enabled=jira_enabled,
        confluence_enabled=confluence_enabled,
        obsidian_enabled=obsidian_enabled,
        github_enabled=github_enabled,
        gitlab_enabled=gitlab_enabled,
        slack_enabled=slack_enabled,
        outlook_enabled=outlook_enabled,
        nvbugs_enabled=nvbugs_enabled,
    )


def _warn_missing(source: str, required: list[str], values: dict[str, str]) -> None:
    missing = [k for k in required if not values.get(k)]
    print(f"Warning: {source} connector disabled — missing env vars: {', '.join(missing)}")
