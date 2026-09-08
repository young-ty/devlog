"""Allow ``python -m devlog.eval`` to run the evaluation suite."""

from devlog.eval.runner import run_cli


if __name__ == "__main__":
    raise SystemExit(run_cli())
