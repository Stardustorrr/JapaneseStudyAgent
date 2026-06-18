from __future__ import annotations

from dataclasses import asdict
import json
import os
from typing import Any

from .anki import VocabularyEntry
from .exercises import ExerciseSet, parse_exercise_json
from .notes import GrammarEntry


SYSTEM_PROMPT = """你是一位严格但鼓励人的日语老师。
目标学习者是中文母语者，水平约 N5-N4。
所有题目必须只使用学习者已经学过的语法点，并尽量使用 JLPT N4/N5 常见词汇。
输出和批改解释使用中文，日语句子保留自然日语。"""


class JapaneseTutorClient:
    def __init__(self, model: str) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set")

        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=60.0, max_retries=2)
        self.model = model

    def generate_exercises(
        self,
        date: str,
        entries: list[GrammarEntry],
        vocabulary: list[VocabularyEntry],
        cn_to_ja_count: int,
        ja_to_cn_count: int,
        grammar_groups: list[list[GrammarEntry]] | None = None,
    ) -> ExerciseSet:
        fallback_titles = [entry.title for entry in entries]
        groups = grammar_groups or [[entry] for entry in entries]
        notes = "\n\n".join(
            f"[{index}] {entry.title}\n来源：{entry.source}\n{entry.content}"
            for index, entry in enumerate(entries, start=1)
        )
        group_plan = "\n".join(
            f"- 第{index}题 难度{len(group)} 使用语法：{'; '.join(entry.title for entry in group)}"
            for index, group in enumerate(groups, start=1)
        )
        words = "\n".join(f"- {entry.compact}" for entry in vocabulary[:30]) or "未配置 Anki 词汇池。请只使用 N4/N5 常见词。"
        user_prompt = f"""请根据这些已学语法笔记生成今天的练习。

日期：{date}
中译日题数量：{cn_to_ja_count}
日译中题数量：{ja_to_cn_count}

要求：
- 必须生成 exactly {cn_to_ja_count + ja_to_cn_count} 道题。
- 必须严格按照“题目难度与语法组合计划”生成，每题使用计划中列出的全部语法。
- 难度等于该题 grammar_focuses 的数量；中译日题内部按难度递增，日译中题内部也按难度递增。
- grammar_focuses 必须是数组，逐项填写该题使用的所有语法标题。
- grammar_focus 是 grammar_focuses 用“ + ”连接后的展示字符串。
- 不要自行创造“无特殊句型”等标题。
- notes_used 必须等于今天实际使用过的全部语法标题列表，且不得重复。
- 中译日题给中文句子，让学习者翻译成自然日语。
- 日译中题给日语句子，让学习者翻译成中文，并理解目标语法在句中的作用。
- 优先使用“Anki 已学词汇”里的单词；如果数量不足，再补充 JLPT N4/N5 常见词。
- Anki 已学词汇已按复习优先级排序，靠前的词更急需复习或曾经遗忘，请优先使用靠前词汇。
- 每道题尽量使用 1-3 个 Anki 词汇，不要为了塞词牺牲自然度。
- prompt 里不要直接写“使用某语法/某单词/说明某语法作用”等提示；题干默认必须隐藏考点。
- grammar_focuses、grammar_focus 和 vocabulary_focus 用于隐藏提示，必须准确填写。
- reference_answer 必须在生成题目时一并生成，且必须实际使用 grammar_focuses 标注的全部语法和 vocabulary_focus 标注的词汇。
- answer_explanation 用中文逐项说明 reference_answer 中哪一部分体现了 grammar_focuses 的每个语法，以及用了哪些 vocabulary_focus。
- 生成每道题后自检：如果 reference_answer 没有自然使用全部标注语法或标注词汇，必须改题目或改答案，直到一致。
- 日译中题的 prompt 中的日语原句本身必须实际使用 grammar_focuses 和 vocabulary_focus；reference_answer 是该日语原句的中文答案。
- hint 显示给学习者点击“提示”时看，可以包含语法名、语法说明和涉及单词，但不要泄露完整答案。
- 只使用 JSON 输出，不要 Markdown。

JSON 结构：
{{
  "date": "YYYY-MM-DD",
  "notes_used": ["语法点标题"],
  "vocabulary_used": ["单词 - 意思"],
  "exercises": [
    {{
      "id": "CJ1 或 JC1",
      "type": "translation_cn_to_ja 或 translation_ja_to_cn",
      "prompt": "题目",
      "grammar_focus": "语法1 + 语法2",
      "grammar_focuses": ["语法1", "语法2"],
      "difficulty": 2,
      "vocabulary_focus": ["单词 - 意思"],
      "reference_answer": "参考答案",
      "answer_explanation": "说明参考答案如何使用目标语法和目标词汇",
      "hint": "提示"
    }}
  ]
}}

已学笔记：
{notes}

题目难度与语法组合计划：
{group_plan}

Anki 已学词汇：
{words}
"""
        raw = self._complete_json(user_prompt)
        return parse_exercise_json(raw, date, fallback_titles, groups)

    def grade_answer(self, exercise: dict[str, Any], answer: str) -> dict[str, Any]:
        user_prompt = f"""请批改学习者的答案。

题目：
{json.dumps(exercise, ensure_ascii=False)}

出题时生成的参考答案：
{exercise.get("reference_answer", "")}

参考答案与考点说明：
{exercise.get("answer_explanation", "")}

学习者答案：
{answer}

请以题干含义、学习者答案本身的正确性、自然度和参考答案作为主要基准批改。
参考答案与考点说明用于理解出题意图，但提示中的 grammar_focuses/grammar_focus 和 vocabulary_focus 是隐藏提示，不是强制作答条件。
如果是中译日题，请判断学习者答案是否表达了题干含义、日语是否自然、语法/助词/动词变形是否正确。学习者没有使用全部 grammar_focuses 或 vocabulary_focus 时，不要仅因此判错或大幅扣分；如果答案正确自然，仍然可以给高分或满分。
如果学习者自然地使用了目标语法或目标词汇，请在解释中肯定；如果没有使用，可以温和说明参考答案使用了哪些语法/词汇，作为拓展学习。题目难度由 grammar_focuses 数量决定。
如果是日译中题，请判断中文意思是否准确，并解释目标语法在日语原句中的作用。
不要另写“修改后答案”或“更自然说法”；需要展示答案时，直接展示出题时生成的参考答案。
只输出 JSON，不要 Markdown。

JSON 结构：
{{
  "score": 0-100,
  "is_correct": true/false,
  "corrected_answer": "直接填写出题时生成的参考答案；不要根据学习者答案另写修改句",
  "explanation": "中文解释",
  "grammar_notes": ["要点1", "要点2"],
  "encouragement": "一句鼓励"
}}
"""
        raw = self._complete_json(user_prompt)
        return json.loads(raw)

    def _complete_json(self, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned an empty response")
        return content


def fallback_grade(exercise: dict[str, Any], answer: str) -> dict[str, Any]:
    reference = exercise.get("reference_answer", "")
    has_answer = bool(answer.strip())
    score = 50 if has_answer else 0
    if has_answer and answer.strip() == reference.strip():
        score = 100

    return {
        "score": score,
        "is_correct": score >= 80,
        "corrected_answer": reference,
        "explanation": "当前没有配置 OPENAI_API_KEY，只能进行本地占位批改。配置 API key 后会给出具体语法分析。",
        "grammar_notes": [f"本题关注：{exercise.get('grammar_focus', '')}"],
        "encouragement": "先把答案写出来就很好，接下来可以接入 AI 批改看细节。",
    }


def exercise_to_dict(exercise: Any) -> dict[str, Any]:
    if hasattr(exercise, "__dataclass_fields__"):
        return asdict(exercise)
    return dict(exercise)
