from __future__ import annotations

import argparse
from datetime import date
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Any

from .app_core import PracticeState, load_practice_state
from .config import get_default_cn_to_ja_count, get_default_ja_to_cn_count, load_dotenv
from .exercises import GENERATION_MODE_RANDOM, GENERATION_MODE_REVIEW
from .grammar_srs import load_grammar_srs, parse_date, update_grammar_review
from .notes import load_entries
from .openai_client import exercise_to_dict, fallback_grade
from .session import save_session


class JapaneseAgentApp(tk.Tk):
    def __init__(
        self,
        cn_to_ja_count: int | None = None,
        ja_to_cn_count: int | None = None,
        regenerate: bool = False,
    ) -> None:
        super().__init__()
        self.title("JapaneseAgent")
        self.geometry("980x680")
        self.minsize(860, 580)

        self.state_data: PracticeState | None = None
        self.current_index = 0
        self.cn_to_ja_count = cn_to_ja_count if cn_to_ja_count is not None else get_default_cn_to_ja_count()
        self.ja_to_cn_count = ja_to_cn_count if ja_to_cn_count is not None else get_default_ja_to_cn_count()
        self.generation_mode = GENERATION_MODE_REVIEW
        self.loading = False

        self._build_styles()
        self._build_layout()
        self.after(0, lambda: self.ask_generation_mode(regenerate=True))

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f7f7f4")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f7f7f4", foreground="#222222")
        style.configure("Panel.TLabel", background="#ffffff", foreground="#222222")
        style.configure("Muted.TLabel", background="#ffffff", foreground="#666666")
        style.configure("Title.TLabel", background="#ffffff", foreground="#111111", font=("Helvetica", 18, "bold"))
        style.configure("Badge.TLabel", background="#e8f0fe", foreground="#174ea6", padding=(8, 3))
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", padding=(12, 7))

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(18, 14, 18, 10))
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="JapaneseAgent", font=("Helvetica", 20, "bold")).grid(row=0, column=0, sticky="w")
        self.status_var = tk.StringVar(value="正在加载...")
        ttk.Label(header, textvariable=self.status_var).grid(row=0, column=1, sticky="e")

        sidebar = ttk.Frame(self, padding=(14, 12), width=240)
        sidebar.grid(row=1, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.rowconfigure(2, weight=1)

        ttk.Label(sidebar, text="今日题目", font=("Helvetica", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.progress_var = tk.StringVar(value="请选择生成模式")
        ttk.Label(sidebar, textvariable=self.progress_var).grid(row=1, column=0, sticky="w", pady=(4, 10))

        self.exercise_list = tk.Listbox(sidebar, width=26, height=18, activestyle="none", exportselection=False)
        self.exercise_list.grid(row=2, column=0, sticky="nsew")
        self.exercise_list.bind("<<ListboxSelect>>", self.on_select_exercise)

        sidebar_buttons = ttk.Frame(sidebar)
        sidebar_buttons.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        sidebar_buttons.columnconfigure(0, weight=1)
        count_frame = ttk.Frame(sidebar_buttons)
        count_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        count_frame.columnconfigure(1, weight=1)
        count_frame.columnconfigure(3, weight=1)
        ttk.Label(count_frame, text="中译日").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.cn_to_ja_var = tk.IntVar(value=self.cn_to_ja_count)
        self.cn_to_ja_spinbox = ttk.Spinbox(count_frame, from_=0, to=20, width=4, textvariable=self.cn_to_ja_var)
        self.cn_to_ja_spinbox.grid(row=0, column=1, sticky="ew")
        ttk.Label(count_frame, text="日译中").grid(row=0, column=2, sticky="w", padx=(8, 4))
        self.ja_to_cn_var = tk.IntVar(value=self.ja_to_cn_count)
        self.ja_to_cn_spinbox = ttk.Spinbox(count_frame, from_=0, to=20, width=4, textvariable=self.ja_to_cn_var)
        self.ja_to_cn_spinbox.grid(row=0, column=3, sticky="ew")

        self.regenerate_button = ttk.Button(sidebar_buttons, text="按数量重新生成", command=self.regenerate_session)
        self.regenerate_button.grid(row=1, column=0, sticky="ew")
        self.grammar_status_button = ttk.Button(sidebar_buttons, text="语法复习状态", command=self.show_grammar_status)
        self.grammar_status_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.change_mode_button = ttk.Button(sidebar_buttons, text="更换生成模式", command=self.ask_generation_mode)
        self.change_mode_button.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        main_panel = ttk.Frame(self, style="Panel.TFrame", padding=(22, 20))
        main_panel.grid(row=1, column=1, sticky="nsew", padx=(0, 18), pady=(0, 18))
        main_panel.columnconfigure(0, weight=1)
        main_panel.rowconfigure(3, weight=1)
        main_panel.rowconfigure(6, weight=1)

        top_line = ttk.Frame(main_panel, style="Panel.TFrame")
        top_line.grid(row=0, column=0, sticky="ew")
        top_line.columnconfigure(1, weight=1)
        self.type_var = tk.StringVar(value="")
        self.grammar_var = tk.StringVar(value="")
        ttk.Label(top_line, textvariable=self.type_var, style="Badge.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(top_line, textvariable=self.grammar_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        self.prompt_var = tk.StringVar(value="")
        ttk.Label(main_panel, textvariable=self.prompt_var, style="Title.TLabel", wraplength=680, justify="left").grid(
            row=1, column=0, sticky="ew", pady=(16, 12)
        )

        ttk.Label(main_panel, text="你的答案", style="Panel.TLabel", font=("Helvetica", 12, "bold")).grid(
            row=2, column=0, sticky="w"
        )
        self.answer_text = scrolledtext.ScrolledText(main_panel, height=7, wrap="word", font=("Helvetica", 14))
        self.answer_text.grid(row=3, column=0, sticky="nsew", pady=(6, 12))

        actions = ttk.Frame(main_panel, style="Panel.TFrame")
        actions.grid(row=4, column=0, sticky="ew", pady=(0, 14))
        actions.columnconfigure(4, weight=1)
        ttk.Button(actions, text="提示", command=self.show_hint).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="跳过", command=self.skip_current).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="上一题", command=self.previous_exercise).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(actions, text="下一题", command=self.next_exercise).grid(row=0, column=3, padx=(0, 8))
        self.submit_button = ttk.Button(actions, text="提交批改", style="Accent.TButton", command=self.submit_answer)
        self.submit_button.grid(row=0, column=5, sticky="e")

        ttk.Label(main_panel, text="批改与解释", style="Panel.TLabel", font=("Helvetica", 12, "bold")).grid(
            row=5, column=0, sticky="w"
        )
        self.result_text = scrolledtext.ScrolledText(main_panel, height=9, wrap="word", font=("Helvetica", 13))
        self.result_text.grid(row=6, column=0, sticky="nsew", pady=(6, 0))
        self.result_text.configure(state="disabled")
        self.set_controls_enabled(False)

    def ask_generation_mode(self, regenerate: bool = True) -> None:
        if self.loading:
            return

        dialog = tk.Toplevel(self)
        dialog.title("选择生成模式")
        dialog.geometry("460x300")
        dialog.minsize(420, 280)
        dialog.transient(self)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", self.destroy)

        container = ttk.Frame(dialog, padding=(22, 18))
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)

        ttk.Label(container, text="今天如何生成题目？", font=("Helvetica", 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            container,
            text="复习模式会自动覆盖所有未复习或今日到期的语法；随机模式使用你指定的题目数量。",
            wraplength=400,
        ).grid(row=1, column=0, sticky="ew", pady=(8, 16))

        def choose_review() -> None:
            self.generation_mode = GENERATION_MODE_REVIEW
            dialog.destroy()
            self.update_generation_mode_controls()
            self.load_session(regenerate=regenerate)

        ttk.Button(container, text="按语法复习情况生成", style="Accent.TButton", command=choose_review).grid(
            row=2, column=0, sticky="ew"
        )

        random_frame = ttk.Frame(container)
        random_frame.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        random_frame.columnconfigure(1, weight=1)
        random_frame.columnconfigure(3, weight=1)
        ttk.Label(random_frame, text="随机抽选语法", font=("Helvetica", 12, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        random_cn_var = tk.IntVar(value=self.cn_to_ja_count)
        random_ja_var = tk.IntVar(value=self.ja_to_cn_count)
        ttk.Label(random_frame, text="中译日").grid(row=1, column=0, sticky="w", padx=(0, 4))
        ttk.Spinbox(random_frame, from_=0, to=20, width=4, textvariable=random_cn_var).grid(row=1, column=1, sticky="ew")
        ttk.Label(random_frame, text="日译中").grid(row=1, column=2, sticky="w", padx=(10, 4))
        ttk.Spinbox(random_frame, from_=0, to=20, width=4, textvariable=random_ja_var).grid(row=1, column=3, sticky="ew")

        def choose_random() -> None:
            self.generation_mode = GENERATION_MODE_RANDOM
            self.cn_to_ja_count = max(0, int(random_cn_var.get()))
            self.ja_to_cn_count = max(0, int(random_ja_var.get()))
            self.cn_to_ja_var.set(self.cn_to_ja_count)
            self.ja_to_cn_var.set(self.ja_to_cn_count)
            dialog.destroy()
            self.update_generation_mode_controls()
            self.load_session(regenerate=regenerate)

        ttk.Button(container, text="按指定数量随机生成", command=choose_random).grid(row=4, column=0, sticky="ew", pady=(14, 0))

        self.wait_window(dialog)

    def update_generation_mode_controls(self) -> None:
        is_random = self.generation_mode == GENERATION_MODE_RANDOM
        mode_label = "随机抽选语法" if is_random else "按语法复习情况"
        button_label = "按数量重新生成" if is_random else "按复习状态重新生成"
        spinbox_state = "normal" if is_random else "disabled"
        self.regenerate_button.configure(text=button_label)
        self.cn_to_ja_spinbox.configure(state=spinbox_state)
        self.ja_to_cn_spinbox.configure(state=spinbox_state)
        if not self.state_data:
            self.progress_var.set(mode_label)

    def load_session(self, regenerate: bool = False, async_load: bool = True) -> None:
        if self.loading:
            return
        if async_load:
            self.loading = True
            self.set_loading_state("正在读取笔记并生成练习...")
            thread = threading.Thread(target=self._load_session_in_background, args=(regenerate,), daemon=True)
            thread.start()
            return

        self.status_var.set("正在读取笔记并生成练习...")
        self.update_idletasks()
        try:
            state = self.build_practice_state(regenerate)
        except Exception as error:
            messagebox.showerror("启动失败", str(error))
            self.status_var.set("启动失败")
            return

        self.apply_loaded_state(state)

    def _load_session_in_background(self, regenerate: bool) -> None:
        try:
            state = self.build_practice_state(regenerate)
            self.after(0, lambda: self.finish_loading(state))
        except Exception as error:
            self.after(0, lambda: self.fail_loading(str(error)))

    def build_practice_state(self, regenerate: bool) -> PracticeState:
        self.cn_to_ja_count = max(0, int(self.cn_to_ja_var.get()))
        self.ja_to_cn_count = max(0, int(self.ja_to_cn_var.get()))
        return load_practice_state(
            date_value=date.today().isoformat(),
            cn_to_ja_count=self.cn_to_ja_count,
            ja_to_cn_count=self.ja_to_cn_count,
            regenerate=regenerate,
            generation_mode=self.generation_mode,
        )

    def finish_loading(self, state: PracticeState) -> None:
        self.loading = False
        self.set_controls_enabled(True)
        self.apply_loaded_state(state)

    def fail_loading(self, message: str) -> None:
        self.loading = False
        self.set_controls_enabled(True)
        self.status_var.set("生成失败")
        messagebox.showerror("生成失败", message)

    def apply_loaded_state(self, state: PracticeState) -> None:
        self.state_data = state
        self.current_index = self.first_unanswered_index()
        self.refresh_exercise_list()
        self.show_current_exercise()
        mode = "AI 批改" if self.state_data.tutor else "本地占位批改"
        generation_mode = generation_mode_label(self.state_data.generation_mode)
        self.generation_mode = self.state_data.generation_mode
        self.update_generation_mode_controls()
        self.status_var.set(f"{self.state_data.date} · {generation_mode} · {mode} · {self.state_data.vocabulary_status}")

    def set_loading_state(self, message: str) -> None:
        self.status_var.set(message)
        self.set_controls_enabled(False)
        self.set_result(message)

    def set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.regenerate_button.configure(state=state)
        self.grammar_status_button.configure(state=state)
        self.change_mode_button.configure(state=state)
        self.submit_button.configure(state=state)

    def regenerate_session(self) -> None:
        confirmed = messagebox.askyesno(
            "重新生成",
            "这会用当前模式和最新笔记重新生成今天的题目。仍然匹配新题目的作答记录会被保留，已经写入的复习状态不会撤销。继续吗？",
        )
        if confirmed:
            self.load_session(regenerate=True)

    def show_grammar_status(self) -> None:
        window = tk.Toplevel(self)
        window.title("语法复习状态")
        window.geometry("960x560")
        window.minsize(820, 420)

        container = ttk.Frame(window, padding=(14, 12))
        container.pack(fill="both", expand=True)
        container.rowconfigure(1, weight=1)
        container.columnconfigure(0, weight=1)

        summary_var = tk.StringVar(value="")
        ttk.Label(container, textvariable=summary_var, font=("Helvetica", 13, "bold")).grid(row=0, column=0, sticky="w")

        columns = ("title", "status", "due", "interval", "reps", "lapses", "last_score", "last_reviewed")
        tree = ttk.Treeview(container, columns=columns, show="headings", height=18)
        headings = {
            "title": "语法",
            "status": "状态",
            "due": "到期日",
            "interval": "间隔",
            "reps": "次数",
            "lapses": "遗忘",
            "last_score": "最近分数",
            "last_reviewed": "最近复习",
        }
        widths = {
            "title": 310,
            "status": 90,
            "due": 110,
            "interval": 70,
            "reps": 60,
            "lapses": 60,
            "last_score": 80,
            "last_reviewed": 110,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")
        tree.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(10, 0))
        tree.configure(yscrollcommand=scrollbar.set)

        rows = self.build_grammar_status_rows()
        today = date.today()
        reviewed_count = 0
        due_count = 0
        for row in rows:
            tree.insert(
                "",
                "end",
                values=(
                    row["title"],
                    row["status"],
                    row["due"],
                    row["interval"],
                    row["reps"],
                    row["lapses"],
                    row["last_score"],
                    row["last_reviewed"],
                ),
            )
            if row["reviewed"]:
                reviewed_count += 1
            if row["due_sort"] <= today:
                due_count += 1
        summary_var.set(f"共 {len(rows)} 个语法，已复习 {reviewed_count} 个，当前到期 {due_count} 个")

        button_row = ttk.Frame(container)
        button_row.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(button_row, text="关闭", command=window.destroy).pack(side="right")

    def build_grammar_status_rows(self) -> list[dict[str, Any]]:
        states = load_grammar_srs()
        titles = set(states)
        if self.state_data:
            try:
                titles.update(entry.title for entry in load_entries(self.state_data.notes_dir))
            except Exception:
                pass

        today = date.today()
        rows: list[dict[str, Any]] = []
        for title in sorted(titles):
            state = states.get(title)
            if state is None:
                rows.append(
                    {
                        "title": title,
                        "status": "未复习",
                        "due": "-",
                        "interval": "-",
                        "reps": "0",
                        "lapses": "0",
                        "last_score": "-",
                        "last_reviewed": "-",
                        "reviewed": False,
                        "due_sort": today,
                    }
                )
                continue

            due_date = parse_date(state.due) if state.due else today
            if due_date <= today:
                status = "到期"
            elif state.last_score is not None and state.last_score < 80:
                status = "需巩固"
            else:
                status = "进行中"
            rows.append(
                {
                    "title": title,
                    "status": status,
                    "due": state.due or "-",
                    "interval": f"{state.interval_days}天" if state.interval_days else "-",
                    "reps": str(state.reps),
                    "lapses": str(state.lapses),
                    "last_score": "-" if state.last_score is None else str(state.last_score),
                    "last_reviewed": state.last_reviewed or "-",
                    "reviewed": True,
                    "due_sort": due_date,
                }
            )

        return sorted(rows, key=lambda row: (row["due_sort"], row["status"] == "未复习", row["title"]))

    def first_unanswered_index(self) -> int:
        if not self.state_data:
            return 0
        answered_ids = {item["exercise_id"] for item in self.state_data.answers}
        for index, exercise in enumerate(self.state_data.exercise_set.exercises):
            if exercise.id not in answered_ids:
                return index
        return 0

    def refresh_exercise_list(self) -> None:
        if not self.state_data:
            return
        self.exercise_list.delete(0, tk.END)
        answered_ids = {item["exercise_id"] for item in self.state_data.answers}
        for exercise in self.state_data.exercise_set.exercises:
            mark = "✓" if exercise.id in answered_ids else " "
            self.exercise_list.insert(tk.END, f"{mark} {exercise.id} {label_for_type(exercise.type)}")
        self.exercise_list.selection_clear(0, tk.END)
        self.exercise_list.selection_set(self.current_index)
        self.exercise_list.activate(self.current_index)
        self.update_progress()

    def update_progress(self) -> None:
        if not self.state_data:
            return
        total = len(self.state_data.exercise_set.exercises)
        done = len({item["exercise_id"] for item in self.state_data.answers})
        self.progress_var.set(f"{done}/{total} 已完成")

    def on_select_exercise(self, _event: tk.Event[Any]) -> None:
        selection = self.exercise_list.curselection()
        if not selection:
            return
        self.current_index = int(selection[0])
        self.show_current_exercise()

    def show_current_exercise(self) -> None:
        exercise = self.current_exercise()
        if not exercise:
            return

        self.type_var.set(label_for_type(exercise.type))
        self.grammar_var.set("")
        self.prompt_var.set(exercise.prompt)
        self.answer_text.delete("1.0", tk.END)
        self.set_result("")

        answer_record = self.answer_for_exercise(exercise.id)
        if answer_record:
            self.answer_text.insert("1.0", answer_record.get("answer", ""))
            self.show_grade(answer_record.get("grade", {}))
            self.submit_button.configure(text="更改答案")
        else:
            self.submit_button.configure(text="提交批改")

    def current_exercise(self) -> Any | None:
        if not self.state_data or not self.state_data.exercise_set.exercises:
            return None
        return self.state_data.exercise_set.exercises[self.current_index]

    def answer_for_exercise(self, exercise_id: str) -> dict[str, Any] | None:
        if not self.state_data:
            return None
        for answer in self.state_data.answers:
            if answer.get("exercise_id") == exercise_id:
                return answer
        return None

    def show_hint(self) -> None:
        exercise = self.current_exercise()
        if exercise:
            messagebox.showinfo("提示", self.build_focus_text(exercise, include_reference=False))

    def skip_current(self) -> None:
        exercise = self.current_exercise()
        if exercise:
            self.grammar_var.set(exercise.grammar_focus)
            self.set_result(f"{self.build_focus_text(exercise, include_reference=False)}\n\n参考答案：\n{exercise.reference_answer}")

    def submit_answer(self) -> None:
        exercise = self.current_exercise()
        if not exercise or not self.state_data:
            return
        answer = self.answer_text.get("1.0", tk.END).strip()
        if not answer:
            messagebox.showinfo("还没有答案", "请先输入答案，或者点击“跳过”。")
            return

        self.submit_button.configure(state="disabled")
        self.status_var.set("正在批改...")
        thread = threading.Thread(target=self._grade_in_background, args=(exercise, answer), daemon=True)
        thread.start()

    def _grade_in_background(self, exercise: Any, answer: str) -> None:
        assert self.state_data is not None
        try:
            exercise_payload = exercise_to_dict(exercise)
            grade = (
                self.state_data.tutor.grade_answer(exercise_payload, answer)
                if self.state_data.tutor
                else fallback_grade(exercise_payload, answer)
            )
            self.after(0, lambda: self.finish_grading(exercise.id, answer, grade))
        except Exception as error:
            self.after(0, lambda: self.fail_grading(str(error)))

    def finish_grading(self, exercise_id: str, answer: str, grade: dict[str, Any]) -> None:
        assert self.state_data is not None
        exercise = self.current_exercise()
        existing_record = self.answer_for_exercise(exercise_id)
        review_already_recorded = bool(existing_record and existing_record.get("review_recorded"))
        should_record_review = not review_already_recorded

        if should_record_review and exercise:
            for grammar in exercise.grammar_focuses or [exercise.grammar_focus]:
                if grammar:
                    update_grammar_review(grammar, int(grade.get("score", 0)), self.state_data.date)
        self.state_data.answers = [item for item in self.state_data.answers if item.get("exercise_id") != exercise_id]
        self.state_data.answers.append(
            {
                "exercise_id": exercise_id,
                "answer": answer,
                "grade": grade,
                "review_recorded": review_already_recorded or should_record_review,
                "exercise_snapshot": exercise_to_dict(exercise) if exercise else {},
            }
        )
        save_session(self.state_data.date, self.state_data.exercise_set, self.state_data.answers)
        self.show_grade(grade)
        self.refresh_exercise_list()
        self.submit_button.configure(state="normal")
        self.submit_button.configure(text="更改答案")
        mode = "AI 批改" if self.state_data.tutor else "本地占位批改"
        self.status_var.set(f"{self.state_data.date} · {generation_mode_label(self.state_data.generation_mode)} · {mode} · 已保存")

    def fail_grading(self, message: str) -> None:
        self.submit_button.configure(state="normal")
        exercise = self.current_exercise()
        self.submit_button.configure(text="更改答案" if exercise and self.answer_for_exercise(exercise.id) else "提交批改")
        self.status_var.set("批改失败")
        messagebox.showerror("批改失败", message)

    def show_grade(self, grade: dict[str, Any]) -> None:
        exercise = self.current_exercise()
        if exercise:
            self.grammar_var.set(exercise.grammar_focus)
        lines = [
            f"得分：{grade.get('score', '?')}/100",
            "",
            f"参考答案：{grade.get('corrected_answer', '')}",
            "",
            f"解释：{grade.get('explanation', '')}",
        ]
        if exercise:
            lines.extend(["", self.build_focus_text(exercise, include_reference=False)])
            if exercise.answer_explanation:
                lines.extend(["", f"参考答案说明：{exercise.answer_explanation}"])
        notes = grade.get("grammar_notes") or []
        if notes:
            lines.append("")
            lines.append("语法要点：")
            lines.extend(f"- {note}" for note in notes)
        if grade.get("encouragement"):
            lines.append("")
            lines.append(str(grade["encouragement"]))
        self.set_result("\n".join(lines))

    def build_focus_text(self, exercise: Any, include_reference: bool) -> str:
        lines = [f"难度：{exercise.difficulty}", f"涉及语法：{exercise.grammar_focus}"]
        vocabulary = exercise.vocabulary_focus or []
        if vocabulary:
            lines.append("涉及单词：")
            lines.extend(f"- {word}" for word in vocabulary)
        if exercise.hint:
            lines.extend(["", f"提示：{exercise.hint}"])
        if include_reference:
            lines.extend(["", f"参考答案：{exercise.reference_answer}"])
        return "\n".join(lines)

    def set_result(self, value: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", value)
        self.result_text.configure(state="disabled")

    def previous_exercise(self) -> None:
        if not self.state_data:
            return
        self.current_index = max(0, self.current_index - 1)
        self.refresh_exercise_list()
        self.show_current_exercise()

    def next_exercise(self) -> None:
        if not self.state_data:
            return
        last_index = len(self.state_data.exercise_set.exercises) - 1
        self.current_index = min(last_index, self.current_index + 1)
        self.refresh_exercise_list()
        self.show_current_exercise()


def label_for_type(exercise_type: str) -> str:
    if exercise_type == "translation_cn_to_ja":
        return "中译日"
    if exercise_type == "translation_ja_to_cn":
        return "日译中"
    return exercise_type


def generation_mode_label(mode: str) -> str:
    if mode == GENERATION_MODE_REVIEW:
        return "按语法复习情况"
    if mode == GENERATION_MODE_RANDOM:
        return "随机抽选语法"
    return mode


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="JapaneseAgent desktop app.")
    parser.add_argument("--cn-to-ja-count", type=int, default=None)
    parser.add_argument("--ja-to-cn-count", type=int, default=None)
    parser.add_argument("--regenerate", action="store_true")
    args = parser.parse_args()

    app = JapaneseAgentApp(
        cn_to_ja_count=args.cn_to_ja_count,
        ja_to_cn_count=args.ja_to_cn_count,
        regenerate=args.regenerate,
    )
    app.mainloop()


if __name__ == "__main__":
    main()
