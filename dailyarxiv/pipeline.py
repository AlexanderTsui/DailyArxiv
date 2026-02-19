from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

from .archivist_sqlite import ArchivistSQLite
from .arxiv_client import apply_keyword_heuristics, harvest_candidates
from .config import Settings
from .llm_client import LLMClient
from .models import DailyReport, PaperAnalysis, PaperCandidate, PeriodTrend
from .render.renderer import render_report_html
from .render.weasyprint_renderer import render_html_to_pdf_if_available
from .trends import build_bar_keywords, summarize_period_trend


def run_pipeline(
    settings: Settings,
    out_root: Path,
    date_arg: str,
    max_results: int | None,
    max_selected: int | None,
    dry_run: bool,
    html_only: bool,
    pdf_only: bool,
) -> dict[str, Any]:
    tz = ZoneInfo(settings.search.timezone)
    generated_at = datetime.now(tz).isoformat()

    max_results_eff = max_results or settings.search.max_results
    max_selected_eff = max_selected or settings.filter.max_selected

    harvest = harvest_candidates(
        categories=settings.search.categories,
        timezone=settings.search.timezone,
        mode=settings.search.mode,
        time_window_hours=settings.search.time_window_hours,
        lookback_days=settings.search.lookback_days,
        max_results=max_results_eff,
        date_override=None if date_arg == "auto" else date_arg,
    )
    report_date = harvest.report_date

    out_dir = out_root / report_date
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = Path("dailyarxiv.sqlite")
    arch = ArchivistSQLite(db_path)

    candidates = harvest.candidates
    candidates = apply_keyword_heuristics(
        candidates, settings.search.keywords_include, settings.search.keywords_exclude
    )

    debug_candidates_path = out_dir / "debug_candidates.json"
    debug_payload: dict[str, Any] = {
        "report_date": report_date,
        "generated_at": generated_at,
        "source_range_start": harvest.source_range_start,
        "source_range_end": harvest.source_range_end,
        "candidates": [c.model_dump() for c in candidates],
    }

    if dry_run:
        debug_candidates_path.write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"report_date": report_date, "out_dir": str(out_dir)}

    llm = LLMClient.from_settings(settings.llm)

    judgements = llm.filter_relevance(
        candidates=candidates,
        keywords=settings.search.keywords_include,
        max_selected=max_selected_eff,
        threshold=settings.filter.relevance_threshold,
        reviewer_mode=settings.filter.reviewer_mode,
    )
    debug_payload["judgements"] = [j.model_dump() for j in judgements["all_judgements"]]
    debug_payload["selected_ids"] = [c.id for c in judgements["selected"]]
    debug_candidates_path.write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    analyses: list[PaperAnalysis] = llm.analyze_papers(
        selected=judgements["selected"],
        relevance_by_id=judgements["by_id"],
    )

    global_trend = llm.summarize_daily_trend(analyses)

    weekly_trend: PeriodTrend | None = None
    monthly_trend: PeriodTrend | None = None

    run_id = arch.begin_run(
        report_date=report_date,
        generated_at=generated_at,
        source_range_start=harvest.source_range_start,
        source_range_end=harvest.source_range_end,
        categories=settings.search.categories,
        keywords=settings.search.keywords_include,
        counts={"candidates": len(candidates), "selected": len(analyses)},
    )
    arch.write_candidates(run_id, candidates)
    arch.write_judgements(run_id, judgements["by_id"])
    arch.write_analyses(run_id, analyses)

    if settings.trend.enable_weekly:
        weekly_items = arch.get_analyses_between(days=settings.trend.weekly_days, timezone=settings.search.timezone)
        weekly_kw = build_bar_keywords(weekly_items, top_k=settings.trend.top_k_keywords)
        weekly_summary = summarize_period_trend(llm, "week", weekly_items, timezone=settings.search.timezone)
        weekly_trend = PeriodTrend(
            period="week",
            start_date=weekly_summary["start_date"],
            end_date=weekly_summary["end_date"],
            summary_cn=weekly_summary["summary_cn"],
            keywords=weekly_kw,
            chart_path=None,
        )
        arch.write_trend(run_id, weekly_trend)

    if settings.trend.enable_monthly:
        monthly_items = arch.get_analyses_between(days=settings.trend.monthly_days, timezone=settings.search.timezone)
        monthly_kw = build_bar_keywords(monthly_items, top_k=settings.trend.top_k_keywords)
        monthly_summary = summarize_period_trend(llm, "month", monthly_items, timezone=settings.search.timezone)
        monthly_trend = PeriodTrend(
            period="month",
            start_date=monthly_summary["start_date"],
            end_date=monthly_summary["end_date"],
            summary_cn=monthly_summary["summary_cn"],
            keywords=monthly_kw,
            chart_path=None,
        )
        arch.write_trend(run_id, monthly_trend)

    report = DailyReport(
        date=report_date,
        generated_at=generated_at,
        source_range_start=harvest.source_range_start,
        source_range_end=harvest.source_range_end,
        domain="Computer Science",
        categories=settings.search.categories,
        keywords=settings.search.keywords_include,
        global_trend=global_trend,
        papers=analyses,
        weekly_trend=weekly_trend,
        monthly_trend=monthly_trend,
        spotlight=[],
    )

    daily_report_path = out_dir / "daily_report.json"
    daily_report_path.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    arch.write_daily_report(run_id, report)

    html_path = out_dir / "report.html"
    pdf_path = out_dir / "report.pdf"

    if not pdf_only:
        render_report_html(report.model_dump(), html_path)
    if not html_only and settings.output.write_pdf:
        render_html_to_pdf_if_available(html_path, pdf_path)

    return {
        "report_date": report_date,
        "out_dir": str(out_dir),
        "html_path": str(html_path) if html_path.exists() else None,
        "pdf_path": str(pdf_path) if pdf_path.exists() else None,
        "db_path": str(db_path),
        "run_id": run_id,
    }
