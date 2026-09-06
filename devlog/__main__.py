"""Allow `python -m devlog` to run the CLI."""

from devlog.cli.main import main as entry


if __name__ == "__main__":
    raise SystemExit(entry())
