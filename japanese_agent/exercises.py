from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import random
from typing import Any

from .anki import VocabularyEntry
from .config import get_max_grammar_per_exercise, get_review_mode_exercise_limit
from .grammar_srs import GrammarReviewState, grammar_weight, mark_grammar_due, parse_date
from .notes import GrammarEntry


GENERATION_MODE_REVIEW = "review"
GENERATION_MODE_RANDOM = "random"
GENERATION_MODES = {GENERATION_MODE_REVIEW, GENERATION_MODE_RANDOM}
AI_EXERCISE_BATCH_SIZE = 8


@dataclass
class Exercise:
    id: str
    type: str
    prompt: str
    grammar_focus: str
    reference_answer: str
    hint: str = ""
    vocabulary_focus: list[str] | None = None
    answer_explanation: str = ""
    grammar_focuses: list[str] | None = None
    difficulty: int = 1


@dataclass
class ExerciseSet:
    date: str
    notes_used: list[str]
    exercises: list[Exercise]
    vocabulary_used: list[str] | None = None
    generation_mode: str = GENERATION_MODE_RANDOM

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "notes_used": self.notes_used,
            "vocabulary_used": self.vocabulary_used or [],
            "generation_mode": self.generation_mode,
            "exercises": [asdict(exercise) for exercise in self.exercises],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExerciseSet":
        return cls(
            date=payload["date"],
            notes_used=list(payload.get("notes_used", [])),
            vocabulary_used=list(payload.get("vocabulary_used", [])),
            generation_mode=normalize_generation_mode(payload.get("generation_mode")),
            exercises=[Exercise(**normalize_exercise_payload(item)) for item in payload.get("exercises", [])],
        )


def select_daily_entries(entries: list[GrammarEntry], date: str, limit: int = 8) -> list[GrammarEntry]:
    return select_daily_entries_avoiding(entries, date, set(), limit)


def select_daily_entries_avoiding(
    entries: list[GrammarEntry],
    date: str,
    recent_titles: set[str],
    limit: int = 8,
    grammar_states: dict[str, GrammarReviewState] | None = None,
) -> list[GrammarEntry]:
    if not entries:
        return []

    rng = random.Random(date)
    today = parse_date(date)
    remaining = entries[:]
    selected: list[GrammarEntry] = []
    states = grammar_states or {}

    while remaining and len(selected) < limit:
        weights = [grammar_weight(entry, states, today, recent_titles) for entry in remaining]
        chosen_index = weighted_choice_index(weights, rng)
        selected.append(remaining.pop(chosen_index))

    return selected


def build_exercise_set(
    tutor: Any | None,
    date: str,
    entries: list[GrammarEntry],
    vocabulary: list[VocabularyEntry],
    cn_to_ja_count: int,
    ja_to_cn_count: int,
    recent_grammar_titles: set[str] | None = None,
    grammar_states: dict[str, GrammarReviewState] | None = None,
    generation_mode: str = GENERATION_MODE_RANDOM,
) -> ExerciseSet:
    mode = normalize_generation_mode(generation_mode)
    if mode == GENERATION_MODE_REVIEW:
        cn_groups, ja_groups = build_review_mode_groups(
            entries,
            date,
            grammar_states or {},
            get_max_grammar_per_exercise(),
            get_review_mode_exercise_limit(),
        )
        cn_to_ja_count = len(cn_groups)
        ja_to_cn_count = len(ja_groups)
    else:
        cn_groups = build_grammar_groups(
            entries,
            f"{date}:cn_to_ja",
            recent_grammar_titles or set(),
            cn_to_ja_count,
            grammar_states or {},
            get_max_grammar_per_exercise(),
            weighted=False,
        )
        used_titles = {entry.title for group in cn_groups for entry in group}
        remaining_entries = [entry for entry in entries if entry.title not in used_titles]
        ja_groups = build_grammar_groups(
            remaining_entries or entries,
            f"{date}:ja_to_cn",
            recent_grammar_titles or set(),
            ja_to_cn_count,
            grammar_states or {},
            get_max_grammar_per_exercise(),
            weighted=False,
        )
    grammar_groups = [*cn_groups, *ja_groups]
    selected = [entry for group in grammar_groups for entry in group]
    if tutor:
        exercise_set = generate_with_batches(
            tutor,
            date,
            vocabulary,
            cn_groups,
            ja_groups,
            mode,
        )
        exercise_set.generation_mode = mode
        return exercise_set

    return build_fallback_exercises(date, selected, vocabulary, cn_to_ja_count, ja_to_cn_count, grammar_groups, mode)


