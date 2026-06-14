from __future__ import annotations

import os
from pathlib import Path


DEFAULT_NOTES_DIR = Path(
    "/Users/stardustor/Library/CloudStorage/OneDrive-个人/obsidian-doc/日本語を勉強します"
)
DEFAULT_MODEL = "gpt-4.1-mini"
DATA_DIR = Path("data")
DEFAULT_ANKI_CONNECT_URL = "http://127.0.0.1:8765"
DEFAULT_ANKI_QUERY = ""
DEFAULT_ANKI_WORD_FIELDS = ("Expression", "Word", "Vocabulary", "Front")
DEFAULT_ANKI_READING_FIELDS = ("Reading", "Kana")
DEFAULT_ANKI_MEANING_FIELDS = ("Meaning", "Back", "中文", "Chinese")
DEFAULT_CN_TO_JA_COUNT = 3
DEFAULT_JA_TO_CN_COUNT = 2
DEFAULT_MAX_GRAMMAR_PER_EXERCISE = 3


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_notes_dir(cli_value: str | None = None) -> Path:
    if cli_value:
        return Path(cli_value).expanduser()

    env_value = os.getenv("JAPANESE_AGENT_NOTES_DIR")
    if env_value:
        return Path(env_value).expanduser()

    return DEFAULT_NOTES_DIR


def get_model(cli_value: str | None = None) -> str:
    return cli_value or os.getenv("JAPANESE_AGENT_MODEL") or DEFAULT_MODEL


def get_anki_connect_url() -> str:
    return os.getenv("JAPANESE_AGENT_ANKI_CONNECT_URL") or DEFAULT_ANKI_CONNECT_URL


def get_anki_query() -> str:
    return os.getenv("JAPANESE_AGENT_ANKI_QUERY") or DEFAULT_ANKI_QUERY


def get_anki_limit() -> int:
    raw_value = os.getenv("JAPANESE_AGENT_ANKI_LIMIT", "30")
    try:
        return max(0, int(raw_value))
    except ValueError:
        return 80


def get_anki_enabled() -> bool:
    return os.getenv("JAPANESE_AGENT_ANKI_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def get_field_names(env_name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(env_name)
    if not raw_value:
        return defaults
    return tuple(value.strip() for value in raw_value.split(",") if value.strip())


def get_int_env(env_name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.getenv(env_name, str(default))
    try:
        return max(minimum, int(raw_value))
    except ValueError:
        return default


def get_default_cn_to_ja_count() -> int:
    return get_int_env("JAPANESE_AGENT_CN_TO_JA_COUNT", DEFAULT_CN_TO_JA_COUNT)


def get_default_ja_to_cn_count() -> int:
    return get_int_env("JAPANESE_AGENT_JA_TO_CN_COUNT", DEFAULT_JA_TO_CN_COUNT)


def get_max_grammar_per_exercise() -> int:
    return get_int_env("JAPANESE_AGENT_MAX_GRAMMAR_PER_EXERCISE", DEFAULT_MAX_GRAMMAR_PER_EXERCISE, minimum=1)
