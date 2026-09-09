"""打包元数据、版本、serve 命令与 README 的测试。"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from devlog import __version__
from devlog.cli.main import build_parser, main


ROOT = Path(__file__).resolve().parent.parent


class PackagingMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        pyproject = ROOT / "pyproject.toml"
        with pyproject.open("rb") as handle:
            self.metadata = tomllib.load(handle)

    def test_pyproject_declares_package_metadata(self) -> None:
        project = self.metadata["project"]
        self.assertEqual(project["name"], "devlog")
        self.assertEqual(project["requires-python"], ">=3.12")
        self.assertEqual(project["readme"], "README.md")
        self.assertIn("version", project["dynamic"])

    def test_dependencies_are_pinned(self) -> None:
        dependencies = self.metadata["project"]["dependencies"]
        joined = "\n".join(dependencies)
        self.assertIn("fastapi==", joined)
        self.assertIn("httpx==", joined)
        self.assertIn("uvicorn[standard]==", joined)

    def test_console_script_points_to_cli_main(self) -> None:
        scripts = self.metadata["project"]["scripts"]
        self.assertEqual(scripts["devlog"], "devlog.cli.main:main")

    def test_version_is_derived_from_package(self) -> None:
        dynamic = self.metadata["tool"]["setuptools"]["dynamic"]
        self.assertEqual(dynamic["version"]["attr"], "devlog.__version__")
        self.assertEqual(__version__, "0.1.0")

    def test_readme_file_exists(self) -> None:
        self.assertTrue((ROOT / self.metadata["project"]["readme"]).is_file())


class VersionCommandTests(unittest.TestCase):
    def test_main_version_prints_and_exits_zero(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as context:
                main(["--version"])
        self.assertEqual(context.exception.code, 0)
        self.assertIn(__version__, buffer.getvalue())


class ServeCommandTests(unittest.TestCase):
    def test_serve_defaults_to_localhost_8000(self) -> None:
        args = build_parser().parse_args(["serve"])
        self.assertEqual(args.command, "serve")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8000)

    def test_serve_calls_uvicorn_with_app_and_options(self) -> None:
        captured: dict[str, object] = {}

        def fake_run(app: object, **kwargs: object) -> None:
            captured["app"] = app
            captured.update(kwargs)

        with mock.patch("devlog.cli.main.create_app", return_value="fake-app") as factory:
            with mock.patch("devlog.cli.main.uvicorn.run", side_effect=fake_run) as runner:
                code = main(["serve", "--host", "0.0.0.0", "--port", "9000"])

        self.assertEqual(code, 0)
        factory.assert_called_once_with(db_path=None)
        runner.assert_called_once()
        self.assertEqual(captured["app"], "fake-app")
        self.assertEqual(captured["host"], "0.0.0.0")
        self.assertEqual(captured["port"], 9000)

    def test_fresh_server_app_import_has_no_circular_import(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import devlog.server.app; print('server-ok')",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("server-ok", output)


class ReadmeTests(unittest.TestCase):
    def test_readme_contains_quick_start_commands(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        fragments = [
            "pip install -e .",
            "devlog --version",
            "devlog scan .",
            "devlog review generate --offline",
            "devlog serve",
            "pnpm dev",
            "python -m devlog.eval",
        ]
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
