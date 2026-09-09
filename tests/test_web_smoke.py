"""模块 8 冒烟测试：React 前端结构与生产构建。"""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "devlog" / "web"


class WebSmokeTests(unittest.TestCase):
    def test_frontend_sources_exist(self) -> None:
        for relative in (
            "package.json",
            "vite.config.ts",
            "index.html",
            "src/main.tsx",
            "src/App.tsx",
            "src/api.ts",
            "src/types.ts",
            "src/pages/ProjectsPage.tsx",
            "src/pages/ProjectPage.tsx",
            "src/pages/ReviewPage.tsx",
            "src/pages/TimelinePage.tsx",
        ):
            self.assertTrue(
                (WEB_DIR / relative).exists(),
                f"missing frontend source: {relative}",
            )

        package_text = (WEB_DIR / "package.json").read_text(encoding="utf-8")
        self.assertIn('"vite"', package_text)
        self.assertIn('"react"', package_text)

    def test_memory_layer_api_bindings_exist(self) -> None:
        api_text = (WEB_DIR / "src" / "api.ts").read_text(encoding="utf-8")
        for function_name in (
            "listDailyNotes",
            "saveDailyNote",
            "listBugs",
            "captureBug",
            "updateBug",
            "deleteBug",
            "suggestBugTitle",
            "listAnnotations",
            "addAnnotation",
            "updateAnnotation",
            "deleteAnnotation",
        ):
            self.assertIn(
                f"export function {function_name}(",
                api_text,
                f"missing api wrapper: {function_name}",
            )

        types_text = (WEB_DIR / "src" / "types.ts").read_text(encoding="utf-8")
        for type_name in (
            "DailyNote",
            "BugRecord",
            "BugStatus",
            "CommitAnnotation",
            "AnnotationKind",
        ):
            self.assertIn(
                type_name,
                types_text,
                f"missing memory type: {type_name}",
            )

    def test_production_build_passes(self) -> None:
        if shutil.which("pnpm") is None:
            self.skipTest("pnpm is not available in this environment")

        command = (
            ["cmd", "/c", "pnpm build"]
            if os.name == "nt"
            else ["pnpm", "build"]
        )
        result = subprocess.run(
            command,
            cwd=WEB_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("built in", output)


if __name__ == "__main__":
    unittest.main()
