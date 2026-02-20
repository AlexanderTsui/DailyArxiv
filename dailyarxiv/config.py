from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseModel):
    api_key: str = ""
    base_url: str = ""
    # Default aligned with PRD/user preference.
    model_fast: str = "gemini-3-flash"
    model_smart: str = "gemini-3-flash"
    temperature: float = 0.0


class SearchSettings(BaseModel):
    categories: list[str] = Field(default_factory=list)
    mode: str = "latest_update_day"  # latest_update_day | fixed_window
    time_window_hours: int = 24
    lookback_days: int = 7
    timezone: str = "UTC"
    max_results: int = 120
    keywords_include: list[str] = Field(default_factory=list)
    keywords_exclude: list[str] = Field(default_factory=list)


class FilterSettings(BaseModel):
    relevance_threshold: int = 60
    max_selected: int = 20
    reviewer_mode: str = "fast_only"  # fast_only | fast_then_review


class TrendSettings(BaseModel):
    enable_weekly: bool = True
    enable_monthly: bool = True
    weekly_days: int = 7
    monthly_days: int = 30
    top_k_keywords: int = 20
    chart_type: str = "bar"  # bar | wordcloud


class SpotlightSettings(BaseModel):
    enable: bool = False
    recent_days: int = 7
    attention_threshold: int = 70
    max_items: int = 2
    sources: list[str] = Field(default_factory=lambda: ["semantic_scholar"])


class OutputSettings(BaseModel):
    write_pdf: bool = True
    # HTML template short-name (editorial|baseline|modern|compact) or a '*.j2' filename.
    html_template: str = "editorial"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DAILYARXIV_", extra="ignore")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    filter: FilterSettings = Field(default_factory=FilterSettings)
    trend: TrendSettings = Field(default_factory=TrendSettings)
    spotlight: SpotlightSettings = Field(default_factory=SpotlightSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)


def load_settings(config_path: Path) -> Settings:
    data: dict[str, Any] = {}
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(data)


def save_settings(config_path: Path, settings: Settings, *, include_api_key: bool = False) -> None:
    data = settings.model_dump()
    if not include_api_key:
        data.setdefault("llm", {})
        data["llm"]["api_key"] = ""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
