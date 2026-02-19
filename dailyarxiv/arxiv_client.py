from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from zoneinfo import ZoneInfo

from .models import PaperCandidate


@dataclass(frozen=True)
class HarvestResult:
    report_date: str  # YYYY-MM-DD
    source_range_start: str  # ISO
    source_range_end: str  # ISO
    candidates: list[PaperCandidate]


def _to_date_str(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).date().isoformat()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("UTC")).isoformat()
    return dt.isoformat()


def harvest_candidates(
    categories: list[str],
    timezone: str,
    mode: str,
    time_window_hours: int,
    lookback_days: int,
    max_results: int,
    date_override: str | None = None,
) -> HarvestResult:
    """
    Deterministic strategy:
    - Fetch latest max_results by UpdatedDate (arxiv wrapper sort).
    - Group by local date (timezone).
    - Pick report_date:
      - latest_update_day: latest date with at least one result within lookback_days (from newest)
      - fixed_window: keep items updated within now - time_window_hours
    """
    # Lazy import so tests can run without arxiv installed.
    import arxiv

    tz = ZoneInfo(timezone)
    query = " OR ".join(f"cat:{c}" for c in categories) if categories else "all"
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.LastUpdatedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    client = arxiv.Client()
    results = list(client.results(search))
    if not results:
        now = datetime.now(tz)
        return HarvestResult(
            report_date=now.date().isoformat(),
            source_range_start=now.isoformat(),
            source_range_end=now.isoformat(),
            candidates=[],
        )

    now = datetime.now(tz)
    if mode == "fixed_window":
        start = now - timedelta(hours=time_window_hours)
        kept: list[PaperCandidate] = []
        for r in results:
            updated = getattr(r, "updated", None) or getattr(r, "published", None)
            if updated is None:
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=ZoneInfo("UTC"))
            if updated >= start.astimezone(updated.tzinfo):
                kept.append(_to_candidate(r))
        return HarvestResult(
            report_date=now.date().isoformat(),
            source_range_start=start.isoformat(),
            source_range_end=now.isoformat(),
            candidates=kept,
        )

    # latest_update_day (or explicit date_override)
    buckets: dict[str, list[PaperCandidate]] = defaultdict(list)
    newest_dt: datetime | None = None
    oldest_dt: datetime | None = None
    for r in results:
        updated = getattr(r, "updated", None) or getattr(r, "published", None)
        if updated is None:
            continue
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=ZoneInfo("UTC"))
        newest_dt = updated if newest_dt is None else max(newest_dt, updated)
        oldest_dt = updated if oldest_dt is None else min(oldest_dt, updated)
        buckets[_to_date_str(updated, tz)].append(_to_candidate(r))

    if not buckets:
        return HarvestResult(
            report_date=now.date().isoformat(),
            source_range_start=now.isoformat(),
            source_range_end=now.isoformat(),
            candidates=[],
        )

    available_dates = sorted(buckets.keys(), reverse=True)
    if date_override:
        if date_override not in buckets:
            start = datetime.fromisoformat(date_override).replace(tzinfo=tz)
            end = start + timedelta(days=1) - timedelta(seconds=1)
            return HarvestResult(
                report_date=date_override,
                source_range_start=start.isoformat(),
                source_range_end=end.isoformat(),
                candidates=[],
            )
        start = datetime.fromisoformat(date_override).replace(tzinfo=tz)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        return HarvestResult(
            report_date=date_override,
            source_range_start=start.isoformat(),
            source_range_end=end.isoformat(),
            candidates=buckets[date_override],
        )
    newest_date = datetime.fromisoformat(available_dates[0]).date()
    chosen: str | None = None
    for d in available_dates:
        dt = datetime.fromisoformat(d).date()
        if (newest_date - dt).days <= lookback_days:
            chosen = d
            break
    if chosen is None:
        chosen = available_dates[0]

    start = datetime.fromisoformat(chosen).replace(tzinfo=tz)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return HarvestResult(
        report_date=chosen,
        source_range_start=start.isoformat(),
        source_range_end=end.isoformat(),
        candidates=buckets[chosen],
    )


def _to_candidate(r: object) -> PaperCandidate:
    # arxiv.Result has: entry_id, title, authors, summary, updated, published, categories, primary_category
    entry_id = getattr(r, "entry_id", "")
    arxiv_id = getattr(r, "get_short_id", None)
    if callable(arxiv_id):
        pid = arxiv_id()
    else:
        pid = entry_id.rsplit("/", 1)[-1] if entry_id else ""
    title = getattr(r, "title", "").strip().replace("\n", " ")
    summary = getattr(r, "summary", "").strip().replace("\n", " ")
    authors = [getattr(a, "name", str(a)) for a in getattr(r, "authors", [])][:3]
    updated = getattr(r, "updated", None) or getattr(r, "published", None)
    publish_date = _iso(updated) if isinstance(updated, datetime) else ""
    categories = list(getattr(r, "categories", []) or [])
    primary_category = getattr(r, "primary_category", "") or (categories[0] if categories else "")
    return PaperCandidate(
        id=str(pid),
        title_en=title,
        authors=authors,
        url=str(entry_id),
        publish_date=publish_date,
        categories=[str(c) for c in categories],
        primary_category=str(primary_category),
        abstract=summary,
    )


def apply_keyword_heuristics(
    candidates: Iterable[PaperCandidate],
    include: list[str],
    exclude: list[str],
) -> list[PaperCandidate]:
    inc = [s.lower() for s in include if s.strip()]
    exc = [s.lower() for s in exclude if s.strip()]

    out: list[PaperCandidate] = []
    for c in candidates:
        text = f"{c.title_en}\n{c.abstract}".lower()
        if exc and any(x in text for x in exc):
            continue
        if inc and not any(x in text for x in inc):
            continue
        out.append(c)
    return out
