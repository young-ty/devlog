"""允许通过 ``python -m devlog.eval`` 运行评测套件。"""

from devlog.eval.runner import run_cli


if __name__ == "__main__":
    raise SystemExit(run_cli())
