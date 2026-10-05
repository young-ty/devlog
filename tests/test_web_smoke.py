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


class ReviewReadingViewBindingsTests(unittest.TestCase):
    """复盘页要有「成稿阅读」视图，并且收录规则不许在前端再写一份。"""

    def test_reading_view_component_and_api_exist(self) -> None:
        self.assertTrue(
            (WEB_DIR / "src" / "components" / "ReviewReadingView.tsx").exists(),
            "缺少成稿阅读视图组件",
        )
        api_text = (WEB_DIR / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("export function getReviewDocument(", api_text)
        self.assertIn("/document", api_text)
        types_text = (WEB_DIR / "src" / "types.ts").read_text(encoding="utf-8")
        for type_name in ("FinalDocument", "FinalSection", "FinalClaim"):
            self.assertIn(type_name, types_text, f"missing type: {type_name}")

    def test_reading_view_opens_by_default(self) -> None:
        page_text = (WEB_DIR / "src" / "pages" / "ReviewPage.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("ReviewReadingView", page_text)
        self.assertIn("getReviewDocument", page_text)
        # 复盘首先是拿来读的：默认进阅读视图，校对是过程不是结果。
        self.assertIn('useState<"read" | "proof">("read")', page_text)
        # 成稿视图不提供编辑入口，免得读的时候手滑改坏论断。
        reading_text = (
            WEB_DIR / "src" / "components" / "ReviewReadingView.tsx"
        ).read_text(encoding="utf-8")
        self.assertNotIn("onConfirm", reading_text)
        self.assertIn("rv-pending-bar", reading_text)

    def test_reading_view_styles_exist(self) -> None:
        styles = (WEB_DIR / "src" / "styles.css").read_text(encoding="utf-8")
        for selector in (".rv-layout", ".rv-toc", ".rv-pending-bar", ".rv-qa"):
            self.assertIn(selector, styles, f"missing style: {selector}")

    def test_finalize_bindings_exist(self) -> None:
        """定稿是一个可撤回的标记，界面和接口都得有。"""

        api_text = (WEB_DIR / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("export function finalizeReview(", api_text)
        self.assertIn("/finalize", api_text)

        page_text = (WEB_DIR / "src" / "pages" / "ReviewPage.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("handleFinalize", page_text)
        self.assertIn("定稿并归档", page_text)
        # 撤回入口必须和定稿入口同时存在，否则用户会被"定死"在一份稿上。
        self.assertIn("撤回定稿", page_text)

        project_text = (
            WEB_DIR / "src" / "pages" / "ProjectPage.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn('review.status === "finalized"', project_text)

        styles = (WEB_DIR / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".rv-badge-done", styles)
        self.assertIn(".badge-finalized", styles)


class VisualToneTests(unittest.TestCase):
    """界面观感约束：不用生成式模板那套发光、毛玻璃和循环动画。

    这些效果本身没错，但它们组合起来会让一个本地开发工具看起来像 AI
    生成的演示页，也让人怀疑里面有多少是真东西。约束写进测试，避免以后
    顺手又把光晕加回来。
    """

    def setUp(self) -> None:
        self.styles = (WEB_DIR / "src" / "styles.css").read_text(
            encoding="utf-8"
        )

    def test_no_decorative_glow_background(self) -> None:
        self.assertNotIn("radial-gradient", self.styles)

    def test_topbar_is_opaque_instead_of_frosted_glass(self) -> None:
        self.assertNotIn("backdrop-filter", self.styles)

    def test_no_endless_loading_animation(self) -> None:
        self.assertNotIn("infinite", self.styles)
        self.assertNotIn("@keyframes", self.styles)

    def test_panel_radius_stays_tool_like(self) -> None:
        self.assertIn("--radius: 8px;", self.styles)


class DayDigestBindingTests(unittest.TestCase):
    """每日复盘页要先把"当天都发生了什么"摆出来，再让人动笔。"""

    def test_api_binding_exists(self) -> None:
        api_text = (WEB_DIR / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn("export function getDayDigest(", api_text)
        self.assertIn("/digest", api_text)

        types_text = (WEB_DIR / "src" / "types.ts").read_text(encoding="utf-8")
        self.assertIn("export interface DayDigest", types_text)
        self.assertIn("has_cached_commits", types_text)

    def test_notes_page_shows_the_digest(self) -> None:
        page_text = (WEB_DIR / "src" / "pages" / "NotesPage.tsx").read_text(
            encoding="utf-8"
        )
        for token in (
            "getDayDigest",
            "当天都发生了什么",
            "用提交记录起草",
            "扫描最新提交",
            "digest-row",
            "draft_text",
        ):
            self.assertIn(token, page_text)

    def test_digest_styles_exist(self) -> None:
        styles = (WEB_DIR / "src" / "styles.css").read_text(encoding="utf-8")
        for selector in (".digest-stats", ".digest-list", ".digest-row"):
            self.assertIn(selector, styles, f"missing style: {selector}")

    def test_bugs_can_be_opened_from_the_digest(self) -> None:
        """当天小结里看到的 Bug 要能点回 Bug 页，并定位到那一条。"""

        app_text = (WEB_DIR / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("focusBugId", app_text)
        self.assertIn("onOpenBug", app_text)

        notes_text = (WEB_DIR / "src" / "pages" / "NotesPage.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("onOpenBug(bug.id)", notes_text)
        self.assertIn("digest-row-link", notes_text)

        bugs_text = (WEB_DIR / "src" / "pages" / "BugsPage.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("focusBugId", bugs_text)
        self.assertIn("scrollIntoView", bugs_text)
        self.assertIn("bug-card-focus", bugs_text)

        styles = (WEB_DIR / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".bug-card-focus", styles)


if __name__ == "__main__":
    unittest.main()
