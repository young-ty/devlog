# DevLog 技术方案（V1）

> 状态：Draft · 版本：0.1 · 2026-09-05
> 配套文档：[product-design.md](./product-design.md)

## 1. 目标与范围

本文档描述 DevLog V1 的技术方案：以本地 Git 仓库为唯一事实来源，提供"事件建模 → AI 复盘草稿 → 人工确认/编辑 → 导出 Markdown"的完整链路，并支撑 CLI 与本地 Web 两种使用方式。

V1 不包含 Bug 现场捕获、开发中批注、复盘定稿（V2/V3）。坑点知识库与语义
检索已移出范围，另立 RAG 项目。

## 2. 总体架构

```
┌────────────────────────── DevLog 本地进程 ──────────────────────────┐
│                                                                     │
│   CLI（argparse）       Web UI（React + Vite，浏览器访问）            │
│        │                      │                                     │
│        └──────────┬───────────┘                                     │
│              FastAPI 本地服务（Uvicorn）                             │
│                   │                                                │
│          核心库（纯 Python 领域逻辑，CLI/API 共用）                   │
│   ┌────────────────┼───────────────────────────────┐                │
│   │                │                               │                │
│ git_source     llm_pipeline                   review_engine         │
│ （读 Git）     （DeepSeek 等，可替换）            （草稿/导出）        │
│   │                │                               │                │
│   └────────────────┼───────────────────────────────┘                │
│                    ▼                                                │
│        SQLite 本地状态库（~/.devlog/devlog.db）                      │
│        —— 事件缓存、草稿与确认状态（非真相，可重建）                  │
└─────────────────────────────────────────────────────────────────────┘

外部产物：<被扫描项目>/docs/retrospectives/*.md（进入项目 Git，可版本化）
```

核心原则：**Git 是真相，SQLite 是缓存/状态库；复盘 Markdown 是唯一落进用户项目的产物。**

## 3. 技术选型

| 层次 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.12 | 核心逻辑与 AI 生态 |
| CLI | argparse（MVP，标准库零依赖） | 解析层与 runner 服务层分离；正式打包时可换 Typer，业务逻辑不变 |
| Git 读取 | subprocess 调用 `git log` / `git diff` / `git show` | 兼容所有 Git 版本，不依赖 GitPython |
| LLM | DeepSeek API（OpenAI 兼容协议） | 通过 provider 抽象层接入，默认 DeepSeek，可替换 |
| 结构化输出 | Pydantic v2 + JSON schema 校验 | 复盘论断强约束 + 重试/回退 |
| 本地服务 | FastAPI + Uvicorn | 供 CLI 与 Web 消费同一套 API |
| Web 前端 | React + TypeScript + Vite | 时间线、复盘编辑器、diff 侧栏；替代 Gradio |
| 状态存储 | SQLite（Python 标准库 sqlite3） | 本地单文件、事务安全、后续可加 FTS5 |
| 配置 | `~/.devlog/config.toml` | API Key 等本地配置，禁止入库 |
| 测试/质量 | pytest + 自定义评测脚本 + ruff | M4 评测集 + 常规测试 |

## 4. 分层与职责

### 4.1 git_source（事件建模）

- 输入：仓库路径 + 时间范围（日期区间 / 起止 commit / tag）；
- 读取 commit 元数据与文件变更统计；必要时按需读取 diff 内容；
- 噪音分类：merge、revert、wip、chore、依赖升级等；
- 主题聚类：先按提交信息/文件路径做启发式聚合，再用 LLM 生成主题摘要（可回归评测）；
- 支持增量扫描（记录上次扫描位置）与全量重建（历史改写后失效重建）；
- 产物为 SQLite 中的 commit/theme 记录。

### 4.2 storage（SQLite 状态库）

- 数据库位置：`~/.devlog/devlog.db`，**不放进被扫描的项目仓库**；
- `PRAGMA user_version` 管理 schema 版本，提供可迁移机制；
- 职责：项目注册、commit/事件缓存、主题、复盘草稿与论断状态、扫描进度。

### 4.3 llm_pipeline（AI 能力）

- provider 抽象：`LLMClient` 接口（chat 补全、结构化输出），默认 DeepSeek；
- 分块/增量摘要：超长历史先按 commit/主题分块，再逐层聚合，控制 token 与成本；
- 结构化输出：按复盘 schema（Pydantic 模型）约束字段，校验失败自动重试/降级；
- 证据设计：每条论断携带 `sources`（commit 列表）；无法从素材得出的内容生成引导问题，不编造。

### 4.4 review_engine（草稿与导出）

