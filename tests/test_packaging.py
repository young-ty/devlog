"""打包元数据、版本、serve 命令与 README 的测试。"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from devlog import __version__
from devlog.cli import doctor
from devlog.cli.main import browser_url, build_parser, main


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

    def test_packaging_extra_is_optional_not_runtime(self) -> None:
        """PyInstaller 只服务打包，不该混进运行时依赖。"""

        extras = self.metadata["project"]["optional-dependencies"]
        self.assertIn("package", extras)
        joined = "\n".join(extras["package"])
        self.assertIn("pyinstaller==", joined)
        self.assertNotIn("pyinstaller", "\n".join(self.metadata["project"]["dependencies"]))

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
        self.assertFalse(args.open_browser)

    def test_serve_open_flag_is_opt_in(self) -> None:
        args = build_parser().parse_args(["serve", "--open"])
        self.assertTrue(args.open_browser)

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

    def test_serve_with_open_flag_schedules_browser_open(self) -> None:
        with mock.patch("devlog.cli.main.create_app", return_value="fake-app"):
            with mock.patch("devlog.cli.main.uvicorn.run"):
                with mock.patch(
                    "devlog.cli.main.schedule_browser_open"
                ) as browser:
                    code = main(["serve", "--port", "9123", "--open"])

        self.assertEqual(code, 0)
        browser.assert_called_once_with("http://127.0.0.1:9123")

    def test_serve_without_open_flag_does_not_touch_browser(self) -> None:
        with mock.patch("devlog.cli.main.create_app", return_value="fake-app"):
            with mock.patch("devlog.cli.main.uvicorn.run"):
                with mock.patch(
                    "devlog.cli.main.schedule_browser_open"
                ) as browser:
                    code = main(["serve"])

        self.assertEqual(code, 0)
        browser.assert_not_called()

    def test_browser_url_maps_wildcard_host_to_loopback(self) -> None:
        self.assertEqual(browser_url("0.0.0.0", 8000), "http://127.0.0.1:8000")
        self.assertEqual(browser_url("::", 8000), "http://127.0.0.1:8000")
        self.assertEqual(browser_url("127.0.0.1", 9123), "http://127.0.0.1:9123")

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


class LauncherScriptTests(unittest.TestCase):
    """一键启动脚本必须存在、可被双击，并复用统一的 serve 入口。"""

    def setUp(self) -> None:
        self.script = ROOT / "start-devlog.bat"

    def test_launcher_exists(self) -> None:
        self.assertTrue(self.script.is_file())

    def test_launcher_reuses_devlog_serve(self) -> None:
        text = self.script.read_text(encoding="utf-8")
        self.assertIn("devlog.exe\" serve --open", text)
        self.assertIn(".venv\\Scripts\\devlog.exe", text)

    def test_launcher_builds_frontend_when_dist_missing(self) -> None:
        text = self.script.read_text(encoding="utf-8")
        self.assertIn("devlog\\web\\dist\\index.html", text)
        self.assertIn("pnpm build", text)

    def test_launcher_uses_crlf_and_has_no_bom(self) -> None:
        """cmd.exe 对 LF 换行和 UTF-8 BOM 都很敏感，这里钉住文件格式。"""

        raw = self.script.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))


class ServeOneLinerDocsTests(unittest.TestCase):
    def test_readme_documents_launcher_script(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("start-devlog.bat", text)
        self.assertIn("127.0.0.1:8000", text)


class FrozenEntryTests(unittest.TestCase):
    """打包成 exe 之后，双击（没有参数）应该直接可用。"""

    def test_frozen_exe_without_args_serves_and_opens_browser(self) -> None:
        with mock.patch.object(sys, "argv", ["DevLog.exe"]):
            with mock.patch.object(sys, "frozen", True, create=True):
                with mock.patch(
                    "devlog.cli.main.create_app", return_value="fake-app"
                ):
                    with mock.patch("devlog.cli.main.uvicorn.run") as uvicorn_run:
                        with mock.patch(
                            "devlog.cli.main.schedule_browser_open"
                        ) as browser:
                            code = main()

        self.assertEqual(code, 0)
        browser.assert_called_once_with("http://127.0.0.1:8000")
        uvicorn_run.assert_called_once()

    def test_source_run_without_args_still_reports_usage(self) -> None:
        """没打包时不能悄悄变成 serve：脚本里敲 `devlog` 就该提示用法。"""

        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", ["devlog"]):
            with contextlib.redirect_stderr(buffer):
                with self.assertRaises(SystemExit) as context:
                    main()
        self.assertEqual(context.exception.code, 2)


class DoctorCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "doctor.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_report_covers_every_prerequisite(self) -> None:
        buffer = io.StringIO()
        code = doctor.run_doctor(self.db_path, stream=buffer)
        text = buffer.getvalue()

        for fragment in (
            "前端产物",
            "文件夹选择框",
            "Git",
            "状态数据库",
            "大模型",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)
        # 仓库里前端产物是构建好的，所以这里应当是"健康"的
        self.assertEqual(code, 0)
        self.assertIn(f"schema v", text)

    def test_missing_frontend_marks_report_unhealthy(self) -> None:
        with mock.patch(
            "devlog.cli.doctor.resolve_web_dist", return_value=None
        ):
            lines, healthy = doctor.build_report(self.db_path)
        self.assertFalse(healthy)
        self.assertTrue(any("前端产物" in line for line in lines))

    def test_missing_git_marks_report_unhealthy(self) -> None:
        with mock.patch("devlog.cli.doctor.shutil.which", return_value=None):
            lines, healthy = doctor.build_report(self.db_path)
        self.assertFalse(healthy)
        self.assertTrue(any("Git" in line for line in lines))

    def test_unconfigured_llm_is_only_a_warning(self) -> None:
        with mock.patch(
            "devlog.cli.doctor.llm_settings",
            return_value={"configured": "false", "model": "x", "base_url": "y"},
        ):
            lines, healthy = doctor.build_report(self.db_path)
        self.assertTrue(healthy)
        self.assertTrue(any("--offline" in line for line in lines))

    def test_cli_exposes_doctor_command(self) -> None:
        args = build_parser().parse_args(["doctor"])
        self.assertEqual(args.command, "doctor")

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--db", str(self.db_path), "doctor"])
        self.assertEqual(code, 0)
        self.assertIn("DevLog 自检", buffer.getvalue())

    def test_broken_database_marks_report_unhealthy(self) -> None:
        broken = Path(self.tmp.name) / "broken.db"
        broken.write_bytes(b"not a sqlite database at all")
        buffer = io.StringIO()
        code = doctor.run_doctor(broken, stream=buffer)
        self.assertEqual(code, 1)
        self.assertIn("数据库", buffer.getvalue())


class PyInstallerBuildTests(unittest.TestCase):
    """打包配置本身也要有测试：它坏了没人会发现。"""

    def test_spec_bundles_frontend_and_uvicorn_submodules(self) -> None:
        text = (ROOT / "packaging" / "devlog.spec").read_text(encoding="utf-8")
        self.assertIn('"devlog/web/dist"', text)
        self.assertIn('collect_submodules("uvicorn")', text)
        self.assertIn('name="DevLog"', text)
        self.assertIn('console=True', text)

    def test_build_script_reuses_spec_and_checks_output(self) -> None:
        script = ROOT / "build-app.bat"
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        self.assertIn("packaging\\devlog.spec", text)
        self.assertIn("dist\\DevLog.exe", text)
        self.assertIn("pnpm build", text)

    def test_build_script_uses_crlf_and_has_no_bom(self) -> None:
        raw = (ROOT / "build-app.bat").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))

    def test_readme_documents_packaging(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("build-app.bat", text)
        self.assertIn("dist\\DevLog.exe", text)
        self.assertIn("devlog doctor", text)


if __name__ == "__main__":
    unittest.main()
