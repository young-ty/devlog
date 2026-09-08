# DevLog

DevLog 是面向个人开发者的**本地开发复盘工具**：扫描 Git 仓库的提交历史，
按开发主题聚类，再生成一份“有据可查、人机共创”的结构化复盘草稿。
事实论断带 commit 来源，AI 推断先标记为“待确认”，你确认并补充后导出 Markdown。

## 核心能力

- 只读 Git 历史，零侵入：不需要在开发过程中额外记录任何东西；
- 自动聚类开发主题，识别噪音提交（merge / wip / chore 等）与静默期；
- AI 摘要逐条附 commit 来源，降低幻觉风险；
- 复盘草稿区分“事实”与“AI 待确认”，支持逐条确认/补充后导出；
- 内置离线评测集，用人工 golden set 量化摘要质量。

## 技术栈

- Python 3.12 + FastAPI + Uvicorn
- SQLite（本地状态库，`~/.devlog/devlog.db`）
- React + TypeScript + Vite（本地 Web 界面）
- DeepSeek API（通过 provider 抽象层，可替换）

## 快速开始

### 1. 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

安装后终端里会多出 `devlog` 命令：

```powershell
devlog --version
```

### 2. 命令行全流程演示（对本仓库 dogfood）

```powershell
devlog init .
devlog scan .
devlog review generate --offline
devlog review list
devlog review confirm 1 --all
devlog review export 1
```

`--offline` 不调用 AI、不需要 API key，适合无网演示和自动化测试。
去掉 `--offline` 才会走 DeepSeek 生成真正的 AI 摘要。

### 3. 启动本地 Web 界面

终端一：启动后端 API（默认只监听本机 127.0.0.1:8000）

```powershell
devlog serve
```

终端二：启动前端开发服务器

```powershell
cd devlog/web
pnpm install
pnpm dev
```

浏览器打开 <http://localhost:5173>。

### 4. 配置 DeepSeek（可选）

创建 `%USERPROFILE%\.devlog\config.toml`：

```toml
api_key = "sk-你的密钥"
model = "deepseek-chat"
```

也可以设置环境变量 `DEEPSEEK_API_KEY`。密钥始终保存在 `~/.devlog/`，不会进入任何 Git 仓库。

## 测试与质量

```powershell
python -m unittest discover -s tests
python tests/test_product_design.py
python tests/test_technical_design.py
python -m devlog.eval
```

完整测试套件覆盖 Git 扫描、SQLite 存储、主题聚类、LLM、复盘生成/导出、
CLI、FastAPI、React 构建以及模块九的离线评测。

## 项目结构

```text
devlog/
├── core/
│   ├── git_source/   # Git 扫描与事件建模
│   ├── storage/      # SQLite 状态库
│   ├── theming/      # 主题聚类
│   ├── llm/          # LLM provider 抽象与摘要
│   └── review/       # 复盘草稿组装与 Markdown 导出
├── cli/              # devlog 命令行
├── server/           # FastAPI 本地 API
├── eval/             # golden set 离线评测
└── web/              # React + Vite 前端
```

## 常见问题

- 端口被占用：换端口启动，例如 `devlog serve --port 9000`；
- 提示缺少 API key：按上文配置 `~/.devlog/config.toml`，或先使用 `--offline`；
- rebase / force push 之后历史变化：执行 `devlog scan . --reset` 重建缓存。
