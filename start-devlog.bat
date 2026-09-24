@echo off
chcp 65001 >nul
REM DevLog 一键启动：缺前端产物就先构建，然后启动本地服务并自动打开浏览器。
REM 直接双击本文件即可日常使用；关闭黑窗口就等于停止 DevLog。
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\devlog.exe" (
    echo [错误] 没找到 .venv\Scripts\devlog.exe
    echo        请先按 README 的「快速开始 - 安装」创建虚拟环境并执行 pip install -e .
    pause
    exit /b 1
)

if exist "devlog\web\dist\index.html" (
    echo [1/2] 前端产物已存在，跳过构建。
) else (
    echo [1/2] 首次启动，正在构建前端界面（需要 Node.js 与 pnpm）...
    pushd devlog\web
    call pnpm install
    call pnpm build
    popd
    if not exist "devlog\web\dist\index.html" (
        echo [错误] 前端构建失败，请先确认 pnpm 可用。
        pause
        exit /b 1
    )
)

echo [2/2] 正在启动 DevLog，稍后浏览器会自动打开 http://127.0.0.1:8000
".venv\Scripts\devlog.exe" serve --open
pause
