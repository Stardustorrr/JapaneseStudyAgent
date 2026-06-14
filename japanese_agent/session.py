from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .exercises import ExerciseSet


def session_path(date: str) -> Path:
    return DATA_DIR / "sessions" / f"{date}.json"


def load_session(date: str) -> dict[str, Any] | None:
    path = session_path(date)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_session(date: str, exercise_set: ExerciseSet, answers: list[dict[str, Any]]) -> Path:
    path = session_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date,
        "exercise_set": exercise_set.to_dict(),
        "answers": answers,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_recent_grammar_titles(current_date: str, limit: int = 7) -> set[str]:
    sessions_dir = DATA_DIR / "sessions"
    if not sessions_dir.exists():
        return set()

    recent_files = sorted(
        (path for path in sessions_dir.glob("*.json") if path.stem != current_date),
        key=lambda path: path.stem,
        reverse=True,
    )[:limit]

    titles: set[str] = set()
    for path in recent_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        titles.update(payload.get("exercise_set", {}).get("notes_used", []))
    return titles
