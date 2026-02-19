from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Iterable

from zoneinfo import ZoneInfo

from .llm_client import LLMClient
from .models import KeywordWeight, PaperAnalysis


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-\+_/]{2,}")


def build_bar_keywords(items: Iterable[PaperAnalysis], *, top_k: int) -> list[KeywordWeight]:
    """
    Deterministic keyword aggregation suitable for bar-chart rendering.
    Uses:
    - method/paradigm_relation (English tokens)
    - matched_terms from relevance judgement
    """
    counter: Counter[str] = Counter()
    for a in items:
        text = f"{a.method}\n{a.paradigm_relation}\n" + " ".join(a.relevance.matched_terms or [])
        for w in _WORD_RE.findall(text):
            key = w.strip().lower()
            if len(key) < 3:
                continue
            counter[key] += 1

    if not counter:
        return []
    most = counter.most_common(top_k)
    max_v = float(most[0][1])
    out: list[KeywordWeight] = []
    for k, v in most:
        out.append(KeywordWeight(keyword=k, weight=float(v) / max_v))
    return out


def summarize_period_trend(llm: LLMClient, period: str, items: list[PaperAnalysis], timezone: str = "UTC") -> dict[str, Any]:
    tz = ZoneInfo(timezone)
    end = datetime.now(tz).date().isoformat()
    if period == "week":
        start = (datetime.now(tz).date() - timedelta(days=6)).isoformat()
    else:
        start = (datetime.now(tz).date() - timedelta(days=29)).isoformat()

    if not items:
        return {
            "start_date": start,
            "end_date": end,
            "summary_cn": "（该时间范围内暂无历史入选论文）",
        }

    bullets = [f"{a.title_en}: {a.method} / {a.paradigm_relation}" for a in items]
    summary_cn = llm.summarize_period_trend(period, bullets, start, end)
    return {"start_date": start, "end_date": end, "summary_cn": summary_cn}
