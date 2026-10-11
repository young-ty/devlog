"""docs/technical-design.md 的冒烟测试。

保护设计阶段确定的关键工程决策：SQLite 仅作本地状态存储（永不作事实
来源）、Git 是事实来源、LLM 访问与供应商无关、前端用 React 而非
Gradio，以及复盘论断携带明确的来源/状态语义。

写成 unittest.TestCase 而不是模块级函数：`unittest discover` 收不到
后者，这两个文件以前一直没被 CI 跑到。
"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "technical-design.md"


class TechnicalDesignDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DOC_PATH.exists():
            raise AssertionError(f"missing technical design doc: {DOC_PATH}")
        cls.doc = DOC_PATH.read_text(encoding="utf-8")

    def test_architecture_decision_present(self) -> None:
        for token in ("Git 是真相", "SQLite 是缓存/状态库", "~/.devlog/devlog.db"):
            self.assertIn(token, self.doc)

    def test_tech_stack_present(self) -> None:
        # 断言实际在用的选型：解析层是标准库 argparse，测试是标准库 unittest。
        # 初版计划里的 Typer / pytest 没有采用，文档里作为决策记录保留即可。
        for tech in ("FastAPI", "argparse", "React", "DeepSeek", "Pydantic", "unittest"):
            self.assertIn(tech, self.doc, f"missing tech choice: {tech}")
        self.assertTrue(
            "替代 Gradio" in self.doc or "Gradio" not in self.doc,
            "Gradio 只能作为被替代的方案出现",
        )

    def test_llm_abstraction_present(self) -> None:
        for token in ("provider 抽象", "LLMClient"):
            self.assertIn(token, self.doc)

    def test_claim_source_and_status_model_present(self) -> None:
        for token in ("review_claims", "sources_json", "ai_pending", "confirmed"):
            self.assertIn(token, self.doc)

    def test_storage_boundary_and_migration_present(self) -> None:
        for token in ("user_version", "docs/retrospectives/"):
            self.assertIn(token, self.doc)
        self.assertTrue(
            "不进" in self.doc or "不放进" in self.doc or "避免污染" in self.doc,
            "文档要写明草稿不进 Git 仓库",
        )

    def test_final_document_rules_have_one_implementation(self) -> None:
        """界面和 Markdown 导出必须共用同一份成稿规则，否则排版会各自漂移。"""

        for token in ("devlog/core/review/document.py", "共用", "定稿"):
            self.assertIn(token, self.doc)

    def test_day_digest_rules_present(self) -> None:
        """当日小结的两个关键口径：按本机时区算一天、不调模型。"""

        for token in ("devlog/core/digest/day.py", "本机时区", "has_cached_commits"):
            self.assertIn(token, self.doc)


if __name__ == "__main__":
    unittest.main()
