# JapaneseAgent

从 Obsidian 日语笔记中读取已学语法点，每天生成 N4/N5 词汇范围内的中译日和日译中题，并在你输入答案后自动批改、解释语法。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="你的 key"
python -m japanese_agent practice
```

## 一键启动

macOS 上可以直接双击项目根目录里的 `JapaneseAgent.app`，它会打开独立练习窗口。

如果 `.app` 被系统拦截，可以右键点击 `JapaneseAgent.app`，选择“打开”。

也可以双击 `start.command` 作为备用启动方式。

它会自动：

- 进入当前项目目录
- 创建并启用 `.venv`
- 安装缺失依赖
- 读取 `.env`
- 打开独立练习窗口

窗口里可以点击“重新生成今日练习”，用最新笔记重新生成今天的题目。

默认读取：

```text
/Users/stardustor/Library/CloudStorage/OneDrive-个人/obsidian-doc/日本語を勉強します
```

如果要换路径：

```bash
python -m japanese_agent practice --notes-dir "/path/to/notes"
```

## 常用命令

查看识别到的语法条目：

```bash
python -m japanese_agent list-notes
```

生成指定数量题目：

```bash
python -m japanese_agent practice --cn-to-ja-count 3 --ja-to-cn-count 3
```

启动窗口版：

```bash
python -m japanese_agent.gui
```

复习某一天：

```bash
python -m japanese_agent practice --date 2026-06-12
```

如果当天已经生成过练习，默认会继续使用 `data/sessions/` 里保存的当天题目和进度。
如果你更新了笔记，并且希望今天的题目立刻基于最新笔记重新生成：

```bash
python -m japanese_agent practice --regenerate
```

## 配置

可以用环境变量配置：

```bash
export OPENAI_API_KEY="你的 key"
export JAPANESE_AGENT_MODEL="gpt-4.1-mini"
export JAPANESE_AGENT_NOTES_DIR="/path/to/notes"
```

也可以在项目根目录创建 `.env`：

```text
OPENAI_API_KEY=你的 key
JAPANESE_AGENT_MODEL=gpt-4.1-mini
JAPANESE_AGENT_NOTES_DIR=/path/to/notes
JAPANESE_AGENT_CN_TO_JA_COUNT=3
JAPANESE_AGENT_JA_TO_CN_COUNT=2
JAPANESE_AGENT_MAX_GRAMMAR_PER_EXERCISE=3
```

练习记录会保存在 `data/sessions/`，方便之后继续做复习和错题统计。

窗口版左侧也可以临时调整“中译日/日译中”的数量，然后点击“按数量重新生成”。

每次生成会安排难度梯度：中译日内部会从较少语法逐渐增加到多语法组合，日译中内部也会单独形成同样的梯度。`JAPANESE_AGENT_MAX_GRAMMAR_PER_EXERCISE` 可以控制单题最多组合几个语法。

## 语法复习

程序会记录每个语法点的复习情况，记录保存在：

```text
data/grammar_srs.json
```

每次批改后，会根据得分更新该语法点的复习状态：

- 低分会增加遗忘次数，并让语法更快再次出现
- 高分会拉长复习间隔
- 已到期、错得多、低分的语法会在后续生成题目时获得更高权重
- 最近几次练习已经用过的语法会被降权，避免每天过于重复

查看语法复习状态：

```bash
python -m japanese_agent grammar-srs
```

## Anki 词汇

程序可以通过 AnkiConnect 读取你在 Anki 里保存的单词，并在生成中译日/日译中题时优先使用这些词。
词汇会参考 Anki 复习状态抽样：优先使用最近复习过且熟悉程度较低的卡片，其次使用 `is:due` 到期卡片和 `prop:lapses>0` 有遗忘记录的卡片，最后再用普通卡片补足数量。

准备步骤：

1. 在 Anki 中安装插件 AnkiConnect，插件代码是 `2055492159`。
2. 保持 Anki 软件打开。
3. 在 `.env` 中配置查询条件和字段名。

示例：

```text
JAPANESE_AGENT_ANKI_ENABLED=1
JAPANESE_AGENT_ANKI_QUERY=deck:日本語
JAPANESE_AGENT_ANKI_LIMIT=80
JAPANESE_AGENT_ANKI_WORD_FIELDS=Expression,Word,Vocabulary,Front
JAPANESE_AGENT_ANKI_READING_FIELDS=Reading,Kana
JAPANESE_AGENT_ANKI_MEANING_FIELDS=Meaning,Back,中文,Chinese
```

`JAPANESE_AGENT_ANKI_QUERY` 使用 Anki 自己的搜索语法。比如：

```text
deck:日本語
tag:N4 OR tag:N5
deck:日本語 (tag:N4 OR tag:N5)
```

如果没有配置 Anki 查询，或者 Anki 没打开，程序仍然可以练习，只是不会把 Anki 单词加入题目。

如果希望生成题目的词汇池更小、更集中，可以把 `JAPANESE_AGENT_ANKI_LIMIT` 调低，例如 `30`。

## 笔记更新规则

`list-notes` 和新生成练习时都会重新读取 Obsidian 文件夹里的 Markdown，所以你新增或修改笔记后，语法条目会更新。

有一个例外：某一天的练习一旦生成，会缓存在 `data/sessions/YYYY-MM-DD.json`，这样你中途退出后可以继续同一套题。要让当天练习使用最新笔记，请在窗口中点击“重新生成今日练习”，或运行 `practice --regenerate`。
