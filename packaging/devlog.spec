# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 DevLog 打成单文件 exe。

正常用法是双击仓库根目录的 build-app.bat；也可以手动执行：

    .venv\\Scripts\\pyinstaller.exe packaging\\devlog.spec --noconfirm

产物 dist\\DevLog.exe 自带 Python 运行时和前端产物，
目标机器不需要装 Python，也不需要装 Node。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH 由 PyInstaller 注入：本文件所在目录（packaging/）
PROJECT_ROOT = Path(SPECPATH).resolve().parent
WEB_DIST = PROJECT_ROOT / "devlog" / "web" / "dist"

# 前端产物按 devlog/web/dist 放进包里：运行时代码里的
# DEFAULT_WEB_DIST 是"<包目录>/../web/dist"算出来的，
# 冻结后 __file__ 指向解包目录，路径正好对上，不用写 if frozen 分支。
datas = [(str(WEB_DIST), "devlog/web/dist")]

# uvicorn 用 importlib 动态加载 loop / protocol 实现，静态分析看不到，
# 必须显式收集整个包，否则运行时会在 "auto" 这一层炸掉。
hiddenimports = collect_submodules("uvicorn")

a = Analysis(
    [str(PROJECT_ROOT / "devlog" / "__main__.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DevLog",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    icon=None,
)
