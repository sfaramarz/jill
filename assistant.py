"""Assistant core — Claude-backed reasoning over Jira, Confluence, Obsidian, GitHub, and GitLab."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from typing import Any

import anthropic

from config import Config
from connectors.jira import JiraConnector
from connectors.confluence import ConfluenceConnector
from connectors.obsidian import ObsidianConnector
from connectors.github import GitHubConnector
from connectors.gitlab import GitLabConnector
from connectors.slack import SlackConnector
from connectors.outlook import OutlookConnector
from connectors.nvbugs import NVBugsConnector

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are Jill, a personal AI assistant for a TPM/Producer at NVIDIA. \
You have access to data from seven sources:

1. **Jira** — project management tickets, issues, sprints, and activity
2. **Confluence** — team wiki pages, documentation, and meeting notes
3. **Obsidian** — the user's personal knowledge vault (markdown notes, ideas, research)
4. **GitHub** — pull requests, review requests, and issues across repos
5. **GitLab** — merge requests, review assignments, and issues
6. **Slack** — channel messages, direct messages, and mentions
7. **Outlook** — email inbox, unread messages, and email search
8. **NVBugs** — NVIDIA internal bug tracker (bugs, components, priorities, dispositions)

You can also write back to these sources: create Jira issues/comments, transition tickets, \
create/update Confluence pages, write Obsidian notes, add NVBugs comments, and generate structured documents.

Your job is to help the user manage their TPM responsibilities by synthesizing information \
across all sources.

Guidelines:
- Be concise and direct. Bullet points are preferred over long paragraphs.
- When referencing a Jira issue, always include the issue key (e.g. PROJ-123) and its URL.
- When referencing a Confluence page, include its title and URL.
- When referencing an Obsidian note, include its title and relative path.
- When referencing a GitHub PR/issue, include the repo, number, and URL.
- When referencing a GitLab MR/issue, include the project, iid, and URL.
- When referencing a Slack message, include the channel name, user, and timestamp.
- When referencing an Outlook email, include the subject, sender, and received date.
- When referencing an NVBug, always include the bug ID, synopsis, priority, and disposition.
- If data is missing or a source returned no results, say so explicitly rather than making things up.
- Cross-reference across sources when relevant.
- Today's date context may be provided — use it when reasoning about deadlines and recency.
"""

# ---------------------------------------------------------------------------
# Document templates
# ---------------------------------------------------------------------------

_DOC_TEMPLATES: dict[str, str] = {
    "por": """\
Generate a **Plan of Record (POR)** document for the context provided. \
Include these sections:

1. **Executive Summary** — one-paragraph overview of the initiative
2. **Scope** — what is in scope and explicitly out of scope
3. **Timeline / Milestones** — key dates and deliverables in a table or list
4. **Resources** — team members, their roles, and headcount needs
5. **Dependencies** — internal and external dependencies with owners
6. **Risks** — top risks with likelihood, impact, and mitigation plans

Format in clean Markdown suitable for an Obsidian note.""",

    "srd": """\
Generate a **Software Requirements Document (SRD)** for the context provided. \
Include these sections:

1. **Overview** — purpose and background of the feature/system
2. **Stakeholders** — roles, names/teams, and their interests
3. **Functional Requirements** — numbered list of must-have behaviors
4. **Non-Functional Requirements** — performance, security, reliability, scalability
5. **Acceptance Criteria** — measurable conditions for sign-off

Format in clean Markdown suitable for an Obsidian note.""",

    "roadmap": """\
Generate a **Product/Project Roadmap** document for the context provided. \
Include these sections:

1. **Vision** — the north-star goal this roadmap serves
2. **Q1 Theme** — focus area and key deliverables
3. **Q2 Theme** — focus area and key deliverables
4. **Q3 Theme** — focus area and key deliverables
5. **Q4 Theme** — focus area and key deliverables
6. **Features by Quarter** — table mapping feature → quarter → owner → status
7. **Dependencies** — cross-team or external dependencies

Format in clean Markdown suitable for an Obsidian note.""",

    "checklist": """\
Generate a **Release Checklist** document for the context provided. \
Include these sections:

1. **Pre-release Checks** — code, tests, docs, security scan
2. **Code Freeze** — criteria and date, branch cut process
3. **QA Gates** — test coverage thresholds, test types required, sign-off owner
4. **Sign-off Owners** — table of who must approve each gate
5. **Go / No-Go Criteria** — explicit conditions that must be met before shipping

Format in clean Markdown suitable for an Obsidian note.""",
}


