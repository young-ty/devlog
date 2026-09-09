"""docs/product-design.md 的冒烟测试。

设计文档是产品范围的唯一事实来源，因此这些检查防止核心 V1 决策
（零侵入 Git 数据源、人机共创复盘、论断可追溯、V2/V3 边界）被误删。
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "product-design.md"


def read_doc() -> str:
    if not DOC_PATH.exists():
        raise AssertionError(f"missing design doc: {DOC_PATH}")
    return DOC_PATH.read_text(encoding="utf-8")


def test_positioning_and_principles_present(doc: str) -> None:
    assert "唯一事实来源" in doc
    assert "有据可查" in doc
    assert "人机共创" in doc
    assert "待确认" in doc


def test_v1_flow_present(doc: str) -> None:
    assert "选择 Git 仓库与时间范围" in doc
    assert "导出 Markdown" in doc


def test_main_modules_present(doc: str) -> None:
    for module in ("M1 项目接入与事件建模", "M2 AI 复盘生成流水线", "M3 复盘文档管理与编辑", "M4 离线评测集"):
        assert module in doc, f"missing module heading: {module}"


def test_roadmap_boundaries_present(doc: str) -> None:
    assert "V2" in doc and "一键捕获" in doc
    assert "V3" in doc and "踩坑知识库" in doc
    assert "非目标" in doc


def run_all() -> None:
    doc = read_doc()
    for test in (
        test_positioning_and_principles_present,
        test_v1_flow_present,
        test_main_modules_present,
        test_roadmap_boundaries_present,
    ):
        test(doc)
        print(f"PASS  {test.__name__}")
    print(f"\nAll smoke tests passed for {DOC_PATH.name}")


if __name__ == "__main__":
    run_all()
