from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class KeywordWeight(BaseModel):
    keyword: str
    weight: float


class PaperCandidate(BaseModel):
    id: str
    title_en: str
    authors: list[str]
    url: str
    publish_date: str
    categories: list[str]
    primary_category: str
    abstract: str


class RelevanceJudgement(BaseModel):
    is_relevant: bool
    relevance_score: int = Field(ge=0, le=100)
    matched_terms: list[str] = Field(default_factory=list)
    reason_cn: str


class PaperAnalysis(BaseModel):
    id: str
    title_en: str
    title_cn: str
    authors: list[str]
    url: str
    publish_date: str
    primary_category: str

    motivation: str
    method: str
    paradigm_relation: str
    score: int = Field(ge=1, le=5)

    relevance: RelevanceJudgement


class PeriodTrend(BaseModel):
    period: Literal["week", "month"]
    start_date: str
    end_date: str
    summary_cn: str
    keywords: list[KeywordWeight] = Field(default_factory=list)
    chart_path: str | None = None


class AttentionSignal(BaseModel):
    source: str  # e.g. semantic_scholar
    metric: str
    value: float
    fetched_at: str


class SpotlightItem(BaseModel):
    paper_id: str
    attention_score: int = Field(ge=0, le=100)
    signals: list[AttentionSignal] = Field(default_factory=list)
    intro_cn: str


class DailyReport(BaseModel):
    date: str
    generated_at: str
    source_range_start: str
    source_range_end: str

    domain: str
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    global_trend: str
    papers: list[PaperAnalysis] = Field(default_factory=list)

    weekly_trend: PeriodTrend | None = None
    monthly_trend: PeriodTrend | None = None
    spotlight: list[SpotlightItem] = Field(default_factory=list)

