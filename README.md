# Jill — Personal AI Assistant

Jill is a personal AI assistant I built for myself as a TPM/Producer at NVIDIA. It connects to all the tools I use daily — Jira, Confluence, Obsidian, GitHub, GitLab, and Slack — and lets me ask questions, generate briefings, search across everything, and produce TPM documents, all from a single CLI.

---

## Why I Built This

As a TPM I constantly context-switch between Jira tickets, Confluence docs, meeting notes, pull requests, and Slack threads. I wanted one tool that could pull all of that together and let me ask natural language questions like *"What are my open blockers this sprint?"* or *"Create a roadmap planning agenda for FrameView"* — without having to open six tabs.

---

## How It Works

### The Stack

- **[Claude](https://www.anthropic.com/claude) (claude-sonnet-4-6)** — the brain. Every query goes to Claude with full context from all your data sources injected into the prompt. Responses stream to the terminal in real time.
- **[Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)** — used directly for streaming Claude API calls.
- **[Click](https://click.palletsprojects.com/)** — powers the CLI interface.
- **[Requests](https://requests.readthedocs.io/)** — used by each connector to call REST APIs.
- **[slack-sdk](https://slack.dev/python-slack-sdk/)** — Slack Web API connector.
- **[python-dotenv](https://github.com/theskumar/python-dotenv)** — loads credentials from a local `.env` file.
- **[MCP (Model Context Protocol)](https://modelcontextprotocol.io/)** — `server.py` exposes Jira, Confluence, and Obsidian as MCP tools so Jill can also run as a tool server inside Claude Desktop.

### Architecture

```
main.py          ← CLI entry point (Click commands)
assistant.py     ← Orchestrator: gathers context, calls Claude, streams output
config.py        ← Loads and validates .env, enables/disables connectors
connectors/
  jira.py        ← Jira Server/DC REST API v2
  confluence.py  ← Confluence REST API
  obsidian.py    ← Local vault file system reader
  github.py      ← GitHub REST API v3
  gitlab.py      ← GitLab REST API v4
  slack.py       ← Slack Web API
server.py        ← MCP server (Claude Desktop integration)
```

### How a Query Works

1. You run a CLI command (e.g. `python main.py ask "what are my blockers?"`)
2. `assistant.py` calls each enabled connector in parallel to fetch relevant data
3. All results are formatted and injected into a single prompt as context
4. Claude receives the prompt + context and streams a response back to your terminal
5. If a connector fails or isn't configured, it's skipped with a warning — everything else still works

### Graceful Fallback

Every connector is optional. If a credential is missing or a service is unreachable, that connector is disabled with a warning at startup and the rest continue working. You can run Jill with just Obsidian configured, or just Jira — whatever you have.

---

## Connectors

| Source | What it fetches |
|--------|----------------|
| **Jira** | Assigned issues, sprint issues, recent activity, full-text search, project issues |
| **Confluence** | Recent pages, full-text search, fetch by page ID/URL |
| **Obsidian** | Local vault search by title + content, recent notes, pinned notes |
| **GitHub** | Your open PRs, PRs awaiting your review, open issues, search |
| **GitLab** | Your open MRs, MRs awaiting your review, open issues, search |
| **Slack** | Channel messages, DMs, mentions, message search (user token) |

---

## CLI Commands

```bash
# Ask any natural language question grounded in your data
python main.py ask "What are my open Jira tickets?"
python main.py ask "Any Slack messages about the RTX project?"

# Generate a daily briefing across all sources
python main.py briefing

# Cross-reference a topic across every source
python main.py search "FrameView roadmap"

# Generate and save a weekly status report to Obsidian
python main.py weekly-report

# Generate a TPM document (POR, SRD, roadmap, or release checklist)
python main.py create por --project NVDRV
python main.py create srd --topic "GPU memory management"
python main.py create roadmap
python main.py create checklist --topic "RTX 5090 release"

# Populate a PLC document from a Confluence template
python main.py plc-doc \
  --template https://confluence.nvidia.com/pages/123456789 \
  --title "RTX 5090 PLC Q2 2026" \
  --space NVDRV \
  --jira-project NVDRV \
  --obsidian "RTX 5090 roadmap"
```

---

## Setup

### 1. Clone & install dependencies

```bash
git clone https://github.com/sfaramarz/jill.git
cd jill
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials. Every connector except `ANTHROPIC_API_KEY` is optional — leave blank to disable.

```env
ANTHROPIC_API_KEY=sk-ant-...

# Jira
JIRA_BASE_URL=https://jirasw.example.com
JIRA_USERNAME=your_username
JIRA_API_TOKEN=your_personal_access_token

# Confluence
CONFLUENCE_BASE_URL=https://confluence.example.com
CONFLUENCE_USERNAME=your_username
CONFLUENCE_API_TOKEN=your_personal_access_token

# Obsidian (local vault path)
OBSIDIAN_VAULT_PATH=C:\Users\you\Documents\Obsidian

# GitHub
GITHUB_TOKEN=ghp_...
GITHUB_USERNAME=your_github_username

# GitLab
GITLAB_BASE_URL=https://gitlab.example.com
GITLAB_TOKEN=glpat-...

# Slack (user token recommended for full access including search)
SLACK_TOKEN=xoxp-...
SLACK_CHANNEL_IDS=C01234ABCD,C05678EFGH   # optional
```

### 3. Run

```bash
python main.py briefing
python main.py ask "What should I focus on today?"
```

---

## MCP Server (Claude Desktop)

`server.py` runs Jill as an [MCP](https://modelcontextprotocol.io/) tool server, which lets you use it directly inside Claude Desktop. Add this to your Claude Desktop config:

```json
{
  "mcpServers": {
    "jill": {
      "command": "python",
      "args": ["C:/path/to/jill/server.py"]
    }
  }
}
```

Claude Desktop will then have access to Jira, Confluence, and Obsidian as native tools.

---

## Pinned Notes

You can pin Obsidian notes to always be included in every prompt, regardless of the query. Useful for context like your team roster, project glossary, or personal working agreements:

```env
OBSIDIAN_PINNED_NOTES=obsidian://open?vault=Obsidian&file=General%20Knowledge%2FTPM%20Resources
```

Separate multiple entries with semicolons.

---

Built with Claude by [@sfaramarz](https://github.com/sfaramarz)