- 组装复盘草稿（项目概述/时间线/技术决策/问题与解决/踩坑/可复用资产/遗留与下一步）；
- 管理论断状态机：`fact`（Git 事实）→ `ai_pending`（AI 推断待确认）→ `confirmed` / `edited`（用户确认或修改）；
- 成稿规则（哪些论断算数、章节顺序、空章节怎么提示）只有一份实现（`devlog/core/review/document.py`），界面阅读视图与 Markdown 导出共用，避免两边排版各自漂移；
- 草稿可标记「定稿 / 撤回定稿」，作为"这份我认了"的显式状态；
- 导出 Markdown 到被扫描项目仓库的 `docs/retrospectives/`：导出是次要出口，只收已确认内容，定稿后导出在文末只交代未确认条数，不倾倒 AI 猜测。

### 4.5 memory_layer（记忆层与当日小结）

- 每日笔记（`dev_notes`，每个项目每天一条）、Bug 捕获（`bug_records`）、commit 批注（`commit_annotations`）构成 Git 之外的人工记忆，全部落在 `~/.devlog/devlog.db`，不进用户仓库；
- 当日小结（`devlog/core/digest/day.py`）把这些记录按日历日归并成一屏：当天的提交、当天捕获的 Bug、统计数字，以及一段可以直接填进「今天做了什么」的草稿；
- 日期归属以**本机时区**为准，且只在这一个模块里判断：Git 提交自带时区偏移，用本地边界直接卡 `since/until` 会在边界上漏记录；
- 小结只做事实归并，不调模型——省 token、无幻觉。要让 AI 概括"今天干了什么"，必须走已有的「AI 推断 + 用户确认」流程；
- 「这仓库还没扫描过」和「这天没干活」是两种状态，用 `has_cached_commits` 分开表达，否则一句"当天没有记录"会把没扫描的仓库也盖进去。

### 4.6 presentation（CLI / API / Web）

MVP CLI（模块六，`python -m devlog`）：

| 命令 | 作用 |
|---|---|
| `init` | 注册 Git 仓库 |
| `scan [--reset]` | 扫描 / 重建事件缓存 |
| `review generate [--offline]` | 生成草稿（离线 = 规则事实摘要） |
| `review list [--draft]` | 列出草稿 / 查看逐条论断 |
| `review confirm` | AI 推断 → 已确认 |
| `review export` | 草稿导出为 Markdown |

`cli/main.py` 只做参数解析与结果打印，真正流程在 `cli/runner.py`
（服务层），模块七 FastAPI 直接复用 runner。FastAPI 提供同能力 REST
接口，Web 前端只消费 API；前端页面为项目概览 / 时间线 / AI 复盘编辑器
（Bug 追踪为 V2 占位）。

> 决策记录：V1 选用标准库 argparse 而非 Typer，是为了保持零第三方依赖，
> 让 `python -m devlog` 开箱即用。解析层是薄壳，未来引入 Typer 只改
> `cli/main.py`，不影响 runner 与核心模块。

前端落地（模块八）：React + TypeScript + Vite，代码位于 `devlog/web/`；
开发时 Vite 把 `/api` 代理到 `http://127.0.0.1:8000`，浏览器不直接跨源。
MVP 只有三个页面（项目列表 / 项目详情 / 复盘编辑器），页面切换由
`App.tsx` 状态完成，暂不引入 React Router 与 Redux。

## 5. 核心数据模型（初版）

### projects

| 字段 | 说明 |
|---|---|
| id | 主键 |
| name / path | 项目名与本地路径 |
| last_scanned_commit | 增量扫描游标 |

### commits（Git 事件缓存）

| 字段 | 说明 |
|---|---|
| project_id | 所属项目 |
| hash / short_hash | commit 哈希（关联字段，非业务主键语义） |
| author / committed_at / message | 原始信息 |
| files_changed / insertions / deletions | 变更统计 |
| noise_type | null / merge / wip / chore 等 |
| theme_id | 聚类归属 |

### themes

| 字段 | 说明 |
|---|---|
| id / project_id / name / summary | 主题 |
| sources_json | 来源 commit 列表 |
| status | `fact` / `ai_pending` / `confirmed` |

### review_drafts / review_claims（草稿与论断，schema v2）

### review_drafts

| 字段 | 说明 |
|---|---|
| id / project_id | 草稿 ID 与所属项目 |
| range_start / range_end | 复盘时间范围 |
| questions_json | 引导问题列表（非论断，单独存储） |
| exported_path | 最近一次导出位置 |

### review_claims（草稿论断）

