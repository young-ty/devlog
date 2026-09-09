"""docs/technical-design.md 的冒烟测试。

保护设计阶段确定的关键工程决策：SQLite 仅作本地状态存储（永不作事实
来源）、Git 是事实来源、LLM 访问与供应商无关、前端用 React 而非
Gradio，以及复盘论断携带明确的来源/状态语义。
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "technical-design.md"


def read_doc() -> str:
    if not DOC_PATH.exists():
        raise AssertionError(f"missing technical design doc: {DOC_PATH}")
    return DOC_PATH.read_text(encoding="utf-8")


def test_architecture_decision_present(doc: str) -> None:
    assert "Git 是真相" in doc
    assert "SQLite 是缓存/状态库" in doc
    assert "~/.devlog/devlog.db" in doc


def test_tech_stack_present(doc: str) -> None:
    for tech in ("FastAPI", "Typer", "React", "DeepSeek", "Pydantic", "pytest"):
        assert tech in doc, f"missing tech choice: {tech}"
    assert "替代 Gradio" in doc or "Gradio" not in doc


def test_llm_abstraction_present(doc: str) -> None:
    assert "provider 抽象" in doc
    assert "LLMClient" in doc


def test_claim_source_and_status_model_present(doc: str) -> None:
    assert "review_claims" in doc
    assert "sources_json" in doc
    assert "ai_pending" in doc
    assert "confirmed" in doc


def test_storage_boundary_and_migration_present(doc: str) -> None:
    assert "user_version" in doc
    assert "docs/retrospectives/" in doc
    assert "不进" in doc or "不放进" in doc or "避免污染" in doc


def run_all() -> None:
    doc = read_doc()
    for test in (
        test_architecture_decision_present,
        test_tech_stack_present,
        test_llm_abstraction_present,
        test_claim_source_and_status_model_present,
        test_storage_boundary_and_migration_present,
    ):
        test(doc)
        print(f"PASS  {test.__name__}")
    print(f"\nAll smoke tests passed for {DOC_PATH.name}")


if __name__ == "__main__":
    run_all()
