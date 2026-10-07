"""模块 8 冒烟测试：React 前端结构与生产构建。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "devlog" / "web"


def css_rule(styles: str, selector: str) -> str:
    """取出一个选择器的声明块。

    "文件里有这个选择器"太弱了：批注面板被挤扁时，选择器一直都在，是里面
    的 flex 声明在坏事。断言得落到声明块上。
    """

    marker = f"{selector} {{"
    start = styles.index(marker)
    return styles[start : styles.index("}", start)]


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
            "src/hooks/useTheme.ts",
            "src/components/SettingsDialog.tsx",
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
        # 选择框弹出在系统桌面上，页面上得留一句"去哪里找这个窗口"；
        # 但常态下不再解释"浏览是干什么的"，那是多余的一行字。
        self.assertIn("picking &&", page_text)
        self.assertIn("请到弹出的窗口里选", page_text)

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


class SourceListTests(unittest.TestCase):
    """来源展示：几十条 hash 不许铺在正文里，但可追溯性不能丢。"""

    def setUp(self) -> None:
        self.component = WEB_DIR / "src" / "components" / "SourceList.tsx"

    def test_shared_component_collapses_long_lists(self) -> None:
        self.assertTrue(self.component.exists(), "缺少共用的来源列表组件")
        text = self.component.read_text(encoding="utf-8")
        # 收起时只给短 hash，其余的折成一个可点的入口。
        self.assertIn("SHORT_LENGTH = 7", text)
        self.assertIn("VISIBLE_WHEN_COLLAPSED = 3", text)
        self.assertIn("等 {sources.length} 个提交", text)
        # 悬停要能看到完整 hash，否则折叠等于把来源弄丢了。
        self.assertIn("title={source}", text)

    def test_both_views_share_one_implementation(self) -> None:
        for relative in (
            "components/ClaimCard.tsx",
            "components/ReviewReadingView.tsx",
        ):
            with self.subTest(component=relative):
                text = (WEB_DIR / "src" / relative).read_text(encoding="utf-8")
                self.assertIn('from "./SourceList"', text)
                self.assertIn("<SourceList sources=", text)
                # 谁都不许再自己拼一份来源串出来。
                self.assertNotIn('join("、")', text)
                self.assertNotIn("slice(0, 7)", text)

    def test_source_toggle_has_its_own_style(self) -> None:
        styles = (WEB_DIR / "src" / "styles.css").read_text(encoding="utf-8")
        for selector in (".source-list", ".source-list code", ".source-toggle"):
            with self.subTest(selector=selector):
                self.assertIn(selector, styles)


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


class ThemeTests(unittest.TestCase):
    """明暗主题：开关在界面里，颜色全走变量，首屏不能闪。"""

    def test_toggle_is_wired_end_to_end(self) -> None:
        hook = (WEB_DIR / "src" / "hooks" / "useTheme.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn("devlog-theme", hook)
        self.assertIn("dataset.theme", hook)

        app_text = (WEB_DIR / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("useTheme", app_text)
        self.assertIn("toggleTheme", app_text)
        self.assertIn("topbar-actions", app_text)

        # 首屏由内联脚本定主题，否则会先闪一帧深色再变浅色
        index_text = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("dataset.theme", index_text)
        self.assertIn("theme-color", index_text)

    def test_light_theme_overrides_the_whole_palette(self) -> None:
        styles = (WEB_DIR / "src" / "styles.css").read_text(encoding="utf-8")
        marker = ':root[data-theme="light"]'
        self.assertIn(marker, styles, "缺少浅色主题的变量覆盖块")

        light_block = styles.split(marker, 1)[1]
        for token in ("color-scheme: light;", "--bg: #ffffff;", "--text: #1f2328;"):
            self.assertIn(token, light_block, f"浅色主题缺少 {token}")

        # 颜色字面量只能出现在变量定义里（--xxx: #hex / rgba(...)）。
        # 组件里写死一个颜色，浅色主题下就会花一块。
        leaked = [
            line.strip()
            for line in styles.splitlines()
            if (re.search(r"#[0-9a-fA-F]{3,8}\b", line) or "rgba(" in line)
            and not line.strip().startswith("--")
        ]
        self.assertEqual(leaked, [], f"仍有写死的颜色：{leaked}")

    def test_toolbar_controls_have_styles(self) -> None:
        styles = (WEB_DIR / "src" / "styles.css").read_text(encoding="utf-8")
        for selector in (".topbar-actions", ".icon-button", ".link-button"):
            self.assertIn(selector, styles, f"缺少样式：{selector}")


class LLMSettingsUiTests(unittest.TestCase):
    """大模型接入入口：填 key、测连通、保存，全在网页里完成。"""

    def test_api_bindings_exist(self) -> None:
        api_text = (WEB_DIR / "src" / "api.ts").read_text(encoding="utf-8")
        for name in ("updateLLMConfig", "testLLMConfig"):
            self.assertIn(f"export function {name}(", api_text)
        self.assertIn("/api/llm/config/test", api_text)

        types_text = (WEB_DIR / "src" / "types.ts").read_text(encoding="utf-8")
        for token in (
            "LLMConfigUpdate",
            "LLMConfigTestResult",
            "api_key_hint",
            "key_source",
            "clear_api_key",
        ):
            self.assertIn(token, types_text, f"类型缺少 {token}")

    def test_settings_dialog_is_safe_and_complete(self) -> None:
        dialog = (
            WEB_DIR / "src" / "components" / "SettingsDialog.tsx"
        ).read_text(encoding="utf-8")
        for token in (
            'type="password"',
            'autoComplete="off"',
            "测试连接",
            "clear_api_key",
            "updateLLMConfig",
            "testLLMConfig",
        ):
            self.assertIn(token, dialog, f"设置弹窗缺少 {token}")

    def test_topbar_opens_the_settings_dialog(self) -> None:
        app_text = (WEB_DIR / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("SettingsDialog", app_text)
        self.assertIn("onOpenSettings", app_text)
        # 存完密钥要让页面重新读一次配置，否则按钮还是灰的
        self.assertIn("llmVersion", app_text)

    def test_pages_point_at_the_dialog_instead_of_a_hand_edited_file(self) -> None:
        for name in ("ProjectPage.tsx", "TimelinePage.tsx"):
            text = (WEB_DIR / "src" / "pages" / name).read_text(encoding="utf-8")
            self.assertIn("onOpenSettings", text, f"{name} 没有设置入口")
            self.assertIn("去填写 API Key", text, f"{name} 缺少引导文案")
            # 让零基础用户自己去改 ~/.devlog/config.toml 是反人性的
            self.assertNotIn("config.toml", text, f"{name} 仍在让用户手改配置文件")


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


class TimelineOpenCardTests(unittest.TestCase):
    """展开的时间线卡片：批注输入框不许被挤成一条缝。

    卡片高度由时间线几何算出来写死在 maxHeight 上（约 214~334px），而展开
    后是正文 + 原文 + 批注表单，必然放不下。这个前提下只有两种写法：让整张
    卡片滚动，或者挑一个子元素压缩它。后者会把批注输入框压成一个十几像素的
    条，用户根本点不进去。
    """

    def setUp(self) -> None:
        self.styles = (WEB_DIR / "src" / "styles.css").read_text(encoding="utf-8")
        self.card = (
            WEB_DIR / "src" / "components" / "TimelineEventCard.tsx"
        ).read_text(encoding="utf-8")

    def test_expanded_card_scrolls_as_a_whole(self) -> None:
        self.assertIn("overflow-y: auto", css_rule(self.styles, ".tl-open"))

    def test_no_child_of_the_card_may_shrink(self) -> None:
        # 谁都不许被压缩，空间不够就整体滚动。
        for selector in (
            ".tl-card-head",
            ".tl-title",
            ".tl-body",
            ".tl-extra",
            ".tl-more",
            ".tl-card .annotation-panel",
        ):
            with self.subTest(selector=selector):
                self.assertIn("flex: none", css_rule(self.styles, selector))

    def test_annotation_panel_stops_being_the_shock_absorber(self) -> None:
        panel = css_rule(self.styles, ".tl-card .annotation-panel")
        self.assertNotIn("overflow-y: auto", panel)
        self.assertNotIn("min-height: 0", panel)

    def test_collapse_entry_stays_visible_while_the_card_scrolls(self) -> None:
        # 卡片内部滚动后，"收起"会被滚到看不见的地方，得钉在底部。
        more = css_rule(self.styles, "button.tl-more")
        self.assertIn("position: sticky", more)
        self.assertIn("bottom: 0", more)

    def test_connector_line_hangs_on_the_node_not_on_the_card(self) -> None:
        # 卡片一旦滚动就会裁剪溢出内容，挂在卡片上的伪元素会被一起裁掉，
        # 圆点和曲线之间那根短线就断了。
        self.assertNotIn(".tl-card::after", self.styles)
        for selector in (
            ".tl-node::before",
            ".tl-above .tl-node::before",
            ".tl-below .tl-node::before",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.styles)

    def test_only_the_expand_button_toggles_the_card(self) -> None:
        """整张卡片都能点是个多余的手感：会顺手把批注输入框的点击也吃掉。

        现在只有"展开 / 收起"这一个按钮能改状态，点正文、点批注区都不行。
        """

        self.assertIn('className="tl-more"', self.card)
        self.assertIn("onClick={onToggle}", self.card)
        self.assertIn("aria-expanded={open}", self.card)
        # 卡片本身不许再自称按钮，也不许再有 pointer 光标。
        self.assertNotIn('role="button"', self.card)
        self.assertNotIn("tl-clampable", self.card)
        self.assertNotIn("tl-clampable", self.styles)

    def test_expand_entry_is_a_real_button(self) -> None:
        # 用 div 冒充按钮，Tab 键永远停不到它上面，键盘用户就点不开卡片。
        self.assertIn("<button", self.card)
        self.assertIn('type="button"', self.card)
        self.assertIn("button.tl-more:focus-visible", self.styles)

    def test_drag_hint_points_at_the_button(self) -> None:
        # 提示语得和真实交互一致：整卡能点的时候写"点卡片展开"没问题，
        # 现在只有按钮能点，文案不改用户会去点正文，然后以为界面坏了。
        rail = (
            WEB_DIR / "src" / "components" / "TimelineRail.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("点卡片底部的「展开」", rail)


if __name__ == "__main__":
    unittest.main()