| 字段 | 说明 |
|---|---|
| id / draft_id / section | 归属板块 |
| text | 论断内容 |
| sources_json | 来源 commit 列表（可为空 = 引导提问） |
| status | `fact` / `ai_pending` / `confirmed` / `edited` |
| user_note | 用户补充 |

### 外部产物

```text
<project>/docs/retrospectives/<project>_<range>.md
```

## 6. 本地 API（示意）

```text
GET    /api/projects
POST   /api/projects            # 注册仓库
POST   /api/projects/{id}/scan  # 扫描/增量扫描
GET    /api/projects/{id}/timeline?range=...
GET    /api/projects/{id}/digest?date=YYYY-MM-DD   # 当天小结（提交 + Bug）
GET    /api/projects/{id}/notes?note_date=...
POST   /api/projects/{id}/notes                    # 每日笔记（upsert）
POST   /api/projects/{id}/bugs                     # Bug 现场捕获
POST   /api/projects/{id}/reviews/generate
GET    /api/projects/{id}/reviews/{draft_id}
PATCH  /api/reviews/{draft_id}/claims/{claim_id}   # 确认/编辑
POST   /api/reviews/{draft_id}/export
```

## 7. 关键设计决策

1. **SQLite 只做状态库，不是真相**：commit 数据可随时从 Git 重建；rebase/force push 改变历史时，标记相关缓存失效并重扫。
2. **产物进用户仓库，状态不进用户仓库**：复盘 Markdown 是交付物，应版本化；`devlog.db` 放在 `~/.devlog/`，避免污染项目。
3. **LLM provider 抽象**：复盘质量与成本评测需要可替换模型；业务层不感知具体厂商。
4. **结构化输出 + 校验**：AI 输出先过 Pydantic schema，非法则重试/降级，防止脏数据进入草稿。
5. **防幻觉内建于数据模型**：论断区分"有来源的事实"与"待确认的推断"，无来源内容只能是引导问题。
6. **成本可预期**：分块摘要 + 增量扫描 + 结果缓存，避免重复调用浪费 token。
7. **数据库版本化演进**：`SCHEMA_VERSION = 2`，v1→v2 通过 `PRAGMA user_version`
   迁移新增草稿表；旧库升级不丢数据，新库从零按序建表。

## 8. 安全与隐私

- 全部数据留在本机，无云端同步；
- API Key 只存 `~/.devlog/config.toml`（建议 chmod 600），仓库与代码库均不包含；
- V2 Bug 捕获才涉及堆栈/环境信息入库，届时加入脱敏与确认流程（本期仅预留字段设计空间）。

## 9. 工程质量与评测

- 单元测试：git 解析、主题聚类规则、schema 校验、导出渲染；
- 集成测试：临时 Git 仓库（构造固定提交历史）跑 scan → generate → confirm → export 全链路；
- 评测集（M4）：20-30 条人工标注 golden set，用相似度 + LLM-as-judge 量化摘要/复盘质量；
- 每次改动按 AGENTS.md 要求提交并跑全部测试。

## 10. 建议目录结构

```text
devlog/
├── core/
│   ├── git_source/       # Git 解析与事件建模
│   ├── storage/          # SQLite schema 与迁移
│   ├── llm/              # provider 抽象与分块摘要
│   └── review/           # 草稿组装与导出
├── cli/                  # argparse 解析 + runner 服务层
├── server/               # FastAPI 应用
├── web/                  # React + Vite 前端
├── tests/
│   ├── unit/
│   ├── integration/
│   └── eval/             # golden set 与评测脚本
├── docs/                 # 产品与设计文档
└── AGENTS.md
```

## 11. 里程碑（建议顺序）

1. **M1**：仓库接入 + Git 事件建模 + SQLite 落库（CLI：init/scan）；
2. **M2**：LLM provider + 分块摘要 + 结构化复盘草稿（CLI：generate，本地 Markdown 预览）；
3. **M3**：FastAPI + React 界面，接入确认/编辑/导出闭环；
4. **M4**：评测集与回归脚本，跑通全链路并 dogfood 真实项目；
5. 打磨：错误处理、增量扫描边界（rebase/force push）、打包体验。

## 12. 主要风险

- **Git 历史形态多样**：merge 图、作者时区、超大仓库、乱写 commit message → 用集成测试固定行为；
- **LLM 输出质量波动**：靠 schema 校验 + golden set 回归兜底；
- **token 成本**：分块聚合 + 缓存 + 可换低成本模型；
- **范围膨胀**：严格按非目标执行，V2/V3 只做接口与 schema 预留。
