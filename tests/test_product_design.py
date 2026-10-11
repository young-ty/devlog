"""docs/product-design.md 的冒烟测试。

设计文档是产品范围的唯一事实来源，因此这些检查防止核心 V1 决策
（零侵入 Git 数据源、人机共创复盘、论断可追溯、V2/V3 边界）被误删。

写成 unittest.TestCase 而不是模块级函数：`unittest discover` 收不到
后者，这两个文件以前一直没被 CI 跑到。
"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "product-design.md"


class ProductDesignDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DOC_PATH.exists():
            raise AssertionError(f"missing design doc: {DOC_PATH}")
        cls.doc = DOC_PATH.read_text(encoding="utf-8")

    def test_positioning_and_principles_present(self) -> None:
        for token in ("唯一事实来源", "有据可查", "人机共创", "待确认"):
            self.assertIn(token, self.doc)

    def test_v1_flow_present(self) -> None:
        for token in ("选择 Git 仓库与时间范围", "导出 Markdown"):
            self.assertIn(token, self.doc)

    def test_main_modules_present(self) -> None:
        for module in (
            "M1 项目接入与事件建模",
            "M2 AI 复盘生成流水线",
            "M3 复盘文档管理与编辑",
            "M4 离线评测集",
        ):
            self.assertIn(module, self.doc, f"missing module heading: {module}")

    def test_roadmap_boundaries_present(self) -> None:
        self.assertIn("V2", self.doc)
        self.assertIn("一键捕获", self.doc)
        # 知识库已经移出范围：路线图上要能看出这件事是有意为之，
        # 而不是被谁悄悄删掉了。
        self.assertIn("V3", self.doc)
        self.assertIn("复盘成稿", self.doc)
        self.assertIn("移出本项目范围", self.doc)
        self.assertIn("非目标", self.doc)


if __name__ == "__main__":
    unittest.main()
