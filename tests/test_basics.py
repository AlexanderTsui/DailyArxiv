from __future__ import annotations

import shutil
from pathlib import Path

from dailyarxiv.archivist_sqlite import ArchivistSQLite
from dailyarxiv.arxiv_client import apply_keyword_heuristics
from dailyarxiv.models import DailyReport, PaperAnalysis, PaperCandidate, RelevanceJudgement
from dailyarxiv.render.renderer import render_report_html
from dailyarxiv.trends import build_bar_keywords


def _candidate(pid: str, title: str, abstract: str) -> PaperCandidate:
    return PaperCandidate(
        id=pid,
        title_en=title,
        authors=["A", "B", "C"],
        url=f"https://arxiv.org/abs/{pid}",
        publish_date="2026-02-18T12:00:00+00:00",
        categories=["cs.CL"],
        primary_category="cs.CL",
        abstract=abstract,
    )


def _analysis(pid: str) -> PaperAnalysis:
    rel = RelevanceJudgement(is_relevant=True, relevance_score=80, matched_terms=["rag"], reason_cn="相关")
    return PaperAnalysis(
        id=pid,
        title_en="Test Paper",
        title_cn="测试论文",
        authors=["A", "B", "C"],
        url=f"https://arxiv.org/abs/{pid}",
        publish_date="2026-02-18T12:00:00+00:00",
        primary_category="cs.CL",
        motivation="痛点",
        method="Method uses RAG and KV-Cache.",
        paradigm_relation="Incremental",
        score=4,
        relevance=rel,
    )


def test_apply_keyword_heuristics_include_exclude() -> None:
    c1 = _candidate("2502.1", "RAG paper", "We study retrieval augmented generation.")
    c2 = _candidate("2502.2", "Survey paper", "This is a survey of RAG.")
    kept = apply_keyword_heuristics([c1, c2], include=["rag"], exclude=["survey"])
    assert [c.id for c in kept] == ["2502.1"]


def test_build_bar_keywords_normalized() -> None:
    a1 = _analysis("2502.1")
    a2 = _analysis("2502.2")
    a2.method = "KV-Cache improves RAG."
    kws = build_bar_keywords([a1, a2], top_k=10)
    assert kws
    assert 0.0 < kws[0].weight <= 1.0
    assert all(0.0 < k.weight <= 1.0 for k in kws)


def test_sqlite_archive_roundtrip() -> None:
    work = Path("pytest_work_sqlite")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    db = work / "dailyarxiv.sqlite"
    arch = ArchivistSQLite(db)
    run_id = arch.begin_run(
        report_date="2026-02-18",
        generated_at="2026-02-19T08:00:00+00:00",
        source_range_start="2026-02-18T00:00:00+00:00",
        source_range_end="2026-02-18T23:59:59+00:00",
        categories=["cs.CL"],
        keywords=["rag"],
        counts={"candidates": 1, "selected": 1},
    )
    c = _candidate("2502.1", "RAG paper", "We study retrieval augmented generation.")
    arch.write_candidates(run_id, [c])

    j = RelevanceJudgement(is_relevant=True, relevance_score=90, matched_terms=["rag"], reason_cn="相关")
    arch.write_judgements(run_id, {"2502.1": j})

    a = _analysis("2502.1")
    arch.write_analyses(run_id, [a])

    report = DailyReport(
        date="2026-02-18",
        generated_at="2026-02-19T08:00:00+00:00",
        source_range_start="2026-02-18T00:00:00+00:00",
        source_range_end="2026-02-18T23:59:59+00:00",
        domain="Computer Science",
        categories=["cs.CL"],
        keywords=["rag"],
        global_trend="trend",
        papers=[a],
        weekly_trend=None,
        monthly_trend=None,
        spotlight=[],
    )
    arch.write_daily_report(run_id, report)

    exported = arch.export_report(date="2026-02-18")
    assert exported["date"] == "2026-02-18"
    assert exported["papers"][0]["id"] == "2502.1"
    shutil.rmtree(work, ignore_errors=True)


def test_render_html() -> None:
    work = Path("pytest_work_render")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    a = _analysis("2502.1")
    report = DailyReport(
        date="2026-02-18",
        generated_at="2026-02-19T08:00:00+00:00",
        source_range_start="2026-02-18T00:00:00+00:00",
        source_range_end="2026-02-18T23:59:59+00:00",
        domain="Computer Science",
        categories=["cs.CL"],
        keywords=["rag"],
        global_trend="trend",
        papers=[a],
        weekly_trend=None,
        monthly_trend=None,
        spotlight=[],
    )
    out = work / "report.html"
    render_report_html(report.model_dump(), out)
    html = out.read_text(encoding="utf-8")
    assert "精选论文" in html
    assert "Global Trend" in html
    assert "arXiv:2502.1" in html
    shutil.rmtree(work, ignore_errors=True)
