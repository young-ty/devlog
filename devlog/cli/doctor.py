"""`devlog doctor`：一次打印出"为什么起不来"需要的关键信息。

打包成 exe 之后，用户看不到 traceback、也不知道机器上装了什么。
所以与其让用户描述现象，不如给一条命令把前提条件逐条列出来：
前端产物在不在、Git 有没有、数据库能不能开、大模型配没配。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TextIO

from devlog import __version__
from devlog.core.llm.deepseek import llm_settings
from devlog.core.storage.database import (
    DevLogDB,
    DatabaseError,
    default_db_path,
)
from devlog.server import desktop
from devlog.server.app import resolve_web_dist


OK = "[OK]"
WARN = "[警告]"
FAIL = "[失败]"


def running_from_frozen_exe() -> bool:
    """是不是打包后的 exe 在跑（PyInstaller 会注入 sys.frozen）。"""

    return bool(getattr(sys, "frozen", False))


def build_report(db_path: Path | None = None) -> tuple[list[str], bool]:
    """收集自检结果，返回（报告行, 是否一切正常）。

    缺前端产物 / 缺 Git / 数据库打不开才算失败；缺 API key 和缺
    tkinter 只算警告 —— 前者可以用 --offline，后者可以手填路径。
    """

    resolved_db = Path(db_path) if db_path is not None else default_db_path()
    lines = [
        f"DevLog 自检（v{__version__}）",
        f"  运行方式：{'打包 exe' if running_from_frozen_exe() else 'Python 源码'}",
    ]
    healthy = True

    web_dist = resolve_web_dist()
    if web_dist is None:
        healthy = False
        lines.append(
            f"  {FAIL} 前端产物：未找到（界面打不开；API 与命令行仍可用）"
        )
    else:
        lines.append(f"  {OK} 前端产物：{web_dist}")

    if desktop.is_available():
        lines.append(f"  {OK} 文件夹选择框：可用")
    else:
        lines.append(
            f"  {WARN} 文件夹选择框：不可用（缺 tkinter，手动填路径即可）"
        )

    git_path = shutil.which("git")
    if git_path is None:
        healthy = False
        lines.append(f"  {FAIL} Git：未找到（无法扫描仓库）")
    else:
        lines.append(f"  {OK} Git：{git_path}")

    try:
        with DevLogDB(resolved_db) as db:
            projects = len(db.list_projects())
            lines.append(
                f"  {OK} 状态数据库：{resolved_db}"
                f"（schema v{db.schema_version}，{projects} 个项目）"
            )
    except DatabaseError as exc:
        healthy = False
        lines.append(f"  {FAIL} 状态数据库：打不开 —— {exc}")

    settings = llm_settings()
    if settings.get("configured") == "true":
        lines.append(
            f"  {OK} 大模型：{settings.get('model')}"
            f" @ {settings.get('base_url')}"
        )
    else:
        lines.append(
            f"  {WARN} 大模型：未配置（在网页顶栏的「大模型设置」里填 Key，"
            "或先用 --offline 离线生成草稿）"
        )

    return lines, healthy


def run_doctor(db_path: Path | None = None, stream: TextIO | None = None) -> int:
    """打印自检报告；有问题时返回非 0，方便脚本判断。"""

    lines, healthy = build_report(db_path)
    target = stream if stream is not None else sys.stdout
    for line in lines:
        print(line, file=target)
    return 0 if healthy else 1
