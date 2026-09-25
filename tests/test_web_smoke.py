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
            "src/pages/NotesPage.tsx",
            "src/pages/BugsPage.tsx",
        ):
            self.assertTrue(
                (WEB_DIR / relative).exists(),
                f"missing frontend source: {relative}",
            )

        package_text = (WEB_DIR / "package.json").read_text(encoding="utf-8")
        self.assertIn('"vite"', package_text)
        self.assertIn('"react"', package_text)

        app_text = (WEB_DIR / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("import { NotesPage }", app_text)
        self.assertIn("import { BugsPage }", app_text)

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

        timeline_text = (
            WEB_DIR / "src" / "pages" / "TimelinePage.tsx"
        ).read_text(encoding="utf-8")
        for function_name in (
            "listAnnotations",
            "addAnnotation",
            "deleteAnnotation",
        ):
            self.assertIn(
                function_name,
                timeline_text,
                f"timeline page missing annotation call: {function_name}",
            )

    def test_timeline_stream_bindings_exist(self) -> None:
        """横向时间线要能同时表现提交、Bug、笔记、批注、空档。"""

        for relative in (
            "src/components/Icons.tsx",
            "src/components/AnnotationPanel.tsx",
            "src/components/TimelineEventCard.tsx",
            "src/components/TimelineRail.tsx",
            "src/hooks/useDragPan.ts",
        ):
            self.assertTrue(
                (WEB_DIR / relative).exists(),
                f"missing timeline source: {relative}",
            )

        api_text = (WEB_DIR / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("export function getProjectTimelineEvents(", api_text)
        self.assertIn("/timeline-events", api_text)

        types_text = (WEB_DIR / "src" / "types.ts").read_text(encoding="utf-8")
        for type_name in ("TimelineEventKind", "TimelineEvent", "TimelineStream"):
            self.assertIn(type_name, types_text, f"missing type: {type_name}")

        rail_text = (
            WEB_DIR / "src" / "components" / "TimelineRail.tsx"
        ).read_text(encoding="utf-8")
        # 拖动、缩略导航、筛选是"好翻看"的三根支柱，缺一个页面就退化了。
        self.assertIn("useDragPan", rail_text)
        self.assertIn("tl-mm-track", rail_text)
        self.assertIn("tl-chip", rail_text)
        # 筛选项要带数量：切到"本项目一条都没有"的类型时，卡片会全部变淡，
        # 没有数字用户会以为界面坏了。
        self.assertIn("tl-chip-count", rail_text)
        self.assertIn("kindCounts", rail_text)

        styles_text = (WEB_DIR / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".tl-chip-count", styles_text)
        self.assertIn(".tl-chip-empty", styles_text)

        page_text = (
            WEB_DIR / "src" / "pages" / "TimelinePage.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("TimelineRail", page_text)
        self.assertIn("getProjectTimelineEvents", page_text)
        # 时间线板块必须紧跟在统计卡后面。主题分组有几十个主题、很长，
        # 排在它后面等于用户根本翻不到，这一轮就是这么被漏发现的。
        self.assertLess(
            page_text.index("<TimelineRail"),
            page_text.index("主题分组"),
            "时间线板块被排到了主题分组后面，用户要滚很久才能看到",
        )

    def test_directory_picker_bindings_exist(self) -> None:
        api_text = (WEB_DIR / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("export function pickDirectory(", api_text)
        self.assertIn("/api/system/pick-directory", api_text)

        types_text = (WEB_DIR / "src" / "types.ts").read_text(encoding="utf-8")
        self.assertIn("DirectoryPickResult", types_text)

        utils_text = (WEB_DIR / "src" / "utils.ts").read_text(encoding="utf-8")
        self.assertIn("export function folderName(", utils_text)

        page_text = (
            WEB_DIR / "src" / "pages" / "ProjectsPage.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("pickDirectory", page_text)
        self.assertIn("浏览", page_text)
        self.assertIn("is_git_repo", page_text)

    def test_guidance_answer_bindings_exist(self) -> None:
        api_text = (WEB_DIR / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("export function saveAnswer(", api_text)
        self.assertIn("/answers/", api_text)

        types_text = (WEB_DIR / "src" / "types.ts").read_text(encoding="utf-8")
        self.assertIn("ReviewQuestion", types_text)
        self.assertIn("questions: ReviewQuestion[]", types_text)

        page_text = (
            WEB_DIR / "src" / "pages" / "ReviewPage.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("saveAnswer", page_text)
        self.assertIn("<textarea", page_text)
        self.assertIn("保存回答", page_text)

    def test_asset_discoverability_bindings_exist(self) -> None:
        """可复用资产归纳必须能在界面上被看出来跑没跑。"""

        types_text = (WEB_DIR / "src" / "types.ts").read_text(encoding="utf-8")
        self.assertIn("asset_count", types_text)
        self.assertIn("generation_mode", types_text)

        project_text = (
            WEB_DIR / "src" / "pages" / "ProjectPage.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("可复用资产候选", project_text)
        self.assertIn("不会归纳资产", project_text)

        review_text = (
            WEB_DIR / "src" / "pages" / "ReviewPage.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("SECTION_ORDER", review_text)
        self.assertIn("emptySectionHint", review_text)
        self.assertIn("本次 AI 归纳没有找到", review_text)
        self.assertIn("由旧版本生成", review_text)

    def test_review_delete_bindings_exist(self) -> None:
        api_text = (WEB_DIR / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("export function deleteReview(", api_text)

        project_text = (
            WEB_DIR / "src" / "pages" / "ProjectPage.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("deleteReview", project_text)
        self.assertIn("handleDeleteReview", project_text)
        self.assertIn("旧版本", project_text)
        self.assertIn("window.confirm", project_text)

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
