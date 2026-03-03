"""Obsidian vault connector — reads markdown files from a local directory."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, unquote, urlparse


class ObsidianConnector:
    """Reads and indexes markdown files from an Obsidian vault directory."""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        if not self.vault_path.is_dir():
            raise ValueError(f"Obsidian vault path does not exist or is not a directory: {vault_path}")

    def get_all_notes(self, max_notes: int = 200) -> list[dict]:
        """Return all markdown notes in the vault, sorted by modification time (newest first)."""
        notes = []
        for note in self._iter_notes():
            notes.append(note)
            if len(notes) >= max_notes:
                break
        return notes

    def get_recent_notes(self, limit: int = 20) -> list[dict]:
        """Return the most recently modified notes."""
        all_notes = list(self._iter_notes())
        all_notes.sort(key=lambda n: n["modified"], reverse=True)
        return all_notes[:limit]

    @staticmethod
    def parse_obsidian_url(url: str) -> str | None:
        """Extract the vault-relative file path from an obsidian:// URL.

        Returns the decoded path string (without .md) or None if not parseable.
        """
        parsed = urlparse(url)
        if parsed.scheme != "obsidian":
            return None
        params = parse_qs(parsed.query)
        file_param = params.get("file", [None])[0]
        return unquote(file_param) if file_param else None

    def get_note_by_path(self, relative_path: str) -> dict | None:
        """Return a note dict for the given vault-relative path, or None if not found.

        Accepts paths with or without the .md extension and tolerates forward/
        back-slash differences.
        """
        relative_path = relative_path.replace("\\", "/")
        for candidate in (relative_path, f"{relative_path}.md"):
            filepath = self.vault_path / candidate
            if filepath.is_file():
                try:
                    stat = filepath.stat()
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                    return {
                        "title": filepath.stem,
                        "path": str(filepath.relative_to(self.vault_path)),
                        "content": self._clean_markdown(content)[:4000],
                        "raw_content": content[:4000],
                        "modified": stat.st_mtime,
                        "size_bytes": stat.st_size,
                        "tags": self._extract_tags(content),
                        "frontmatter": self._extract_frontmatter(content),
                    }
                except (OSError, PermissionError):
                    return None
        return None

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search notes whose title or content contains the query string (case-insensitive)."""
        query_lower = query.lower()
        matches = []
        for note in self._iter_notes():
            if (
                query_lower in note["title"].lower()
                or query_lower in note["content"].lower()
            ):
                matches.append(note)
            if len(matches) >= limit:
                break
        return matches

    def _iter_notes(self) -> Iterator[dict]:
        """Walk the vault directory and yield structured note dicts."""
        for root, dirs, files in os.walk(self.vault_path):
            # Skip hidden directories (e.g., .obsidian, .git)
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for filename in files:
                if not filename.endswith(".md"):
                    continue
                filepath = Path(root) / filename
                try:
                    stat = filepath.stat()
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                    title = filename[:-3]  # strip .md
                    relative_path = str(filepath.relative_to(self.vault_path))

                    yield {
                        "title": title,
                        "path": relative_path,
                        "content": self._clean_markdown(content)[:4000],  # cap per note
                        "raw_content": content[:4000],
                        "modified": stat.st_mtime,
                        "size_bytes": stat.st_size,
                        "tags": self._extract_tags(content),
                        "frontmatter": self._extract_frontmatter(content),
                    }
                except (OSError, PermissionError):
                    continue

    def _clean_markdown(self, text: str) -> str:
        """Strip common markdown syntax for cleaner LLM context."""
        # Remove YAML frontmatter
        text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
        # Remove code blocks (keep content)
        text = re.sub(r"```[^\n]*\n(.*?)```", r"\1", text, flags=re.DOTALL)
        # Remove inline code markers
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Remove Obsidian internal links [[Note Name|alias]] → alias or Note Name
        text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
        text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
        # Remove markdown links [text](url) → text
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        # Remove image syntax
        text = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", "", text)
        # Remove heading markers but keep text
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove bold/italic markers
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
        # Remove horizontal rules
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_tags(self, content: str) -> list[str]:
        """Extract #tags from the note content."""
        # Tags in frontmatter (tags: [tag1, tag2] or tags:\n  - tag1)
        frontmatter_tags: list[str] = []
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            fm = fm_match.group(1)
            inline = re.search(r"tags:\s*\[([^\]]+)\]", fm)
            if inline:
                frontmatter_tags = [t.strip().strip("\"'") for t in inline.group(1).split(",")]
            else:
                list_tags = re.findall(r"^\s*-\s*(.+)$", fm, re.MULTILINE)
                if list_tags:
                    frontmatter_tags = [t.strip() for t in list_tags]

        # Inline #tags in content body
        inline_tags = re.findall(r"(?<!\w)#([a-zA-Z][a-zA-Z0-9_/-]*)", content)

        all_tags = list(dict.fromkeys(frontmatter_tags + inline_tags))  # deduplicate, preserve order
        return all_tags

    # -------------------------------------------------------------------------
    # Write methods
    # -------------------------------------------------------------------------

    def write_note(self, title: str, content: str, subfolder: str = "") -> str:
        """Create a new note. Raises FileExistsError if the file already exists.

        Returns the path of the created file.
        """
        target_dir = self.vault_path / subfolder if subfolder else self.vault_path
        target_dir.mkdir(parents=True, exist_ok=True)
        filepath = target_dir / f"{title}.md"
        if filepath.exists():
            raise FileExistsError(f"Note already exists: {filepath}")
        filepath.write_text(content, encoding="utf-8")
        return str(filepath.relative_to(self.vault_path))

    def upsert_note(self, title: str, content: str, subfolder: str = "") -> str:
        """Create or overwrite a note.

        Returns the path of the written file.
        """
        target_dir = self.vault_path / subfolder if subfolder else self.vault_path
        target_dir.mkdir(parents=True, exist_ok=True)
        filepath = target_dir / f"{title}.md"
        filepath.write_text(content, encoding="utf-8")
        return str(filepath.relative_to(self.vault_path))

    def _extract_frontmatter(self, content: str) -> dict:
        """Parse YAML-like frontmatter into a simple key→value dict (strings only)."""
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not fm_match:
            return {}
        fm = fm_match.group(1)
        result: dict = {}
        for line in fm.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and value:
                    result[key] = value
        return result