class Assistant:
    """Orchestrates data fetching and Claude API calls for all CLI commands."""

    def __init__(self, config: Config):
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)

        self.jira: JiraConnector | None = None
        self.confluence: ConfluenceConnector | None = None
        self.obsidian: ObsidianConnector | None = None
        self.github: GitHubConnector | None = None
        self.gitlab: GitLabConnector | None = None
        self.slack: SlackConnector | None = None
        self.outlook: OutlookConnector | None = None
        self.nvbugs: NVBugsConnector | None = None

        if config.jira_enabled:
            self.jira = JiraConnector(
                base_url=config.jira_base_url,
                api_token=config.jira_api_token,
                username=config.jira_username,
            )
        if config.confluence_enabled:
            self.confluence = ConfluenceConnector(
                base_url=config.confluence_base_url,
                api_token=config.confluence_api_token,
                username=config.confluence_username,
            )
        if config.obsidian_enabled:
            try:
                self.obsidian = ObsidianConnector(config.obsidian_vault_path)
            except ValueError as e:
                print(f"Warning: {e}")
        if config.github_enabled:
            self.github = GitHubConnector(
                token=config.github_token,
                username=config.github_username,
                org=config.github_org,
            )
        if config.gitlab_enabled:
            self.gitlab = GitLabConnector(
                base_url=config.gitlab_base_url,
                token=config.gitlab_token,
            )
        if config.slack_enabled:
            self.slack = SlackConnector(
                token=config.slack_token,
                channel_ids=config.slack_channel_ids,
            )
        if config.outlook_enabled:
            self.outlook = OutlookConnector(
                tenant_id=config.outlook_tenant_id,
                client_id=config.outlook_client_id,
            )
        if config.nvbugs_enabled:
            self.nvbugs = NVBugsConnector(
                token=config.nvbugs_api_token,
                base_url=config.nvbugs_base_url,
            )

    # -------------------------------------------------------------------------
    # Public command handlers
    # -------------------------------------------------------------------------

    def ask(self, question: str) -> None:
        """Answer a natural language question using context from all sources."""
        context = self._gather_context_for_question(question)
        prompt = f"User question: {question}\n\n{context}"
        self._stream_response(prompt)

    def daily_briefing(self) -> None:
        """Generate a structured daily briefing."""
        context = self._gather_briefing_context()
        prompt = (
            "Generate a structured daily briefing for the user. Include:\n"
            "1. **Open Jira Tickets** — summarize status and priorities\n"
            "2. **Recent Confluence Updates** — highlight notable page changes\n"
            "3. **Obsidian Notes** — surface any recently modified notes or relevant context\n"
            "4. **GitHub** — open PRs you authored and PRs awaiting your review\n"
            "5. **GitLab** — open MRs you authored and MRs awaiting your review\n"
            "6. **Slack** — recent mentions and important channel messages\n"
            "7. **Outlook Emails** — unread email count and most important messages\n"
            "8. **Key Action Items** — what should the user focus on today?\n\n"
            f"{context}"
        )
        self._stream_response(prompt)

    def search(self, topic: str) -> None:
        """Cross-reference a topic across all sources."""
        context = self._gather_search_context(topic)
        prompt = (
            f"The user wants to cross-reference everything related to: **{topic}**\n\n"
            "Synthesize findings from Jira, Confluence, Obsidian, GitHub, GitLab, "
            "Slack, and Outlook into a unified summary. Group results by source, then "
            "highlight any connections or overlaps between sources.\n\n"
            f"{context}"
        )
        self._stream_response(prompt)

    def emails(self, unread_only: bool = False, search_query: str = "") -> None:
        """Display recent or unread emails, or search emails."""
        if not self.outlook:
            print("Error: Outlook is not configured. Set OUTLOOK_TENANT_ID and OUTLOOK_CLIENT_ID in .env.")
            return
        try:
            if search_query:
                print(f"Searching emails for: {search_query}\n")
                emails = self.outlook.search_emails(search_query, count=10)
                label = f"Emails matching '{search_query}'"
            elif unread_only:
                print("Fetching unread emails...\n")
                emails = self.outlook.get_unread_emails(count=10)
                label = "Unread Emails"
            else:
                print("Fetching recent emails...\n")
                emails = self.outlook.get_recent_emails(count=10)
                label = "Recent Emails"
            print(self._format_emails(emails, label=label))
        except Exception as e:
            print(f"Error fetching emails: {e}")

    def bugs(
        self,
        module: str = "",
        assigned_to: str = "",
        bug_id: int = 0,
        keyword: str = "",
        days_open: int = 0,
    ) -> None:
        """Fetch and display NVBugs filtered by various criteria."""
        if not self.nvbugs:
            print("Error: NVBugs is not configured. Set NVBUGS_API_TOKEN in .env.")
            return
        try:
            if bug_id:
                bug = self.nvbugs.get_bug(bug_id)
                bugs_list = [bug] if bug else []
                label = f"NVBug #{bug_id}"
            elif module and days_open:
                bugs_list = self.nvbugs.search_bugs(
                    filters=[
                        {"FieldName": "ModuleName", "FieldValue": module},
                        {"FieldName": "DaysOpen", "FieldValue": str(days_open)},
                    ]
                )
                label = f"NVBugs — module '{module}', {days_open} days open"
            elif module:
                bugs_list = self.nvbugs.search_by_module(module)
                label = f"NVBugs — module '{module}'"
            elif assigned_to:
                bugs_list = self.nvbugs.get_assigned_bugs(assigned_to)
                label = f"NVBugs assigned to {assigned_to}"
            elif keyword:
                bugs_list = self.nvbugs.search_by_keyword(keyword)
                label = f"NVBugs matching '{keyword}'"
            else:
                print("Error: provide at least one of --module, --assigned-to, --id, or --keyword.")
                return
            print(self._format_nvbugs(bugs_list, label=label))
        except Exception as e:
            print(f"Error fetching NVBugs: {e}")

    def weekly_report(self) -> None:
        """Generate a weekly status report and save it as an Obsidian note."""
        today = date.today()
        week_ago = today - timedelta(days=7)
        context = self._gather_briefing_context()
        prompt = (
            f"Today is {today.isoformat()}. Generate a **Weekly Project Status Report** "
            f"covering the past 7 days ({week_ago.isoformat()} to {today.isoformat()}).\n\n"
            "Structure the report as follows:\n"
            "1. **Summary** — 2-3 sentence overview of the week\n"
            "2. **Completed Work** — Jira issues closed/resolved, PRs/MRs merged\n"
            "3. **In Progress** — active tickets, open PRs/MRs, their status\n"
            "4. **Blockers / Risks** — anything slowing progress\n"
            "5. **Next Week** — top priorities and goals\n"
            "6. **Metrics** — counts: issues closed, PRs merged, MRs merged\n\n"
            "Format in clean Markdown suitable for an Obsidian note.\n\n"
            f"{context}"
        )

        print("Generating weekly report...\n")
        report_md = self._collect_response(prompt)
        print(report_md)
        print()

        if self.obsidian:
            note_title = today.isoformat()
            try:
                path = self.obsidian.upsert_note(
                    title=note_title,
                    content=report_md,
                    subfolder="Weekly Reports",
                )
                print(f"\n[Saved] Weekly Reports/{path}")
            except Exception as e:
                print(f"\n[Warning] Could not save to Obsidian: {e}", file=sys.stderr)
        else:
            print("\n[Info] Obsidian not configured — report not saved.")

    def create_document(
        self,
        doc_type: str,
        project: str = "",
        topic: str = "",
    ) -> None:
        """Generate a TPM document from a built-in template and save to Obsidian.

        Args:
            doc_type: One of por | srd | roadmap | checklist
            project:  Optional Jira project key to scope context.
            topic:    Optional free-text topic for context gathering.
        """
        if doc_type not in _DOC_TEMPLATES:
            valid = ", ".join(_DOC_TEMPLATES)
            print(f"Error: unknown doc type '{doc_type}'. Valid types: {valid}", file=sys.stderr)
            return

        template_instruction = _DOC_TEMPLATES[doc_type]

        # Gather context
        search_term = topic or project or doc_type
        context_parts: list[str] = []
        if project and self.jira:
            context_parts.append(self._fetch_jira_project_context(project))
        if search_term:
            if self.jira and not project:
                context_parts.append(self._fetch_jira_context(search_term))
            if self.confluence:
                context_parts.append(self._fetch_confluence_context(search_term))
            if self.obsidian:
                context_parts.append(self._fetch_obsidian_context(search_term))
        context = "\n\n".join(context_parts) if context_parts else "No additional context available."

        scope_desc = f" for project {project}" if project else (f" on topic '{topic}'" if topic else "")
        prompt = (
            f"{template_instruction}\n\n"
            f"Scope: {scope_desc or 'General'}\n\n"
            "Use the following context from the user's data sources:\n\n"
            f"{context}"
        )

        print(f"Generating {doc_type.upper()} document{scope_desc}...\n")
        doc_md = self._collect_response(prompt)
        print(doc_md)
        print()

        if self.obsidian:
            title_parts = [doc_type.upper()]
            if project:
                title_parts.append(project)
            if topic:
                title_parts.append(topic.replace("/", "-")[:40])
            title_parts.append(date.today().isoformat())
            note_title = " - ".join(title_parts)
            subfolder = f"Documents/{doc_type}"
            try:
                path = self.obsidian.upsert_note(
                    title=note_title,
                    content=doc_md,
                    subfolder=subfolder,
                )
                print(f"[Saved] {subfolder}/{path}")
            except Exception as e:
                print(f"\n[Warning] Could not save to Obsidian: {e}", file=sys.stderr)
        else:
            print("[Info] Obsidian not configured — document not saved.")

    def create_plc_document(
        self,
        template_ref: str,
        output_title: str,
        output_space: str,
        output_parent_id: str | None = None,
        jira_project: str | None = None,
        confluence_page_refs: list[str] | None = None,
        obsidian_search: list[str] | None = None,
        meeting_notes_refs: list[str] | None = None,
        user_context: str | None = None,
    ) -> None:
        """Create a populated PLC document from a Confluence template page."""
        if not self.confluence:
            print("Error: Confluence is not configured. Set CONFLUENCE_* env vars.", file=sys.stderr)
            return

        # 1. Resolve template ref → page ID
        print(f"Fetching template: {template_ref}")
        try:
            page_id = self._resolve_confluence_ref(template_ref)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return

        # 2. Fetch template page
        try:
            template_page = self.confluence.get_page_by_id(page_id)
        except Exception as e:
            print(f"Error: Could not fetch template page {page_id}: {e}", file=sys.stderr)
            return

        print(f'Template: "{template_page["title"]}" ({template_page["space"]})')

        # 3. Extract template sections
        sections = self._extract_template_sections(template_page["storage_html"])
        section_names = [s["heading"] for s in sections]
        print(f"Found {len(sections)} template sections: {section_names}")

        # 4. Gather context
        print("Gathering context from all sources...")
        context = self._fetch_plc_context(
            jira_project=jira_project,
            confluence_page_refs=confluence_page_refs or [],
            obsidian_search=obsidian_search or [],
            meeting_notes_refs=meeting_notes_refs or [],
            user_context=user_context or "",
        )

        # 5. Build prompt and call Claude
        prompt = self._build_plc_prompt(template_page, sections, context, output_title)
        print("Generating PLC document content with Claude...")
        raw_response = self._collect_response_silent(prompt, max_tokens=8192)

        if not raw_response:
            print("Error: Claude returned an empty response.", file=sys.stderr)
            return

        # 6. Extract clean XHTML from response
        html_body = self._extract_html_from_response(raw_response)

        # 7. Create Confluence page
        print(f'Creating Confluence page: "{output_title}" in space {output_space}...')
        try:
            result = self.confluence.create_page(
                space_key=output_space,
                title=output_title,
                body_html=html_body,
                parent_id=output_parent_id,
            )
            print(f"[Created] {result['title']}")
            print(f"URL: {result['url']}")
        except Exception as e:
            print(f"Error: Could not create Confluence page: {e}", file=sys.stderr)
            print("--- Generated HTML (for manual recovery) ---", file=sys.stderr)
            print(html_body, file=sys.stderr)

    def _resolve_confluence_ref(self, ref: str) -> str:
        """Resolve a URL or bare numeric ID to a Confluence page ID string."""
        if ref.startswith("http"):
            return self.confluence.extract_page_id_from_url(ref)  # type: ignore[union-attr]
        if not ref.isdigit():
            raise ValueError(
                f"'{ref}' is not a valid page ID (must be numeric) or URL (must start with http)."
            )
        return ref

    def _fetch_plc_context(
        self,
        jira_project: str | None,
        confluence_page_refs: list[str],
        obsidian_search: list[str],
        meeting_notes_refs: list[str],
        user_context: str,
    ) -> dict:
        """Gather all context sources for the PLC document."""
        result: dict = {
            "jira_issues": [],
            "confluence_pages": [],
            "obsidian_notes": [],
            "meeting_notes": [],
            "user_context": user_context,
            "errors": [],
        }

        if jira_project and self.jira:
            print(f"  Fetching Jira project {jira_project} issues...")
            try:
                result["jira_issues"] = self.jira.get_project_issues(jira_project)
            except Exception as e:
                result["errors"].append(f"Jira project {jira_project}: {e}")

        for ref in confluence_page_refs:
            print(f"  Fetching Confluence page {ref}...")
            try:
                pid = self._resolve_confluence_ref(ref)
                page = self.confluence.get_page_by_id(pid)  # type: ignore[union-attr]
                result["confluence_pages"].append(page)
            except Exception as e:
                result["errors"].append(f"Confluence page {ref}: {e}")

        for term in obsidian_search:
            print(f"  Searching Obsidian for '{term}'...")
            if self.obsidian:
                try:
                    notes = self.obsidian.search(term)
                    result["obsidian_notes"].extend(notes)
                except Exception as e:
                    result["errors"].append(f"Obsidian search '{term}': {e}")
            else:
                result["errors"].append("Obsidian not configured — skipping vault search.")

        for ref in meeting_notes_refs:
            print(f"  Resolving meeting note: {ref[:60]}...")
            self._resolve_meeting_note(ref, result)

        return result

    def _resolve_meeting_note(self, ref: str, result: dict) -> None:
        """Resolve a meeting note reference into result['meeting_notes']."""
        if ref.startswith("text:"):
            raw_text = ref[len("text:"):]
            result["meeting_notes"].append({
                "source": "inline",
                "title": "Inline text",
                "content": raw_text,
                "url": None,
            })
        elif ref.startswith("obsidian:"):
            term = ref[len("obsidian:"):]
            if self.obsidian:
                try:
                    notes = self.obsidian.search(term, limit=5)
                    for note in notes:
                        result["meeting_notes"].append({
                            "source": "obsidian",
                            "title": note.get("title", term),
                            "content": note.get("content", ""),
                            "url": None,
                        })
                except Exception as e:
                    result["errors"].append(f"Obsidian meeting note '{term}': {e}")
            else:
                result["errors"].append("Obsidian not configured — skipping obsidian meeting note.")
        else:
            # Treat as Confluence page URL or ID
            try:
                pid = self._resolve_confluence_ref(ref)
                page = self.confluence.get_page_by_id(pid)  # type: ignore[union-attr]
                result["meeting_notes"].append({
                    "source": "confluence",
                    "title": page.get("title", ref),
                    "content": page.get("content", ""),
                    "url": page.get("url"),
                })
            except Exception as e:
                result["errors"].append(f"Confluence meeting note {ref}: {e}")

    def _extract_template_sections(self, storage_html: str) -> list[dict]:
        """Split Confluence storage XHTML into sections by heading tags."""
        import re
        heading_pattern = re.compile(
            r"(<h([1-6])[^>]*>(.*?)</h\2>)",
            re.IGNORECASE | re.DOTALL,
        )
        matches = list(heading_pattern.finditer(storage_html))
        if not matches:
            plain = self.confluence._strip_html(storage_html)  # type: ignore[union-attr]
            return [{
                "heading": "Document Body",
                "level": 1,
                "html_fragment": storage_html,
                "placeholder_text": plain,
            }]

        sections = []
        for i, match in enumerate(matches):
            heading_tag = match.group(1)
            level = int(match.group(2))
            heading_text = self.confluence._strip_html(match.group(3))  # type: ignore[union-attr]
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(storage_html)
            fragment = storage_html[start:end]
            placeholder = self.confluence._strip_html(fragment)  # type: ignore[union-attr]
            sections.append({
                "heading": heading_text,
                "level": level,
                "html_fragment": fragment,
                "placeholder_text": placeholder,
            })
        return sections

    def _build_plc_prompt(
        self,
        template_page: dict,
        sections: list[dict],
        context: dict,
        output_title: str,
    ) -> str:
        """Build the Claude prompt for PLC document generation."""
        lines: list[str] = []
        lines.append(
            f"You are populating a Product Life Cycle (PLC) document titled \"{output_title}\" "
            f"using the Confluence template \"{template_page['title']}\" as the structure.\n"
        )

        lines.append("## Template Sections\n")
        for i, sec in enumerate(sections, 1):
            preview = sec["placeholder_text"][:200].replace("\n", " ")
            lines.append(f"{i}. [H{sec['level']}] {sec['heading']}")
            if preview:
                lines.append(f"   Placeholder: {preview}")
        lines.append("")

        lines.append("## Template XHTML (Confluence Storage Format)\n")
        lines.append("```xml")
        lines.append(template_page["storage_html"])
        lines.append("```\n")

        # Context blocks
        if context["jira_issues"]:
            lines.append("## Jira Issues\n")
            lines.append(self._format_jira_issues(context["jira_issues"], label="Project Issues"))
            lines.append("")

        if context["confluence_pages"]:
            lines.append("## Reference Confluence Pages\n")
            for page in context["confluence_pages"]:
                lines.append(f"### {page['title']} ({page.get('space', '')})")
                lines.append(f"URL: {page.get('url', '')}")
                lines.append(page.get("content", "")[:2000])
                lines.append("")

        if context["obsidian_notes"]:
            lines.append("## Obsidian Notes\n")
            lines.append(self._format_obsidian_notes(context["obsidian_notes"], label="Vault Notes"))
            lines.append("")

        if context["meeting_notes"]:
            lines.append("## Meeting Notes\n")
            for note in context["meeting_notes"]:
                lines.append(f"### {note['title']} (source: {note['source']})")
                if note.get("url"):
                    lines.append(f"URL: {note['url']}")
                lines.append(note.get("content", "")[:1500])
                lines.append("")

        if context["user_context"]:
            lines.append("## Additional Context Provided by User\n")
            lines.append(context["user_context"])
            lines.append("")

        if context["errors"]:
            lines.append("## Warnings (context sources that failed)\n")
            for err in context["errors"]:
                lines.append(f"- {err}")
            lines.append("")

        lines.append("## Output Rules\n")
        lines.append(
            "1. Output ONLY Confluence Storage Format XHTML — no markdown, no prose.\n"
            "2. Wrap your entire output in <confluence-storage-format>...</confluence-storage-format> tags.\n"
            "3. Preserve all ac: macros exactly as they appear in the template (do not rename or remove them).\n"
            "4. Preserve all table rows and columns from the template.\n"
            "5. Preserve all layout panels (ac:layout, ac:layout-cell).\n"
            "6. If no data is available for a section, output: "
            "<p><em>No data available. Please fill in manually.</em></p>\n"
            "7. Maintain the same heading levels as the template.\n"
            "8. Format Jira issues as: <strong>PROJ-123</strong> — Summary (Status)\n"
            "9. Do NOT hallucinate names, dates, or issue keys that are not present in the context above.\n"
            f"10. Today's date is {date.today().isoformat()}."
        )

        return "\n".join(lines)

    def _extract_html_from_response(self, response: str) -> str:
        """Extract Confluence XHTML from Claude's response using 3-layer fallback."""
        import re
        # Layer 1: explicit wrapper tags
        match = re.search(
            r"<confluence-storage-format>(.*?)</confluence-storage-format>",
            response,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip()

        # Layer 2: xml or html code fence
        match = re.search(
            r"```(?:xml|html)\s*(.*?)```",
            response,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip()

        # Layer 3: return raw stripped response
        return response.strip()

    def _collect_response_silent(self, user_message: str, max_tokens: int = 8192) -> str:
        """Send a message to Claude, print progress dots, and return the full text."""
        chunks: list[str] = []
        chunk_count = 0
        try:
            with self.client.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
                    chunk_count += 1
                    if chunk_count % 50 == 0:
                        print(".", end="", flush=True)
            print()  # final newline after dots
        except anthropic.APIConnectionError:
            print("Error: Could not connect to Anthropic API. Check your internet connection.", file=sys.stderr)
        except anthropic.AuthenticationError:
            print("Error: Invalid ANTHROPIC_API_KEY. Check your .env file.", file=sys.stderr)
        except anthropic.RateLimitError:
            print("Error: Anthropic API rate limit exceeded. Please wait and try again.", file=sys.stderr)
        except anthropic.APIError as e:
            print(f"Error: Anthropic API error: {e}", file=sys.stderr)
        return "".join(chunks)

    # -------------------------------------------------------------------------
    # Context gathering
    # -------------------------------------------------------------------------

    def _fetch_pinned_obsidian_notes(self) -> str:
        """Return context for pinned Obsidian notes (always included in every prompt)."""
        if not self.obsidian or not self.config.obsidian_pinned_notes:
            return ""
        notes = []
        for ref in self.config.obsidian_pinned_notes:
            path = ObsidianConnector.parse_obsidian_url(ref) if ref.startswith("obsidian://") else ref
            if path:
                note = self.obsidian.get_note_by_path(path)
                if note:
                    notes.append(note)
        if not notes:
            return ""
        return self._format_obsidian_notes(notes, label="Pinned Reference Notes (always available)")

    def _gather_context_for_question(self, question: str) -> str:
        sections: list[str] = []
        pinned = self._fetch_pinned_obsidian_notes()
        if pinned:
            sections.append(pinned)
        if self.jira:
            sections.append(self._fetch_jira_context(search_term=question))
        if self.confluence:
            sections.append(self._fetch_confluence_context(search_term=question))
        if self.obsidian:
            sections.append(self._fetch_obsidian_context(search_term=question))
        if self.github:
            sections.append(self._fetch_github_context(query=question))
        if self.gitlab:
            sections.append(self._fetch_gitlab_context(query=question))
        if self.slack:
            sections.append(self._fetch_slack_context(query=question))
        if self.outlook:
            sections.append(self._fetch_outlook_context(query=question))
        if self.nvbugs:
            sections.append(self._fetch_nvbugs_context(query=question))
        if not sections:
            return "No data sources are configured."
        return "\n\n".join(sections)

    def _gather_briefing_context(self) -> str:
        sections: list[str] = []
        pinned = self._fetch_pinned_obsidian_notes()
        if pinned:
            sections.append(pinned)
        if self.jira:
            sections.append(self._fetch_jira_briefing_context())
        if self.confluence:
            sections.append(self._fetch_confluence_recent_context())
        if self.obsidian:
            sections.append(self._fetch_obsidian_recent_context())
        if self.github:
            sections.append(self._fetch_github_briefing_context())
        if self.gitlab:
            sections.append(self._fetch_gitlab_briefing_context())
        if self.slack:
            sections.append(self._fetch_slack_briefing_context())
        if self.outlook:
            sections.append(self._fetch_outlook_briefing_context())
        if self.nvbugs:
            sections.append(self._fetch_nvbugs_briefing_context())
        if not sections:
            return "No data sources are configured."
        return "\n\n".join(sections)

    def _gather_search_context(self, topic: str) -> str:
        return self._gather_context_for_question(topic)

    # -------------------------------------------------------------------------
    # Per-source context fetchers
    # -------------------------------------------------------------------------

    def _fetch_jira_context(self, search_term: str) -> str:
        try:
            issues = self.jira.search_issues(search_term)  # type: ignore[union-attr]
            if not issues:
                assigned = self.jira.get_assigned_issues(max_results=20)  # type: ignore[union-attr]
                return self._format_jira_issues(assigned, label="Your Assigned Jira Issues")
            return self._format_jira_issues(issues, label=f"Jira Issues matching '{search_term}'")
        except Exception as e:
            return f"[Jira] Error fetching data: {e}"

    def _fetch_jira_project_context(self, project_key: str) -> str:
        try:
            from typing import cast
            jira = cast(Any, self.jira)
            jql = (
                f"project = {project_key} AND statusCategory != Done "
                "ORDER BY updated DESC"
            )
            data = jira._get("/search", params={
                "jql": jql,
                "maxResults": 30,
                "fields": "summary,status,priority,project,updated,description,issuetype",
            })
            issues = jira._format_issues(data.get("issues", []))
            return self._format_jira_issues(issues, label=f"Jira project {project_key} — Open Issues")
        except Exception as e:
            return f"[Jira] Error fetching project {project_key}: {e}"

    def _fetch_jira_briefing_context(self) -> str:
        try:
            assigned = self.jira.get_assigned_issues()  # type: ignore[union-attr]
            sprint = self.jira.get_sprint_issues()  # type: ignore[union-attr]
            lines = [self._format_jira_issues(assigned, label="Assigned Issues")]
            if sprint:
                sprint_keys = {i["key"] for i in assigned}
                extra_sprint = [i for i in sprint if i["key"] not in sprint_keys]
                if extra_sprint:
                    lines.append(self._format_jira_issues(extra_sprint, label="Other Sprint Issues"))
            return "\n\n".join(lines)
        except Exception as e:
            return f"[Jira] Error fetching data: {e}"

    def _fetch_confluence_context(self, search_term: str) -> str:
        try:
            pages = self.confluence.search(search_term)  # type: ignore[union-attr]
            return self._format_confluence_pages(pages, label=f"Confluence pages matching '{search_term}'")
        except Exception as e:
            return f"[Confluence] Error fetching data: {e}"

    def _fetch_confluence_recent_context(self) -> str:
        try:
            pages = self.confluence.get_recent_pages(limit=10)  # type: ignore[union-attr]
            return self._format_confluence_pages(pages, label="Recent Confluence Pages")
        except Exception as e:
            return f"[Confluence] Error fetching data: {e}"

    def _fetch_obsidian_context(self, search_term: str) -> str:
        try:
            notes = self.obsidian.search(search_term)  # type: ignore[union-attr]
            return self._format_obsidian_notes(notes, label=f"Obsidian notes matching '{search_term}'")
        except Exception as e:
            return f"[Obsidian] Error reading vault: {e}"

    def _fetch_obsidian_recent_context(self) -> str:
        try:
            notes = self.obsidian.get_recent_notes(limit=10)  # type: ignore[union-attr]
            return self._format_obsidian_notes(notes, label="Recently Modified Obsidian Notes")
        except Exception as e:
            return f"[Obsidian] Error reading vault: {e}"

    def _fetch_github_context(self, query: str) -> str:
        try:
            results = self.github.search(query)  # type: ignore[union-attr]
            return self._format_github_items(results, label=f"GitHub results for '{query}'")
        except Exception as e:
            return f"[GitHub] Error fetching data: {e}"

    def _fetch_github_briefing_context(self) -> str:
        try:
            my_prs = self.github.get_my_prs()  # type: ignore[union-attr]
            review_prs = self.github.get_review_requests()  # type: ignore[union-attr]
            my_issues = self.github.get_my_issues()  # type: ignore[union-attr]
            parts = []
            parts.append(self._format_github_items(my_prs, label="Your Open GitHub PRs"))
            parts.append(self._format_github_items(review_prs, label="GitHub PRs Awaiting Your Review"))
            if my_issues:
                parts.append(self._format_github_items(my_issues, label="Your GitHub Issues"))
            return "\n\n".join(parts)
        except Exception as e:
            return f"[GitHub] Error fetching data: {e}"

    def _fetch_gitlab_context(self, query: str) -> str:
        try:
            results = self.gitlab.search(query)  # type: ignore[union-attr]
            return self._format_gitlab_items(results, label=f"GitLab results for '{query}'")
        except Exception as e:
            return f"[GitLab] Error fetching data: {e}"

    def _fetch_gitlab_briefing_context(self) -> str:
        try:
            my_mrs = self.gitlab.get_my_mrs()  # type: ignore[union-attr]
            review_mrs = self.gitlab.get_review_mrs()  # type: ignore[union-attr]
            my_issues = self.gitlab.get_my_issues()  # type: ignore[union-attr]
            parts = []
            parts.append(self._format_gitlab_items(my_mrs, label="Your Open GitLab MRs"))
            parts.append(self._format_gitlab_items(review_mrs, label="GitLab MRs Awaiting Your Review"))
            if my_issues:
                parts.append(self._format_gitlab_items(my_issues, label="Your GitLab Issues"))
            return "\n\n".join(parts)
        except Exception as e:
            return f"[GitLab] Error fetching data: {e}"

    def _fetch_slack_context(self, query: str) -> str:
        try:
            messages = self.slack.search_messages(query)  # type: ignore[union-attr]
            return self._format_slack_messages(messages, label=f"Slack messages matching '{query}'")
        except RuntimeError as e:
            # search requires a user token — fall back to recent channel messages
            if "user token" in str(e):
                try:
                    messages = self.slack.get_recent_messages_across_channels()  # type: ignore[union-attr]
                    return self._format_slack_messages(messages, label="Recent Slack Messages")
                except Exception as e2:
                    return f"[Slack] Error fetching data: {e2}"
            return f"[Slack] Error fetching data: {e}"
        except Exception as e:
            return f"[Slack] Error fetching data: {e}"

    def _fetch_outlook_context(self, query: str) -> str:
        try:
            emails = self.outlook.search_emails(query, count=10)  # type: ignore[union-attr]
            return self._format_emails(emails, label=f"Outlook emails matching '{query}'")
        except Exception as e:
            return f"[Outlook] Error fetching emails: {e}"

    def _fetch_outlook_briefing_context(self) -> str:
        parts: list[str] = []
        try:
            unread = self.outlook.get_unread_emails(count=10)  # type: ignore[union-attr]
            parts.append(self._format_emails(unread, label="Unread Outlook Emails"))
        except Exception as e:
            parts.append(f"[Outlook] Error fetching unread emails: {e}")
        return "\n\n".join(parts) if parts else "[Outlook] No data available."

    def _fetch_slack_briefing_context(self) -> str:
        parts: list[str] = []
        # Mentions (user token only)
        try:
            mentions = self.slack.get_mentions(count=15)  # type: ignore[union-attr]
            parts.append(self._format_slack_messages(mentions, label="Slack Mentions"))
        except RuntimeError:
            pass
        except Exception as e:
            parts.append(f"[Slack] Mentions error: {e}")

        # Recent channel messages
        try:
            messages = self.slack.get_recent_messages_across_channels(  # type: ignore[union-attr]
                limit_per_channel=10, max_channels=5
            )
            parts.append(self._format_slack_messages(messages, label="Recent Slack Channel Messages"))
        except Exception as e:
            parts.append(f"[Slack] Channel messages error: {e}")

        return "\n\n".join(parts) if parts else "[Slack] No data available."

    def _fetch_nvbugs_context(self, query: str) -> str:
        try:
            bugs = self.nvbugs.search_by_keyword(query, limit=20)  # type: ignore[union-attr]
            return self._format_nvbugs(bugs, label=f"NVBugs matching '{query}'")
        except Exception as e:
            return f"[NVBugs] Error fetching data: {e}"

    def _fetch_nvbugs_briefing_context(self) -> str:
        try:
            bugs = self.nvbugs.search_bugs(  # type: ignore[union-attr]
                filters=[{"FieldName": "Status", "FieldValue": "Open"}],
                limit=20,
            )
            return self._format_nvbugs(bugs, label="Open NVBugs")
        except Exception as e:
            return f"[NVBugs] Error fetching data: {e}"

    # -------------------------------------------------------------------------
    # Formatting helpers
    # -------------------------------------------------------------------------

    def _format_jira_issues(self, issues: list[dict], label: str = "Jira Issues") -> str:
        if not issues:
            return f"[Jira] {label}: No issues found."
        lines = [f"## {label} ({len(issues)} issues)\n"]
        for issue in issues:
            desc = issue["description"][:300] + "..." if len(issue["description"]) > 300 else issue["description"]
            lines.append(
                f"- **{issue['key']}** [{issue['status']}] {issue['summary']}\n"
                f"  Project: {issue['project']} | Priority: {issue['priority']} | "
                f"Type: {issue['issue_type']} | Updated: {issue['updated'][:10] if issue['updated'] else 'N/A'}\n"
                f"  URL: {issue['url']}\n"
                + (f"  Description: {desc}\n" if desc else "")
            )
        return "\n".join(lines)

    def _format_confluence_pages(self, pages: list[dict], label: str = "Confluence Pages") -> str:
        if not pages:
            return f"[Confluence] {label}: No pages found."
        lines = [f"## {label} ({len(pages)} pages)\n"]
        for page in pages:
            content_preview = page["content"][:400] + "..." if len(page["content"]) > 400 else page["content"]
            lines.append(
                f"- **{page['title']}** (Space: {page['space']})\n"
                f"  Last modified: {page['last_modified'][:10] if page['last_modified'] else 'N/A'}"
                + (f" by {page['last_modified_by']}" if page["last_modified_by"] else "")
                + f"\n  URL: {page['url']}\n"
                + (f"  Content preview: {content_preview}\n" if content_preview else "")
            )
        return "\n".join(lines)

    def _format_obsidian_notes(self, notes: list[dict], label: str = "Obsidian Notes") -> str:
        if not notes:
            return f"[Obsidian] {label}: No notes found."
        lines = [f"## {label} ({len(notes)} notes)\n"]
        for note in notes:
            content_preview = note["content"][:400] + "..." if len(note["content"]) > 400 else note["content"]
            tags_str = ", ".join(note["tags"][:5]) if note["tags"] else "none"
            lines.append(
                f"- **{note['title']}** (`{note['path']}`)\n"
                f"  Tags: {tags_str}\n"
                + (f"  Content: {content_preview}\n" if content_preview else "")
            )
        return "\n".join(lines)

    def _format_github_items(self, items: list[dict], label: str = "GitHub Items") -> str:
        if not items:
            return f"[GitHub] {label}: None found."
        lines = [f"## {label} ({len(items)})\n"]
        for item in items:
            labels_str = ", ".join(item.get("labels", [])) or "none"
            updated = (item.get("updated_at") or "")[:10]
            lines.append(
                f"- **{item['kind']} #{item['number']}** [{item['state']}] {item['title']}\n"
                f"  Repo: {item['repo']} | Labels: {labels_str} | Updated: {updated}\n"
                f"  URL: {item['url']}\n"
            )
        return "\n".join(lines)

    def _format_slack_messages(self, messages: list[dict], label: str = "Slack Messages") -> str:
        if not messages:
            return f"[Slack] {label}: No messages found."
        lines = [f"## {label} ({len(messages)} messages)\n"]
        for msg in messages:
            channel = msg.get("channel_name") or msg.get("channel_id", "")
            channel_str = f"#{channel}" if channel else ""
            permalink = msg.get("permalink", "")
            lines.append(
                f"- **{msg.get('user', 'unknown')}** {channel_str} @ {msg.get('timestamp', '')}\n"
                f"  {msg.get('text', '')}\n"
                + (f"  Link: {permalink}\n" if permalink else "")
            )
        return "\n".join(lines)

    def _format_emails(self, emails: list[dict], label: str = "Outlook Emails") -> str:
        if not emails:
            return f"[Outlook] {label}: No emails found."
        lines = [f"## {label} ({len(emails)} emails)\n"]
        for email in emails:
            received = (email.get("received") or "")[:10]
            read_flag = "" if email.get("is_read") else " [UNREAD]"
            sender = email.get("from_name") or email.get("from_email", "unknown")
            preview = email.get("preview", "")
            lines.append(
                f"- **{email.get('subject', '(no subject)')}**{read_flag}\n"
                f"  From: {sender} <{email.get('from_email', '')}> | Received: {received}\n"
                + (f"  Preview: {preview[:300]}\n" if preview else "")
            )
        return "\n".join(lines)

    def _format_nvbugs(self, bugs: list[dict], label: str = "NVBugs") -> str:
        if not bugs:
            return f"[NVBugs] {label}: No bugs found."
        lines = [f"## {label} ({len(bugs)} bugs)\n"]
        for bug in bugs:
            lines.append(
                f"- **Bug #{bug['id']}** [{bug['status']}] {bug['synopsis']}\n"
                f"  Module: {bug['module']} | Priority: {bug['priority']} | "
                f"Severity: {bug['severity']} | Disposition: {bug['disposition']}\n"
                f"  Assigned: {bug['assigned_to']} | Submitted: {bug['submitted']} | "
                f"Days Open: {bug['days_open']}\n"
                + (f"  OS: {bug['os']}\n" if bug.get("os") else "")
                + (f"  Version: {bug['version']}\n" if bug.get("version") else "")
            )
        return "\n".join(lines)

    def _format_gitlab_items(self, items: list[dict], label: str = "GitLab Items") -> str:
        if not items:
            return f"[GitLab] {label}: None found."
        lines = [f"## {label} ({len(items)})\n"]
        for item in items:
            updated = (item.get("updated_at") or "")[:10]
            extra = ""
            if item["kind"] == "MR":
                extra = f"  Branch: {item.get('source_branch', '')} → {item.get('target_branch', '')}\n"
            lines.append(
                f"- **{item['kind']} !{item['iid']}** [{item['state']}] {item['title']}\n"
                f"  Project: {item['project']} | Updated: {updated}\n"
                + extra
                + f"  URL: {item['url']}\n"
            )
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Claude API calls with streaming / collection
    # -------------------------------------------------------------------------

    def _stream_response(self, user_message: str) -> None:
        """Send a message to Claude and stream the response to stdout."""
        try:
            with self.client.messages.stream(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
            print()  # final newline
        except anthropic.APIConnectionError:
            print("Error: Could not connect to Anthropic API. Check your internet connection.", file=sys.stderr)
        except anthropic.AuthenticationError:
            print("Error: Invalid ANTHROPIC_API_KEY. Check your .env file.", file=sys.stderr)
        except anthropic.RateLimitError:
            print("Error: Anthropic API rate limit exceeded. Please wait and try again.", file=sys.stderr)
        except anthropic.APIError as e:
            print(f"Error: Anthropic API error: {e}", file=sys.stderr)

    def _collect_response(self, user_message: str) -> str:
        """Send a message to Claude, stream to stdout, and return the full text."""
        chunks: list[str] = []
        try:
            with self.client.messages.stream(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                    chunks.append(text)
            print()  # final newline
        except anthropic.APIConnectionError:
            print("Error: Could not connect to Anthropic API. Check your internet connection.", file=sys.stderr)
        except anthropic.AuthenticationError:
            print("Error: Invalid ANTHROPIC_API_KEY. Check your .env file.", file=sys.stderr)
        except anthropic.RateLimitError:
            print("Error: Anthropic API rate limit exceeded. Please wait and try again.", file=sys.stderr)
        except anthropic.APIError as e:
            print(f"Error: Anthropic API error: {e}", file=sys.stderr)
        return "".join(chunks)
