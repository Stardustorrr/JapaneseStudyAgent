from __future__ import annotations

from dataclasses import dataclass
import random
import re
from typing import Any

from .config import (
    DEFAULT_ANKI_MEANING_FIELDS,
    DEFAULT_ANKI_READING_FIELDS,
    DEFAULT_ANKI_WORD_FIELDS,
    get_anki_connect_url,
    get_anki_enabled,
    get_anki_limit,
    get_anki_query,
    get_field_names,
)


@dataclass(frozen=True)
class VocabularyEntry:
    word: str
    reading: str = ""
    meaning: str = ""
    source: str = "Anki"
    priority: float = 0.0

    @property
    def compact(self) -> str:
        parts = [self.word]
        if self.reading:
            parts.append(f"({self.reading})")
        if self.meaning:
            parts.append(f"- {self.meaning}")
        return " ".join(parts)


def load_anki_vocabulary(date_value: str, limit: int | None = None) -> tuple[list[VocabularyEntry], str]:
    if not get_anki_enabled():
        return [], "Anki vocabulary disabled"

    query = get_anki_query()
    if not query:
        return [], "Anki query is not configured"

    fetch_limit = get_anki_limit() if limit is None else limit
    if fetch_limit <= 0:
        return [], "Anki vocabulary limit is 0"

    try:
        selected_ids, counts, priority_by_note = select_priority_note_ids(query, fetch_limit, date_value)
        if not selected_ids:
            return [], "Anki query returned 0 notes"

        notes = invoke_anki("notesInfo", {"notes": selected_ids})
        vocabulary = parse_notes(notes, priority_by_note)
        return vocabulary, (
            f"Loaded {len(vocabulary)} Anki words "
            f"(recent-low {counts['recent_low']}, due {counts['due']}, forgotten {counts['forgotten']}, regular {counts['regular']})"
        )
    except Exception as error:
        return [], f"Could not load Anki vocabulary: {error}"


def select_priority_note_ids(query: str, limit: int, date_value: str) -> tuple[list[int], dict[str, int], dict[int, float]]:
    all_ids = find_notes_safely(query)
    priority_by_note = load_recent_review_priority(all_ids)
    recent_low_ids = sorted(priority_by_note, key=lambda note_id: priority_by_note[note_id], reverse=True)
    due_ids = find_notes_safely(f"({query}) is:due")
    forgotten_ids = find_notes_safely(f"({query}) prop:lapses>0")
    regular_ids = all_ids

    rng = random.Random(date_value)
    recent_low_ids = stable_priority_shuffle(recent_low_ids, priority_by_note, rng)
    due_ids = shuffled(due_ids, rng)
    forgotten_ids = shuffled(forgotten_ids, rng)
    regular_ids = shuffled(regular_ids, rng)

    selected: list[int] = []
    selected_sources: dict[str, int] = {"recent_low": 0, "due": 0, "forgotten": 0, "regular": 0}
    seen: set[int] = set()

    def add_candidates(candidates: list[int], source: str, quota: int | None = None) -> None:
        for note_id in candidates:
            if len(selected) >= limit:
                break
            if quota is not None and selected_sources[source] >= quota:
                break
            if note_id in seen:
                continue
            seen.add(note_id)
            selected.append(note_id)
            selected_sources[source] += 1

    recent_quota = max(1, int(limit * 0.5))
    due_quota = max(1, int(limit * 0.25))
    forgotten_quota = max(1, int(limit * 0.2))
    add_candidates(recent_low_ids, "recent_low", recent_quota)
    add_candidates(due_ids, "due", due_quota)
    add_candidates(forgotten_ids, "forgotten", forgotten_quota)
    add_candidates(recent_low_ids, "recent_low")
    add_candidates(due_ids, "due")
    add_candidates(forgotten_ids, "forgotten")
    add_candidates(regular_ids, "regular")

    return selected, selected_sources, priority_by_note


