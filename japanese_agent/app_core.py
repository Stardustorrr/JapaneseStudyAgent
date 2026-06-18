from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any

from .anki import VocabularyEntry, load_anki_vocabulary
from .config import get_model, get_notes_dir
from .exercises import GENERATION_MODE_RANDOM, ExerciseSet, build_exercise_set, normalize_generation_mode
from .grammar_srs import load_grammar_srs
from .notes import load_entries
from .openai_client import JapaneseTutorClient
from .session import load_recent_grammar_titles, load_session, save_session


LEGACY_EXERCISE_TYPES = {"sentence_creation"}
LEGACY_PROMPT_MARKERS = ("请用", "尽量使用", "说明句子里")


@dataclass
class PracticeState:
    date: str
    notes_dir: Path
    exercise_set: ExerciseSet
    answers: list[dict[str, Any]]
    tutor: JapaneseTutorClient | None
    regenerated: bool
    used_existing: bool
    vocabulary: list[VocabularyEntry]
    vocabulary_status: str
    generation_mode: str


def build_tutor(model: str | None = None) -> JapaneseTutorClient | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None

    try:
        return JapaneseTutorClient(model=get_model(model))
    except ModuleNotFoundError as error:
        if error.name == "openai":
            raise RuntimeError("缺少依赖 openai，请先安装 requirements.txt。") from error
        raise


def load_practice_state(
    date_value: str,
    notes_dir_value: str | None = None,
    model: str | None = None,
    cn_to_ja_count: int = 3,
    ja_to_cn_count: int = 2,
    regenerate: bool = False,
    generation_mode: str = GENERATION_MODE_RANDOM,
) -> PracticeState:
    mode = normalize_generation_mode(generation_mode)
    notes_dir = get_notes_dir(notes_dir_value)
    entries = load_entries(notes_dir)
    if not entries:
        raise RuntimeError(f"No grammar entries found in {notes_dir}")

    tutor = build_tutor(model)
    vocabulary, vocabulary_status = load_anki_vocabulary(date_value)
    existing = load_session(date_value)
    existing_exercise_set = ExerciseSet.from_dict(existing["exercise_set"]) if existing else None
    existing_answers = (
        normalize_answer_records(existing.get("answers", []), existing_exercise_set) if existing else []
    )
    recent_grammar_titles = load_recent_grammar_titles(date_value)
    grammar_states = load_grammar_srs()
    existing_mode = existing_exercise_set.generation_mode if existing_exercise_set else ""
    should_regenerate = regenerate or bool(existing and (has_legacy_exercises(existing) or existing_mode != mode))

    if existing and not should_regenerate:
        exercise_set = ExerciseSet.from_dict(existing["exercise_set"])
        answers: list[dict[str, Any]] = existing_answers
        used_existing = True
        regenerated = False
    else:
        try:
            exercise_set = build_exercise_set(
                tutor=tutor,
                date=date_value,
                entries=entries,
                vocabulary=vocabulary,
                cn_to_ja_count=cn_to_ja_count,
                ja_to_cn_count=ja_to_cn_count,
                recent_grammar_titles=recent_grammar_titles,
                grammar_states=grammar_states,
                generation_mode=mode,
            )
        except Exception as error:
            if not tutor:
                raise
            vocabulary_status = f"{vocabulary_status}; AI generation failed, used local fallback: {error}"
            exercise_set = build_exercise_set(
                tutor=None,
                date=date_value,
                entries=entries,
                vocabulary=vocabulary,
                cn_to_ja_count=cn_to_ja_count,
                ja_to_cn_count=ja_to_cn_count,
                recent_grammar_titles=recent_grammar_titles,
                grammar_states=grammar_states,
                generation_mode=mode,
            )
        answers = carry_over_answers(existing_answers, exercise_set)
        save_session(date_value, exercise_set, answers)
        used_existing = False
        regenerated = True

    return PracticeState(
        date=date_value,
        notes_dir=notes_dir,
        exercise_set=exercise_set,
        answers=answers,
        tutor=tutor,
        regenerated=regenerated,
        used_existing=used_existing,
        vocabulary=vocabulary,
        vocabulary_status=vocabulary_status,
        generation_mode=exercise_set.generation_mode,
    )


def has_legacy_exercises(session: dict[str, Any]) -> bool:
    exercises = session.get("exercise_set", {}).get("exercises", [])
    return any(
        item.get("type") in LEGACY_EXERCISE_TYPES
        or "vocabulary_focus" not in item
        or "answer_explanation" not in item
        or "grammar_focuses" not in item
        or "difficulty" not in item
        or any(marker in item.get("prompt", "") for marker in LEGACY_PROMPT_MARKERS)
        for item in exercises
    )


def normalize_answer_records(
    records: list[dict[str, Any]],
    exercise_set: ExerciseSet | None = None,
) -> list[dict[str, Any]]:
    exercises_by_id = {exercise.id: exercise for exercise in exercise_set.exercises} if exercise_set else {}
    normalized: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        if "review_recorded" not in item:
            item["review_recorded"] = True
        if "exercise_snapshot" not in item and item.get("exercise_id") in exercises_by_id:
            item["exercise_snapshot"] = exercise_to_snapshot(exercises_by_id[item["exercise_id"]])
        normalized.append(item)
    return normalized


def carry_over_answers(existing_answers: list[dict[str, Any]], exercise_set: ExerciseSet) -> list[dict[str, Any]]:
    if not existing_answers:
        return []

    exercises_by_id = {exercise.id: exercise for exercise in exercise_set.exercises}
    carried: list[dict[str, Any]] = []
    used_answer_indexes: set[int] = set()

    for index, answer in enumerate(existing_answers):
        exercise = exercises_by_id.get(str(answer.get("exercise_id", "")))
        if exercise and answer_matches_exercise(answer, exercise):
            carried.append(answer)
            used_answer_indexes.add(index)

    for exercise in exercise_set.exercises:
        if any(answer.get("exercise_id") == exercise.id for answer in carried):
            continue
        for index, answer in enumerate(existing_answers):
            if index in used_answer_indexes:
                continue
            if answer_matches_exercise(answer, exercise):
                updated = dict(answer)
                updated["exercise_id"] = exercise.id
                carried.append(updated)
                used_answer_indexes.add(index)
                break

    return carried


def answer_matches_exercise(answer: dict[str, Any], exercise: Any) -> bool:
    snapshot = answer.get("exercise_snapshot")
    if not isinstance(snapshot, dict):
        return False
    return (
        snapshot.get("prompt") == exercise.prompt
        and snapshot.get("type") == exercise.type
        and snapshot.get("grammar_focuses", [snapshot.get("grammar_focus")]) == (exercise.grammar_focuses or [exercise.grammar_focus])
    )


def exercise_to_snapshot(exercise: Any) -> dict[str, Any]:
    return {
        "id": exercise.id,
        "type": exercise.type,
        "prompt": exercise.prompt,
        "grammar_focus": exercise.grammar_focus,
        "grammar_focuses": exercise.grammar_focuses or [exercise.grammar_focus],
        "difficulty": exercise.difficulty,
        "reference_answer": exercise.reference_answer,
        "vocabulary_focus": exercise.vocabulary_focus or [],
    }
