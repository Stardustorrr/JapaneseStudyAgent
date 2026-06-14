from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class GrammarEntry:
    source: str
    title: str
    content: str

    @property
    def compact(self) -> str:
        return f"{self.title}\n{self.content}".strip()


def load_entries(notes_dir: Path) -> list[GrammarEntry]:
    if not notes_dir.exists():
        raise FileNotFoundError(f"Notes directory does not exist: {notes_dir}")

    entries: list[GrammarEntry] = []
    for path in sorted(notes_dir.glob("*.md")):
        entries.extend(parse_markdown_file(path))

    return entries


def parse_markdown_file(path: Path) -> list[GrammarEntry]:
    lines = path.read_text(encoding="utf-8").splitlines()
    headings: list[tuple[int, str, int]] = []

    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            headings.append((level, title, index))

    entries: list[GrammarEntry] = []
    title_stack: dict[int, str] = {}
    for heading_index, (level, title, start) in enumerate(headings):
        title_stack = {key: value for key, value in title_stack.items() if key < level}
        title_stack[level] = title

        end = headings[heading_index + 1][2] if heading_index + 1 < len(headings) else len(lines)

        body = "\n".join(lines[start + 1 : end]).strip()
        if not body:
            continue

        parent_titles = [title_stack[key] for key in sorted(title_stack) if key < level]
        title_path = " / ".join([*parent_titles[-2:], title]) if parent_titles else title
        entries.append(GrammarEntry(source=path.name, title=title_path, content=body))

    return entries
