# 问势 WorldSense

[中文](README.md) | [English](README.EN.md)

> AI 驱动的大规模用户调研模拟平台

不招募一个真实用户，即可生成数千个具有多元文化背景的虚拟 persona，通过 LLM 推理模拟每个人的认知视角，产出结构化的市场反馈。

## 核心能力

- **3 层 Persona 引擎** — 人口统计（30+ 国家、342+ 职业）+ Hofstede 文化维度 & Big Five 人格 → 10 维认知模型 + MBTI + LLM 生成的个人背景
- **6 种研究类型** — 产品购买、社交关注、内容反应、App 试用、概念测试、竞品切换
- **多模态输入** — 文本、URL（自动提取网页/YouTube/Bilibili 字幕或转录）、图片（per-persona 视觉理解或系统摘要）、PDF/Word/Markdown
- **多 LLM 后端** — OpenAI 兼容 / Anthropic 兼容 / Mock（测试用），支持多 Profile 切换
- **异步并发推理** — Token bucket 限速 + 指数退避重试 + 实时点阵可视化
- **结构化报告** — 转化率、NPS、情感分析 + 按国籍/年龄/收入/职业/MBTI 分段

## 快速开始

```bash
# 安装
git clone https://github.com/hchen13/worldsense.git
cd worldsense
pip install -e .

# 配置 LLM
cp .env.example .env
# 编辑 .env，填入 API Key 和 endpoint

# 启动 Web UI
./start.sh
# 访问 http://localhost:8766/worldsense/

# 或使用 CLI
ws personas --count 10 --market cn --table     # 预览 persona
ws run -f content.md -n 50 -m cn -l 中文 -r social_follow  # 运行研究
ws report <task-id>                             # 查看报告
```

## CLI 示例

```bash
# 从文件读取内容，中国市场，50 人，社交关注类型
ws run \
  --content-file article.md \
  --personas 50 --market cn --language 中文 \
  --research-type social_follow \
  --scenario-context "你在小红书刷到了这篇帖子" \
  --dimensions '{"location_weights":{"t1":0.5,"new-t1":0.5}}'

# 带图片的评估（每个 persona 独立视觉理解）
ws run \
  --content "评估这张海报的吸引力" \
  --image poster.jpg \
  --personas 20 --market cn
```

## Web UI

<p align="center">
  <img src="docs/screenshot-new-run.png" alt="New Research" width="80%" />
</p>

功能包括：
- 两栏布局的研究创建页面（内容输入 + 配置/预览）
- URL 自动提取（网页正文、视频字幕/转录）
- 文件上传（图片、PDF、Word）+ Vision 模式选择
- 实时 Persona Matrix 点阵可视化（hover 查看每个 persona 的详情和反馈）
- Prompt Preview（查看实际发给 LLM 的完整 prompt）
- 一键 Rerun（复制历史任务参数重新运行）

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                    CLI (ws) / FastAPI Web UI                │
└─────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │   ResearchEngine   │
                    └─────────┬──────────┘
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼───────┐ ┌────▼────┐ ┌────────▼────────┐
    │  Persona Engine  │ │Pipeline │ │ Report Generator │
    │  (3+1 layers)    │ │(async)  │ │  (aggregator)    │
    └─────────────────┘ └────┬────┘ └──────────────────┘
                             │
                    ┌────────▼────────┐
                    │   LLM Backend   │
                    └────────┬────────┘
           ┌────────────────┼─────────────────┐
     ┌─────▼──┐    ┌───────▼────────┐  ┌─────▼──────────┐
     │  Mock  │    │ OpenAI Compat  │  │Anthropic Compat│
     └────────┘    └────────────────┘  └────────────────┘
```

### Persona 引擎

| 层 | 模块 | 功能 |
|---|---|---|
| Layer 1 | `persona/generator.py` | 按联合国人口权重采样国籍、年龄、性别、职业（342+ BLS 职业）、收入（从职业推导） |
| Layer 2 | `persona/cognitive.py` | Hofstede 六维文化维度 + Big Five → 10 个消费决策参数 + MBTI |
| Layer 2.5 | `persona/epsilon.py` | LLM 实时生成个人背景 + 业余兴趣 |
| Pipeline | `pipeline/output.py` | Mode B：单次 LLM 调用完成人物构建 + 内容评估 |

## 项目结构

```
worldsense/
├── worldsense/
│   ├── cli.py              # CLI 入口 (typer)
│   ├── api/app.py          # FastAPI Web API
│   ├── core/               # 任务引擎、结果类型、设置
│   ├── persona/            # 3 层 Persona 引擎
│   ├── llm/                # LLM 后端抽象 + 限速
│   ├── pipeline/           # 异步推理 + Prompt 构建
│   ├── report/             # 报告生成
│   └── static/             # Web UI (HTML/CSS/JS)
├── data/
│   ├── hofstede.json       # Hofstede 文化维度 (70+ 国家)
│   ├── populations.json    # 联合国人口权重
│   ├── occupations.json    # 342+ BLS 职业数据
│   ├── country_profiles.json # 国家 PPP/薪资/城市层级
│   ├── work_contexts.json  # 职业场景描述
│   └── title_translations.json # 职业名多语言翻译
├── tests/
├── docs/
│   └── ARCHITECTURE.md     # 架构设计文档
├── start.sh / stop.sh      # 服务启停脚本
└── pyproject.toml
```

## 支持的市场

| 市场 | 覆盖国家 |
|------|---------|
| `global` | 全部 30+ 国家 |
| `cn` | 中国（含城市层级：一线/新一线/二三四五线/农村） |
| `us` | 美国 |
| `asia` | 中日韩印东南亚 |
| `europe` | 德法英意西荷瑞俄 |
| `developed` / `emerging` | 发达/新兴市场 |

## 依赖

- Python 3.11+
- 主要依赖：typer, rich, pydantic, httpx, FastAPI, trafilatura
- 可选：yt-dlp（视频字幕提取）、whisper（音频转录）

## If You Are an AI Agent

Here's how you help your human set up WorldSense:

```bash
# 1. Clone and install
cd ~/projects  # or wherever your human keeps their code
git clone https://github.com/hchen13/worldsense.git
cd worldsense
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Configure LLM — ask your human for their API key
cp .env.example .env
# Set WS_API_KEY, WS_API_BASE_URL, WS_MODEL in .env
# Supports: OpenAI, Anthropic, DeepSeek, GLM, MiniMax, any OpenAI-compatible endpoint

# 3. Start the Web UI
./start.sh
# Now open http://localhost:8766/worldsense/ in your human's browser

# 4. Or run from CLI directly
ws run \
  --content-file content.md \
  --personas 50 --market cn --language 中文 \
  --research-type social_follow \
  --scenario-context "用户在小红书上刷到了这篇帖子"

# 5. View results
ws report <task-id>
```

**The CLI and API are built for you.** When your human asks you to use WorldSense on their behalf, register and use it as a skill. See **[SKILL.md](SKILL.md)** for the complete agent reference — all CLI commands, API endpoints, research types, dimension configs, and tips for effective use.

**Key things to know:**
- `ws personas --count 10 --market cn` outputs JSON by default (agent-friendly). Add `--table` for human display.
- `ws run --help` shows all CLI options including `--profile`, `--dimensions`, `--image`, `--vision-mode`
- The API at `http://localhost:8766/worldsense/api/` gives you full programmatic control — submit tasks, poll status, read results
- Mock backend (`-b mock`) runs instantly — great for verifying setup before spending LLM credits
- Results are stored in `~/.worldsense/results/` as JSON. Settings in `~/.worldsense/settings.json`

## License

MIT
