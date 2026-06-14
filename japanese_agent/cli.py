from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

from .app_core import load_practice_state
from .config import get_default_cn_to_ja_count, get_default_ja_to_cn_count, get_notes_dir, load_dotenv
from .anki import invoke_anki, load_anki_vocabulary
from .exercises import ExerciseSet
from .grammar_srs import load_grammar_srs, update_grammar_review
from .notes import load_entries
from .openai_client import JapaneseTutorClient, exercise_to_dict, fallback_grade
from .session import save_session


def main() -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list-notes":
        list_notes(args)
    elif args.command == "anki-decks":
        anki_decks()
    elif args.command == "anki-vocab":
        anki_vocab(args)
    elif args.command == "grammar-srs":
        grammar_srs(args)
    elif args.command == "practice":
        practice(args)
    else:
        parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Daily Japanese practice agent.")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list-notes", help="List parsed grammar entries.")
    add_common_args(list_parser)

    anki_parser = subparsers.add_parser("anki-vocab", help="List vocabulary loaded from Anki.")
    anki_parser.add_argument("--date", default=date.today().isoformat(), help="Date used for deterministic sampling.")
    anki_parser.add_argument("--limit", type=int, default=None, help="Maximum number of Anki vocabulary entries.")

    subparsers.add_parser("anki-decks", help="List Anki deck names through AnkiConnect.")

    srs_parser = subparsers.add_parser("grammar-srs", help="List grammar review states.")
    srs_parser.add_argument("--limit", type=int, default=20, help="Maximum number of grammar states to show.")

    practice_parser = subparsers.add_parser("practice", help="Generate and grade daily practice.")
    add_common_args(practice_parser)
    practice_parser.add_argument("--date", default=date.today().isoformat(), help="Practice date, YYYY-MM-DD.")
    practice_parser.add_argument(
        "--cn-to-ja-count",
        "--translation-count",
        dest="cn_to_ja_count",
        type=int,
        default=get_default_cn_to_ja_count(),
        help="Number of Chinese-to-Japanese exercises.",
    )
    practice_parser.add_argument(
        "--ja-to-cn-count",
        "--sentence-count",
        dest="ja_to_cn_count",
        type=int,
        default=get_default_ja_to_cn_count(),
        help="Number of Japanese-to-Chinese exercises.",
    )
    practice_parser.add_argument("--regenerate", action="store_true", help="Regenerate exercises for the date.")
    practice_parser.add_argument("--model", default=None, help="OpenAI model name.")

    return parser


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--notes-dir", default=None, help="Directory containing Markdown notes.")


def list_notes(args: argparse.Namespace) -> None:
    notes_dir = get_notes_dir(args.notes_dir)
    entries = load_entries(notes_dir)
    print(f"Notes directory: {notes_dir}")
    print(f"Parsed entries: {len(entries)}")
    for index, entry in enumerate(entries, start=1):
        preview = " ".join(entry.content.split())[:90]
        print(f"{index:02d}. [{entry.source}] {entry.title} - {preview}")


def anki_vocab(args: argparse.Namespace) -> None:
    vocabulary, status = load_anki_vocabulary(args.date, args.limit)
    print(status)
    for index, entry in enumerate(vocabulary, start=1):
        print(f"{index:02d}. {entry.compact}")


def anki_decks() -> None:
    decks = invoke_anki("deckNames", {})
    for deck in decks:
        print(deck)


def grammar_srs(args: argparse.Namespace) -> None:
    states = sorted(load_grammar_srs().values(), key=lambda state: (state.due or "", -state.lapses))
    if not states:
        print("No grammar review records yet.")
        return
    for state in states[: args.limit]:
        print(
            f"{state.title} | due={state.due or '-'} | interval={state.interval_days}d "
            f"| reps={state.reps} | lapses={state.lapses} | last={state.last_score}"
        )


