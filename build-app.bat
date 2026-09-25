@echo off
chcp 65001 >nul
REM 把 DevLog 打包成单文件 exe（产物：dist\DevLog.exe）。
REM 目标机器不需要装 Python / Node，双击 exe 即可启动界面。
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo [错误] 没有安装 PyInstaller。先执行下面这条命令：
    echo        uv pip install --python .venv\Scripts\python.exe pyinstaller
    pause
    exit /b 1
)

echo [1/4] 构建前端产物...
pushd devlog\web
call pnpm install
call pnpm build
popd
if not exist "devlog\web\dist\index.html" (
    echo [错误] 前端构建失败，打包中止：否则打出来的是个只有 API 的空壳。
    pause
    exit /b 1
)

echo [2/4] 用 PyInstaller 打包（第一次会慢一些）...
".venv\Scripts\pyinstaller.exe" packaging\devlog.spec --noconfirm --distpath dist --workpath build
if not exist "dist\DevLog.exe" (
    echo [错误] 打包失败，请看上面的输出。
    pause
    exit /b 1
)

echo [3/4] 自检产物...
dist\DevLog.exe doctor

echo [4/4] 完成：%CD%\dist\DevLog.exe
echo        把它拷到任何 Windows 机器上双击就能用。
pause