def generate_with_batches(
    tutor: Any,
    date: str,
    vocabulary: list[VocabularyEntry],
    cn_groups: list[list[GrammarEntry]],
    ja_groups: list[list[GrammarEntry]],
    generation_mode: str,
) -> ExerciseSet:
    if len(cn_groups) + len(ja_groups) <= AI_EXERCISE_BATCH_SIZE:
        selected = [entry for group in [*cn_groups, *ja_groups] for entry in group]
        return tutor.generate_exercises(date, selected, vocabulary, len(cn_groups), len(ja_groups), [*cn_groups, *ja_groups])

    batches: list[ExerciseSet] = []
    for group_batch in chunked(cn_groups, AI_EXERCISE_BATCH_SIZE):
        selected = [entry for group in group_batch for entry in group]
        batches.append(tutor.generate_exercises(date, selected, vocabulary, len(group_batch), 0, group_batch))
    for group_batch in chunked(ja_groups, AI_EXERCISE_BATCH_SIZE):
        selected = [entry for group in group_batch for entry in group]
        batches.append(tutor.generate_exercises(date, selected, vocabulary, 0, len(group_batch), group_batch))

    exercises: list[Exercise] = []
    notes_used: list[str] = []
    vocabulary_used: list[str] = []
    for batch in batches:
        for title in batch.notes_used:
            if title not in notes_used:
                notes_used.append(title)
        for word in batch.vocabulary_used or []:
            if word not in vocabulary_used:
                vocabulary_used.append(word)
        exercises.extend(batch.exercises)

    renumber_exercises(exercises)
    return ExerciseSet(
        date=date,
        notes_used=notes_used,
        vocabulary_used=vocabulary_used,
        exercises=exercises,
        generation_mode=generation_mode,
    )


def chunked(values: list[list[GrammarEntry]], size: int) -> list[list[list[GrammarEntry]]]:
    return [values[index : index + size] for index in range(0, len(values), max(1, size))]


def renumber_exercises(exercises: list[Exercise]) -> None:
    cn_index = 1
    ja_index = 1
    for exercise in exercises:
        if exercise.type == "translation_cn_to_ja":
            exercise.id = f"CJ{cn_index}"
            cn_index += 1
        elif exercise.type == "translation_ja_to_cn":
            exercise.id = f"JC{ja_index}"
            ja_index += 1


def build_grammar_groups(
    entries: list[GrammarEntry],
    date: str,
    recent_titles: set[str],
    exercise_count: int,
    grammar_states: dict[str, GrammarReviewState],
    max_per_exercise: int,
    weighted: bool = True,
) -> list[list[GrammarEntry]]:
    if exercise_count <= 0:
        return []

    group_sizes = difficulty_group_sizes(exercise_count, max_per_exercise)
    if weighted:
        selected = select_daily_entries_avoiding(
            entries,
            date,
            recent_titles,
            limit=sum(group_sizes),
            grammar_states=grammar_states,
        )
    else:
        selected = select_random_entries(entries, date, sum(group_sizes))
    groups: list[list[GrammarEntry]] = []
    cursor = 0
    for size in group_sizes:
        group = selected[cursor : cursor + size]
        if not group and selected:
            group = [selected[-1]]
        groups.append(group)
        cursor += size
    return groups