def load_recent_review_priority(note_ids: list[int]) -> dict[int, float]:
    if not note_ids:
        return {}
    try:
        notes = invoke_anki("notesInfo", {"notes": note_ids})
        card_ids = [card_id for note in notes for card_id in note.get("cards", [])]
        cards = invoke_anki("cardsInfo", {"cards": card_ids})
    except Exception:
        return {}

    priority_by_note: dict[int, float] = {}
    for card in cards or []:
        note_id = int(card.get("note", 0) or 0)
        if not note_id:
            continue
        priority = card_review_priority(card)
        priority_by_note[note_id] = max(priority_by_note.get(note_id, 0.0), priority)
    return {note_id: priority for note_id, priority in priority_by_note.items() if priority > 0}


def card_review_priority(card: dict[str, Any]) -> float:
    reps = int(card.get("reps", 0) or 0)
    if reps <= 0:
        return 0.0

    lapses = int(card.get("lapses", 0) or 0)
    interval = max(0, int(card.get("interval", 0) or 0))
    factor = int(card.get("factor", 2500) or 2500)
    queue = int(card.get("queue", 0) or 0)
    card_type = int(card.get("type", 0) or 0)

    familiarity_penalty = 1.0
    familiarity_penalty += min(lapses, 5) * 1.2
    familiarity_penalty += max(0, 2300 - factor) / 300
    familiarity_penalty += max(0, 7 - interval) / 7
    if queue in {1, 3} or card_type == 1:
        familiarity_penalty += 0.8
    return familiarity_penalty


def stable_priority_shuffle(note_ids: list[int], priority_by_note: dict[int, float], rng: random.Random) -> list[int]:
    return sorted(note_ids, key=lambda note_id: (priority_by_note.get(note_id, 0.0), rng.random()), reverse=True)


def find_notes_safely(query: str) -> list[int]:
    try:
        return list(invoke_anki("findNotes", {"query": query}) or [])
    except Exception:
        return []


def shuffled(values: list[int], rng: random.Random) -> list[int]:
    copy = values[:]
    rng.shuffle(copy)
    return copy


def invoke_anki(action: str, params: dict[str, Any]) -> Any:
    try:
        import requests
    except ModuleNotFoundError as error:
        raise RuntimeError("缺少 requests 依赖，请运行 pip install -r requirements.txt") from error

    response = requests.post(
        get_anki_connect_url(),
        json={"action": action, "version": 6, "params": params},
        timeout=3,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload.get("result")


def parse_notes(notes: list[dict[str, Any]], priority_by_note: dict[int, float] | None = None) -> list[VocabularyEntry]:
    word_fields = get_field_names("JAPANESE_AGENT_ANKI_WORD_FIELDS", DEFAULT_ANKI_WORD_FIELDS)
    reading_fields = get_field_names("JAPANESE_AGENT_ANKI_READING_FIELDS", DEFAULT_ANKI_READING_FIELDS)
    meaning_fields = get_field_names("JAPANESE_AGENT_ANKI_MEANING_FIELDS", DEFAULT_ANKI_MEANING_FIELDS)

    entries: list[VocabularyEntry] = []
    seen: set[str] = set()
    for note in notes:
        note_id = int(note.get("noteId", 0) or note.get("id", 0) or 0)
        fields = note.get("fields", {})
        word = pick_field(fields, word_fields)
        if not word or word in seen:
            continue
        seen.add(word)
        entries.append(
            VocabularyEntry(
                word=word,
                reading=pick_field(fields, reading_fields),
                meaning=pick_field(fields, meaning_fields),
                priority=(priority_by_note or {}).get(note_id, 0.0),
            )
        )
    return entries


def pick_field(fields: dict[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = fields.get(name)
        if isinstance(value, dict):
            text = str(value.get("value", "")).strip()
        else:
            text = str(value or "").strip()
        if text:
            return clean_html(text)
    return ""


def clean_html(value: str) -> str:
    cleaned = (
        value.replace("<br>", " ")
        .replace("<br />", " ")
        .replace("<br/>", " ")
        .replace("&nbsp;", " ")
        .strip()
    )
    cleaned = re.sub(r"\[sound:[^\]]+\]", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()
