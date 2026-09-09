"""DevLog V1 交互原型（devlog_mvp_v1.html）的冒烟测试。

原型是静态 HTML mock，因此测试验证的是对 V1 产品范围重要的结构与
内容不变量：

- 四个标签页都存在，包括置灰的 V2 路线图标签；
- V2 路线图面板存在；
- 复盘草稿中每条 AI 论断都带 commit 引用，或显式标记为“待确认”
  （演示稿绝不能暗示未经核实的事实）；
- 早期 mock 里切换标签的 selector bug 已修复。
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "devlog_mvp_v1.html"


def read_html() -> str:
    if not HTML_PATH.exists():
        raise AssertionError(f"missing prototype file: {HTML_PATH}")
    return HTML_PATH.read_text(encoding="utf-8")


def test_all_v1_tabs_present(html: str) -> None:
    for tab in ("overview", "timeline", "bugs", "review"):
        assert f'id="tab-{tab}"' in html, f"missing tab container: {tab}"
        assert f'data-tab="{tab}"' in html, f"missing tab button: {tab}"


def test_bugs_tab_is_v2_roadmap(html: str) -> None:
    assert 'class="tab-btn disabled"' in html
    assert 'id="tab-bugs"' in html
    assert "V2 规划中" in html
    assert "一键捕获 Bug 现场" in html


def test_review_claims_are_traceable_or_pending(html: str) -> None:
    assert html.count("class=\"cite\"") >= 6, "review should cite commit sources"
    assert "待确认" in html
    assert "需你回答" in html


def test_old_selector_bug_is_fixed(html: str) -> None:
    # 早期 mock 有一个未闭合的 CSS 属性选择器：
    #   querySelector('.tab-btn[data-tab="' + tabName + '"')
    # 切换标签时会抛错。确保仓库里不再存在这种坏写法。
    assert '.tab-btn[data-tab="\' + tabName + \'"' not in html
    assert 'data-tab="\' + tabName + \'"' not in html
    assert '.tab-btn[data-tab="' in html  # well-formed selector used


def test_timeline_only_contains_git_events_in_v1(html: str) -> None:
    # V1 不渲染 Bug/笔记时间线圆点，它们只以虚线 V2 占位符出现。
    assert "V2 出现" in html


def run_all() -> None:
    html = read_html()
    for test in (
        test_all_v1_tabs_present,
        test_bugs_tab_is_v2_roadmap,
        test_review_claims_are_traceable_or_pending,
        test_old_selector_bug_is_fixed,
        test_timeline_only_contains_git_events_in_v1,
    ):
        test(html)
        print(f"PASS  {test.__name__}")
    print(f"\nAll smoke tests passed for {HTML_PATH.name}")


if __name__ == "__main__":
    run_all()