def build_review_mode_groups(
    entries: list[GrammarEntry],
    date: str,
    grammar_states: dict[str, GrammarReviewState],
    max_per_exercise: int,
    exercise_limit: int,
) -> tuple[list[list[GrammarEntry]], list[list[GrammarEntry]]]:
    if not entries:
        return [], []

    today = parse_date(date)
    target_entries = [
        entry
        for entry in entries
        if entry.title not in grammar_states or parse_date(grammar_states[entry.title].due) <= today
    ]
    if not target_entries:
        target_entries = select_daily_entries_avoiding(
            entries,
            f"{date}:review-fill",
            set(),
            limit=min(len(entries), max(2, max_per_exercise)),
            grammar_states=grammar_states,
        )

    ordered_targets = order_review_targets(target_entries, date, grammar_states)
    cn_groups, ja_groups, deferred_targets = build_limited_review_groups(
        ordered_targets,
        max_per_exercise,
        exercise_limit,
    )
    if deferred_targets:
        mark_grammar_due([entry.title for entry in deferred_targets], date)

    return cn_groups, ja_groups


def build_limited_review_groups(
    entries: list[GrammarEntry],
    max_per_exercise: int,
    exercise_limit: int,
) -> tuple[list[list[GrammarEntry]], list[list[GrammarEntry]], list[GrammarEntry]]:
    if not entries:
        return [], [], []
    if exercise_limit <= 0:
        cn_targets, ja_targets = split_targets_by_type(entries)
        return (
            pack_entries_with_gradient(cn_targets, max_per_exercise),
            pack_entries_with_gradient(ja_targets, max_per_exercise),
            [],
        )

    cn_exercise_limit = (exercise_limit + 1) // 2
    ja_exercise_limit = exercise_limit // 2
    cn_sizes = difficulty_group_sizes(cn_exercise_limit, max_per_exercise) if cn_exercise_limit else []
    ja_sizes = difficulty_group_sizes(ja_exercise_limit, max_per_exercise) if ja_exercise_limit else []
    capacity = sum(cn_sizes) + sum(ja_sizes)
    selected = entries[:capacity]
    deferred = entries[capacity:]

    if not selected:
        return [], [], deferred

    midpoint = (len(selected) + 1) // 2 if ja_sizes else len(selected)
    cn_targets = selected[:midpoint]
    ja_targets = selected[midpoint:]
    cn_groups = pack_entries_with_sizes(cn_targets, cn_sizes)
    ja_groups = pack_entries_with_sizes(ja_targets, ja_sizes)
    return cn_groups, ja_groups, deferred


def pack_entries_with_sizes(entries: list[GrammarEntry], group_sizes: list[int]) -> list[list[GrammarEntry]]:
    if not entries or not group_sizes:
        return []

    groups: list[list[GrammarEntry]] = []
    cursor = 0
    for size in group_sizes:
        group = entries[cursor : cursor + size]
        if group:
            groups.append(group)
        cursor += size
        if cursor >= len(entries):
            break
    return groups


def order_review_targets(
    entries: list[GrammarEntry],
    date: str,
    grammar_states: dict[str, GrammarReviewState],
) -> list[GrammarEntry]:
    today = parse_date(date)
    rng = random.Random(f"{date}:review-order")

    def priority(entry: GrammarEntry) -> tuple[float, float]:
        state = grammar_states.get(entry.title)
        if state is None:
            return (1000.0, rng.random())
        due_date = parse_date(state.due)
        overdue_days = (today - due_date).days
        low_score = 100 - state.last_score if state.last_score is not None else 0
        return (overdue_days * 10 + state.lapses * 4 + low_score / 10, rng.random())

    return sorted(entries, key=priority, reverse=True)


def split_targets_by_type(entries: list[GrammarEntry]) -> tuple[list[GrammarEntry], list[GrammarEntry]]:
    midpoint = (len(entries) + 1) // 2
    return entries[:midpoint], entries[midpoint:]


def pack_entries_with_gradient(entries: list[GrammarEntry], max_per_exercise: int) -> list[list[GrammarEntry]]:
    if not entries:
        return []

    exercise_count = 1
    while sum(difficulty_group_sizes(exercise_count, max_per_exercise)) < len(entries):
        exercise_count += 1

    groups: list[list[GrammarEntry]] = []
    cursor = 0
    for size in difficulty_group_sizes(exercise_count, max_per_exercise):
        group = entries[cursor : cursor + size]
        if group:
            groups.append(group)
        cursor += size
    if cursor < len(entries):
        groups.append(entries[cursor:])
    return groups


