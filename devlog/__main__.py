"""允许通过 `python -m devlog` 运行命令行工具。"""

from devlog.cli.main import main as entry


if __name__ == "__main__":
    raise SystemExit(entry())