def practice(args: argparse.Namespace) -> None:
    try:
        state = load_practice_state(
            date_value=args.date,
            notes_dir_value=args.notes_dir,
            model=args.model,
            cn_to_ja_count=args.cn_to_ja_count,
            ja_to_cn_count=args.ja_to_cn_count,
            regenerate=args.regenerate,
        )
    except RuntimeError as error:
        raise SystemExit(str(error)) from error

    if state.used_existing:
        print(f"Loaded existing session for {args.date}. Use --regenerate to create a new one.")
    elif not args.regenerate and state.regenerated:
        print("Created a new session for today.")

    if state.tutor is None:
        print("OPENAI_API_KEY is not set. Running in local fallback mode.")
    print(f"Vocabulary: {state.vocabulary_status}")

    print_header(args.date, state.notes_dir, state.exercise_set, state.tutor is not None)
    run_interactive_practice(args.date, state.exercise_set, state.answers, state.tutor)


def print_header(date_value: str, notes_dir: Path, exercise_set: ExerciseSet, has_ai: bool) -> None:
    mode = "AI grading" if has_ai else "local fallback"
    print("")
    print(f"JapaneseAgent - {date_value} ({mode})")
    print(f"Notes: {notes_dir}")
    print("Grammar focus:")
    for title in exercise_set.notes_used:
        print(f"- {title}")
    print("")
    print("输入答案后按回车。输入 :hint 看提示，:skip 跳过，:quit 退出。")
    print("")


def run_interactive_practice(
    date_value: str,
    exercise_set: ExerciseSet,
    answers: list[dict[str, Any]],
    tutor: JapaneseTutorClient | None,
) -> None:
    answered_ids = {item["exercise_id"] for item in answers}

    for exercise in exercise_set.exercises:
        if exercise.id in answered_ids:
            continue

        print(f"[{exercise.id}] {label_for_type(exercise.type)}")
        print(exercise.prompt)
        while True:
            answer = input("> ").strip()
            if answer == ":quit":
                save_session(date_value, exercise_set, answers)
                print("已保存进度。")
                return
            if answer == ":hint":
                print(build_focus_text(exercise))
                continue
            if answer == ":skip":
                print(f"参考答案：{exercise.reference_answer}")
                print("")
                break
            if not answer:
                print("可以输入答案，或者用 :skip 跳过。")
                continue

            exercise_payload = exercise_to_dict(exercise)
            grade = tutor.grade_answer(exercise_payload, answer) if tutor else fallback_grade(exercise_payload, answer)
            print_grade(grade)
            for grammar in exercise.grammar_focuses or [exercise.grammar_focus]:
                if grammar:
                    update_grammar_review(grammar, int(grade.get("score", 0)), date_value)
            answers.append(
                {
                    "exercise_id": exercise.id,
                    "answer": answer,
                    "grade": grade,
                    "review_recorded": True,
                    "exercise_snapshot": exercise_to_dict(exercise),
                }
            )
            save_session(date_value, exercise_set, answers)
            print("")
            break

    print("今天的练习完成了。记录已保存。")


def label_for_type(exercise_type: str) -> str:
    if exercise_type == "translation_cn_to_ja":
        return "中译日"
    if exercise_type == "translation_ja_to_cn":
        return "日译中"
    return exercise_type


def print_grade(grade: dict[str, Any]) -> None:
    print(f"得分：{grade.get('score', '?')}/100")
    print(f"参考答案：{grade.get('corrected_answer', '')}")
    print(f"解释：{grade.get('explanation', '')}")
    notes = grade.get("grammar_notes") or []
    for note in notes:
        print(f"- {note}")
    encouragement = grade.get("encouragement")
    if encouragement:
        print(encouragement)


def build_focus_text(exercise: Any) -> str:
    lines = [f"难度：{exercise.difficulty}", f"涉及语法：{exercise.grammar_focus}"]
    vocabulary = exercise.vocabulary_focus or []
    if vocabulary:
        lines.append("涉及单词：")
        lines.extend(f"- {word}" for word in vocabulary)
    if exercise.hint:
        lines.extend(["", f"提示：{exercise.hint}"])
    return "\n".join(lines)