def select_random_entries(entries: list[GrammarEntry], date: str, limit: int) -> list[GrammarEntry]:
    if not entries or limit <= 0:
        return []
    rng = random.Random(date)
    shuffled = entries[:]
    rng.shuffle(shuffled)
    return shuffled[:limit]


def difficulty_group_sizes(exercise_count: int, max_per_exercise: int) -> list[int]:
    max_size = max(1, max_per_exercise)
    if exercise_count == 1:
        return [1]

    sizes: list[int] = []
    for index in range(exercise_count):
        ratio = index / max(1, exercise_count - 1)
        size = 1 + round(ratio * (max_size - 1))
        sizes.append(max(1, min(max_size, size)))
    return sizes


def build_fallback_exercises(
    date: str,
    entries: list[GrammarEntry],
    vocabulary: list[VocabularyEntry],
    cn_to_ja_count: int,
    ja_to_cn_count: int,
    grammar_groups: list[list[GrammarEntry]] | None = None,
    generation_mode: str = GENERATION_MODE_RANDOM,
) -> ExerciseSet:
    exercises: list[Exercise] = []
    selected_titles = [entry.title for entry in entries]
    vocabulary_words = [entry.compact for entry in vocabulary]
    groups = grammar_groups or [[entry] for entry in entries]

    for index, group in enumerate(groups[:cn_to_ja_count], start=1):
        entry = group[0]
        grammar_titles = [item.title for item in group]
        vocab = vocabulary[(index - 1) % len(vocabulary)] if vocabulary else None
        fallback_word = vocab.word if vocab else "日本料理"
        fallback_meaning = vocab.meaning if vocab and vocab.meaning else fallback_word
        exercises.append(
            Exercise(
                id=f"CJ{index}",
                type="translation_cn_to_ja",
                prompt=f"请翻译成日语：我想稍微谈一谈{fallback_meaning}。",
                grammar_focus=format_grammar_focus(grammar_titles),
                reference_answer=f"{fallback_word}について少し話したいです。",
                hint=build_hint(group, [fallback_word]),
                vocabulary_focus=[vocab.compact if vocab else fallback_word],
                answer_explanation=(
                    f"参考答案应使用这些语法：{format_grammar_focus(grammar_titles)}，并使用词汇「{fallback_word}」。"
                ),
                grammar_focuses=grammar_titles,
                difficulty=len(grammar_titles),
            )
        )

    offset = len(exercises)
    for index, group in enumerate(groups[cn_to_ja_count : cn_to_ja_count + ja_to_cn_count], start=1):
        entry = group[0]
        grammar_titles = [item.title for item in group]
        vocab_index = cn_to_ja_count + index - 1
        vocab = vocabulary[vocab_index % len(vocabulary)] if vocabulary else None
        fallback_word = vocab.word if vocab else "日本料理"
        fallback_meaning = vocab.meaning if vocab and vocab.meaning else fallback_word
        exercises.append(
            Exercise(
                id=f"JC{index}",
                type="translation_ja_to_cn",
                prompt=f"请翻译成中文：{fallback_word}について少し話したいです。",
                grammar_focus=format_grammar_focus(grammar_titles),
                reference_answer=f"我想稍微谈一谈{fallback_meaning}。",
                hint=build_hint(group, [fallback_word]),
                vocabulary_focus=[vocab.compact if vocab else fallback_word],
                answer_explanation=(
                    f"日语原句应体现这些语法：{format_grammar_focus(grammar_titles)}，并使用词汇「{fallback_word}」。"
                ),
                grammar_focuses=grammar_titles,
                difficulty=len(grammar_titles),
            )
        )

    return ExerciseSet(
        date=date,
        notes_used=selected_titles,
        vocabulary_used=vocabulary_words,
        exercises=exercises[: offset + ja_to_cn_count],
        generation_mode=generation_mode,
    )


