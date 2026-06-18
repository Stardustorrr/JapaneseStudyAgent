from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .notes import GrammarEntry


SRS_PATH = DATA_DIR / "grammar_srs.json"


@dataclass
class GrammarReviewState:
    title: str
    reps: int = 0
    lapses: int = 0
    ease: float = 2.3
    interval_days: int = 0
    due: str = ""
    last_reviewed: str = ""
    last_score: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GrammarReviewState":
        return cls(
            title=str(payload.get("title", "")),
            reps=int(payload.get("reps", 0)),
            lapses=int(payload.get("lapses", 0)),
            ease=float(payload.get("ease", 2.3)),
            interval_days=int(payload.get("interval_days", 0)),
            due=str(payload.get("due", "")),
            last_reviewed=str(payload.get("last_reviewed", "")),
            last_score=payload.get("last_score"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "reps": self.reps,
            "lapses": self.lapses,
            "ease": self.ease,
            "interval_days": self.interval_days,
            "due": self.due,
            "last_reviewed": self.last_reviewed,
            "last_score": self.last_score,
        }


def load_grammar_srs() -> dict[str, GrammarReviewState]:
    if not SRS_PATH.exists():
        return {}
    try:
        payload = json.loads(SRS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {title: GrammarReviewState.from_dict(item) for title, item in payload.items()}


def save_grammar_srs(states: dict[str, GrammarReviewState]) -> Path:
    SRS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {title: state.to_dict() for title, state in sorted(states.items())}
    SRS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return SRS_PATH


def mark_grammar_due(titles: list[str], due_date: str | None = None) -> None:
    if not titles:
        return

    today = parse_date(due_date).isoformat() if due_date else date.today().isoformat()
    states = load_grammar_srs()
    for title in titles:
        state = states.get(title, GrammarReviewState(title=title))
        state.due = today
        states[title] = state
    save_grammar_srs(states)


def update_grammar_review(title: str, score: int, review_date: str | None = None) -> GrammarReviewState:
    today = parse_date(review_date) if review_date else date.today()
    states = load_grammar_srs()
    state = states.get(title, GrammarReviewState(title=title))
    state.reps += 1
    state.last_reviewed = today.isoformat()
    state.last_score = score

    if score < 60:
        state.lapses += 1
        state.ease = max(1.3, state.ease - 0.25)
        state.interval_days = 1
    elif score < 80:
        state.ease = max(1.4, state.ease - 0.1)
        state.interval_days = max(1, min(2, state.interval_days))
    else:
        if state.interval_days <= 0:
            state.interval_days = 2
        elif state.interval_days == 1:
            state.interval_days = 4
        else:
            state.interval_days = max(1, round(state.interval_days * state.ease))
        if score >= 95:
            state.ease = min(3.0, state.ease + 0.08)

    state.due = (today + timedelta(days=state.interval_days)).isoformat()
    states[title] = state
    save_grammar_srs(states)
    return state


def grammar_weight(
    entry: GrammarEntry,
    states: dict[str, GrammarReviewState],
    today: date,
    recent_titles: set[str],
) -> float:
    state = states.get(entry.title)
    weight = 1.0

    if state is None:
        weight += 2.0
    else:
        due_date = parse_date(state.due) if state.due else today
        days_overdue = (today - due_date).days
        if days_overdue >= 0:
            weight += 3.0 + min(days_overdue, 7) * 0.35
        else:
            weight *= 0.35
        weight += min(state.lapses, 5) * 0.8
        if state.last_score is not None and state.last_score < 80:
            weight += (80 - state.last_score) / 20

    if entry.title in recent_titles:
        weight *= 0.35

    return max(weight, 0.05)


def parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return date.today()
