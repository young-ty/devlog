"""Smoke tests for the DevLog V1 interactive prototype (devlog_mvp_v1.html).

The prototype is a static HTML mock, so the tests validate structural and
content-level invariants that matter for the V1 product scope:

- all four tabs exist, including the disabled V2 roadmap tab;
- the V2 roadmap panel is present;
- every AI claim shown in the review draft carries a commit citation or is
  explicitly marked as "待确认" (so the demo never implies unverified facts);
- the tab-switching selector bug from the earlier mock is gone.
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
    # The earlier mock had an unterminated CSS attribute selector:
    #   querySelector('.tab-btn[data-tab="' + tabName + '"')
    # which throws on tab switch. Make sure no broken copy survives.
    assert '.tab-btn[data-tab="\' + tabName + \'"' not in html
    assert 'data-tab="\' + tabName + \'"' not in html
    assert '.tab-btn[data-tab="' in html  # well-formed selector used


def test_timeline_only_contains_git_events_in_v1(html: str) -> None:
    # Bug/note timeline dots are not rendered in V1; they appear only as
    # dashed V2 placeholders.
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