def parse_exercise_json(
    raw: str,
    date: str,
    fallback_titles: list[str],
    fallback_groups: list[list[GrammarEntry]] | None = None,
) -> ExerciseSet:
    payload = json.loads(raw)
    exercises = normalize_exercise_sequence(
        [Exercise(**normalize_exercise_payload(item)) for item in payload["exercises"]],
        fallback_titles,
    )
    if fallback_groups:
        apply_planned_grammar_groups(exercises, fallback_groups)
    notes_used = payload.get("notes_used") or fallback_titles
    if fallback_groups:
        notes_used = [entry.title for group in fallback_groups for entry in group]
    vocabulary_used = list(payload.get("vocabulary_used", []))
    return ExerciseSet(
        date=payload.get("date", date),
        notes_used=notes_used,
        vocabulary_used=vocabulary_used,
        exercises=exercises,
        generation_mode=normalize_generation_mode(payload.get("generation_mode")),
    )


def apply_planned_grammar_groups(exercises: list[Exercise], fallback_groups: list[list[GrammarEntry]]) -> None:
    for exercise, group in zip(exercises, fallback_groups):
        grammar_titles = [entry.title for entry in group]
        if not grammar_titles:
            continue
        exercise.grammar_focuses = grammar_titles
        exercise.grammar_focus = format_grammar_focus(grammar_titles)
        exercise.difficulty = len(grammar_titles)


def normalize_generation_mode(value: Any) -> str:
    mode = str(value or GENERATION_MODE_RANDOM)
    return mode if mode in GENERATION_MODES else GENERATION_MODE_RANDOM


def build_hint(entries: GrammarEntry | list[GrammarEntry], vocabulary: list[str]) -> str:
    entry_list = entries if isinstance(entries, list) else [entries]
    parts = [f"语法：{format_grammar_focus([entry.title for entry in entry_list])}"]
    for entry in entry_list:
        if entry.content:
            parts.append(f"说明：{entry.title}: {entry.content.splitlines()[0]}")
    if vocabulary:
        parts.append(f"单词：{', '.join(vocabulary)}")
    return "\n".join(parts)


def normalize_exercise_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("hint", "")
    normalized.setdefault("vocabulary_focus", [])
    normalized.setdefault("answer_explanation", "")
    if "grammar_focuses" not in normalized:
        normalized["grammar_focuses"] = split_grammar_focus(normalized.get("grammar_focus", ""))
    normalized.setdefault("difficulty", max(1, len(normalized.get("grammar_focuses") or [])))
    return normalized


def normalize_exercise_sequence(exercises: list[Exercise], fallback_titles: list[str]) -> list[Exercise]:
    used: set[str] = set()
    fallback_iter = iter(fallback_titles)
    normalized: list[Exercise] = []

    for exercise in exercises:
        grammars = matching_titles(exercise.grammar_focuses or [exercise.grammar_focus], fallback_titles)
        if not grammars:
            grammar = next_unused_title(fallback_iter, used)
            grammars = [grammar] if grammar else []
        unique_grammars = []
        for grammar in grammars:
            if grammar and grammar not in unique_grammars:
                unique_grammars.append(grammar)
                used.add(grammar)
        if unique_grammars:
            exercise.grammar_focuses = unique_grammars
            exercise.grammar_focus = format_grammar_focus(unique_grammars)
            exercise.difficulty = max(1, len(unique_grammars))
        normalized.append(exercise)
    return normalized


def matching_titles(values: list[str], titles: list[str]) -> list[str]:
    matched: list[str] = []
    for value in values:
        title = first_matching_title(value, titles)
        if title and title not in matched:
            matched.append(title)
    return matched


def first_matching_title(value: str, titles: list[str]) -> str:
    stripped = value.strip()
    if stripped in titles:
        return stripped
    for title in titles:
        if title and title in stripped:
            return title
    return ""


def split_grammar_focus(value: str) -> list[str]:
    if not value:
        return []
    parts = [value]
    for separator in (";", "；", "、", ",", "，"):
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(part.split(separator))
        parts = next_parts
    return [part.strip() for part in parts if part.strip()]


def format_grammar_focus(titles: list[str]) -> str:
    return " + ".join(titles)


def next_unused_title(title_iter: Any, used: set[str]) -> str:
    for title in title_iter:
        if title not in used:
            return title
    return ""


def weighted_choice_index(weights: list[float], rng: random.Random) -> int:
    total = sum(weights)
    if total <= 0:
        return rng.randrange(len(weights))
    threshold = rng.random() * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if cumulative >= threshold:
            return index
    return len(weights) - 1
