"""本机桌面能力：让本地 Web 界面能弹出系统原生的「选择文件夹」对话框。

为什么必须放在后端做：浏览器出于安全考虑不允许网页读取本机任意路径，
`<input type="file" webkitdirectory>` 也只能拿到相对路径、拿不到盘符。
而 DevLog 的后端本来就跑在用户自己的电脑上，由它调用系统对话框、
再把结果通过 HTTP 回给页面，才能在「网页里点一下，弹出文件夹选择框」。

因为这是本机特权，app.py 会先校验请求来自回环地址（127.0.0.1 / ::1）
才会调用这里的函数，避免局域网里的其他人往你的屏幕上弹窗口。
"""

from __future__ import annotations

import threading
from pathlib import Path


class DirectoryPickerError(RuntimeError):
    """弹不出系统对话框（缺图形界面支持等）。"""


class DirectoryPickerBusy(RuntimeError):
    """已经有一个选择框开着，用户还没处理完。"""


# 系统模态对话框一次只能开一个：两个请求同时弹窗会互相抢焦点，
# 极端情况下会把窗口堆叠到用户点不到。用非阻塞锁把并发挡在门外。
_PICKER_LOCK = threading.Lock()


def is_available() -> bool:
    """当前环境能不能弹出系统对话框（缺 tkinter 的精简版 Python 就不行）。"""

    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def pick_directory(
    title: str = "选择 Git 仓库所在的文件夹",
    initial_dir: str | Path | None = None,
) -> str | None:
    """弹出系统文件夹选择框。

    返回用户选中的绝对路径；用户点了取消（或直接关掉窗口）时返回 None。
    调用方必须能处理 None —— 「什么都没选」是正常操作，不是错误。
    """

    if not _PICKER_LOCK.acquire(blocking=False):
        raise DirectoryPickerBusy("已经有一个选择框打开了，请先处理它。")
    try:
        return _ask_directory(title, initial_dir)
    finally:
        _PICKER_LOCK.release()


def _ask_directory(title: str, initial_dir: str | Path | None) -> str | None:
    """真正调用 tkinter 的部分，和并发控制分开，方便单独替换/测试。"""

    try:
        import tkinter
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - 取决于运行环境
        raise DirectoryPickerError(
            "当前 Python 环境没有图形界面支持（缺少 tkinter），请手动填写仓库路径。"
        ) from exc

    try:
        root = tkinter.Tk()
    except Exception as exc:  # pragma: no cover - 取决于运行环境
        raise DirectoryPickerError(
            "无法打开系统选择框（服务端可能没有桌面环境），请手动填写仓库路径。"
        ) from exc

    # 隐藏 Tk 自带的空窗口，只留下选择框；置顶避免被浏览器挡住。
    root.withdraw()
    root.attributes("-topmost", True)

    options: dict[str, object] = {"title": title, "mustexist": True}
    if initial_dir:
        options["initialdir"] = str(initial_dir)

    try:
        selected = filedialog.askdirectory(**options)
    except Exception as exc:  # pragma: no cover - 取决于运行环境
        raise DirectoryPickerError(f"选择文件夹失败：{exc}") from exc
    finally:
        root.destroy()

    if not selected:
        return None
    return str(Path(selected).resolve())
