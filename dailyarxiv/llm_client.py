from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any, TypeVar

import time
import httpx
from pydantic import BaseModel, ValidationError

from .config import LLMSettings
from .errors import CancelledError
from .models import PaperAnalysis, PaperCandidate, RelevanceJudgement

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMUsage:
    calls: int = 0


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model_fast: str, model_smart: str, temperature: float) -> None:
        self._api_key = api_key or ""
        self._base_url = _normalize_base_url(base_url or "")
        self._provider = _detect_provider(self._base_url)

        self._openai_client = None
        if self._provider == "openai_compat":
            # Lazy import so tests can run without openai installed.
            from openai import OpenAI

            self._openai_client = OpenAI(api_key=self._api_key or None, base_url=self._base_url or None)

        self._http = httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0))
        self._model_fast = model_fast
        self._model_smart = model_smart
        self._temperature = float(temperature)

    @classmethod
    def from_settings(cls, s: LLMSettings) -> "LLMClient":
        if not s.api_key and not os.getenv("OPENAI_API_KEY") and not os.getenv("GEMINI_API_KEY"):
            raise ValueError("Missing LLM config: set llm.api_key or OPENAI_API_KEY or GEMINI_API_KEY.")
        return cls(
            api_key=s.api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("OPENAI_API_KEY", ""),
            base_url=s.base_url,
            model_fast=s.model_fast,
            model_smart=s.model_smart,
            temperature=s.temperature,
        )

    def _chat_json(self, *, model: str, system: str, user: str, schema_hint: str) -> dict[str, Any]:
        prompt = f"{user}\n\nReturn ONLY valid JSON.\nJSON schema hint:\n{schema_hint}"
        if self._provider == "gemini_v1beta":
            text = _gemini_generate_text(
                http=self._http,
                base_url=self._base_url,
                api_key=self._api_key,
                model=model,
                system=system,
                user=prompt,
                temperature=self._temperature,
            )
            return _safe_json_loads(text)

        if not self._openai_client:
            raise RuntimeError("OpenAI-compatible client not initialized.")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        resp = self._openai_client.chat.completions.create(
            model=model,
            temperature=self._temperature,
            messages=messages,
        )
        content = resp.choices[0].message.content or ""
        return _safe_json_loads(content)

    def _parse_or_repair(self, model: str, system: str, user: str, cls: type[T]) -> T:
        schema_hint = cls.model_json_schema()
        try:
            raw = self._chat_json(model=model, system=system, user=user, schema_hint=json.dumps(schema_hint))
            return cls.model_validate(raw)
        except (ValidationError, json.JSONDecodeError) as e:
            repair_user = (
                f"Your previous output was invalid.\nError: {e}\n\n"
                f"Re-output ONLY valid JSON matching the schema exactly. No markdown.\n\n"
                f"Original task:\n{user}"
            )
            raw2 = self._chat_json(model=model, system=system, user=repair_user, schema_hint=json.dumps(schema_hint))
            return cls.model_validate(raw2)

    def filter_relevance(
        self,
        *,
        candidates: list[PaperCandidate],
        keywords: list[str],
        max_selected: int,
        threshold: int,
        reviewer_mode: str,
        progress_cb: Any | None = None,
        cancel: Any | None = None,
    ) -> dict[str, Any]:
        total = len(candidates)

        if not [k for k in keywords if str(k).strip()]:
            by_id: dict[str, RelevanceJudgement] = {}
            all_judgements: list[RelevanceJudgement] = []
            for i, c in enumerate(candidates, start=1):
                if cancel is not None and hasattr(cancel, "is_set") and bool(cancel.is_set()):
                    raise CancelledError("Cancelled")
                j = RelevanceJudgement(
                    is_relevant=True,
                    relevance_score=50,
                    matched_terms=[],
                    reason_cn="未设置关键词，默认按分区与时间纳入候选。",
                )
                by_id[c.id] = j
                all_judgements.append(j)
                if progress_cb:
                    progress_cb("filter", f"Judged {c.id}", i, total)
            selected = sorted(candidates, key=lambda x: x.publish_date, reverse=True)[:max_selected]
            _ = reviewer_mode
            _ = threshold
            return {"by_id": by_id, "all_judgements": all_judgements, "selected": selected}

        system = (
            "You are a senior AI researcher. "
            "Judge whether a paper is relevant to user's interests based ONLY on the abstract and title. "
            "Be strict and concise."
        )
        by_id: dict[str, RelevanceJudgement] = {}
        all_judgements: list[RelevanceJudgement] = []
        for i, c in enumerate(candidates, start=1):
            if cancel is not None and hasattr(cancel, "is_set") and bool(cancel.is_set()):
                raise CancelledError("Cancelled")
            if progress_cb:
                progress_cb("filter", f"Judging {c.id}", i, total)
            user = (
                f"User keywords: {keywords}\n\n"
                f"Paper title: {c.title_en}\n"
                f"Paper abstract: {c.abstract}\n\n"
                "Decide relevance to the user keywords. "
                "Return is_relevant, relevance_score (0-100), matched_terms, and a short Chinese reason (<=80 chars)."
            )
            j = self._parse_or_repair(self._model_fast, system, user, RelevanceJudgement)
            by_id[c.id] = j
            all_judgements.append(j)

        selected = [c for c in candidates if by_id[c.id].is_relevant and by_id[c.id].relevance_score >= threshold]
        selected.sort(key=lambda x: (by_id[x.id].relevance_score, x.publish_date), reverse=True)
        selected = selected[:max_selected]

        # reviewer_mode reserved (future): fast_then_review
        _ = reviewer_mode

        return {"by_id": by_id, "all_judgements": all_judgements, "selected": selected}

    def analyze_papers(
        self,
        *,
        selected: list[PaperCandidate],
        relevance_by_id: dict[str, RelevanceJudgement],
        progress_cb: Any | None = None,
        cancel: Any | None = None,
    ) -> list[PaperAnalysis]:
        system = (
            "You are a senior AI researcher and editor. "
            "Read the abstract and produce a structured Chinese analysis. "
            "Be specific, avoid fluff, and keep each field short as requested."
        )
        out: list[PaperAnalysis] = []
        total = len(selected)
        for i, c in enumerate(selected, start=1):
            if cancel is not None and hasattr(cancel, "is_set") and bool(cancel.is_set()):
                raise CancelledError("Cancelled")
            if progress_cb:
                progress_cb("analyze", f"Analyzing {c.id}", i, total)
            j = relevance_by_id[c.id]
            user = (
                "Fill the fields for PaperAnalysis. Constraints:\n"
                "- title_cn: Chinese translation of title\n"
                "- motivation/method: <50 Chinese chars each\n"
                "- paradigm_relation: describe relation to SOTA (Chinese)\n"
                "- score: 1-5 based on novelty AND relevance\n\n"
                f"Paper metadata:\n"
                f"id={c.id}\n"
                f"title_en={c.title_en}\n"
                f"authors={c.authors}\n"
                f"url={c.url}\n"
                f"publish_date={c.publish_date}\n"
                f"primary_category={c.primary_category}\n\n"
                f"Abstract:\n{c.abstract}\n\n"
                f"Relevance prior:\n{j.model_dump()}\n"
            )
            analysis = self._parse_or_repair(self._model_smart, system, user, PaperAnalysis)
            # Ensure relevance matches our judgement (LLM may override)
            analysis.relevance = j
            out.append(analysis)
        return out

    def summarize_daily_trend(self, analyses: list[PaperAnalysis]) -> str:
        if not analyses:
            return "今日无入选论文。"
        system = "You are an editor-in-chief. Summarize today's selected papers into one concise Chinese paragraph (~200 chars)."
        user = "Papers:\n" + "\n".join(f"- {a.title_en}: {a.method} / {a.paradigm_relation}" for a in analyses)
        payload = self._chat_json(model=self._model_smart, system=system, user=user, schema_hint='{"global_trend":"string"}')
        trend = str(payload.get("global_trend", "")).strip()
        return trend or "（趋势总结生成失败）"

    def summarize_period_trend(self, period: str, bullets: list[str], start_date: str, end_date: str) -> str:
        system = "You are an editor-in-chief. Summarize the macro trend for the given period in one Chinese paragraph (150-250 chars)."
        user = (
            f"Period: {period}\nRange: {start_date} to {end_date}\n\n"
            "Bullets (methods/paradigm notes):\n" + "\n".join(f"- {b}" for b in bullets[:120])
        )
        payload = self._chat_json(model=self._model_smart, system=system, user=user, schema_hint='{"summary_cn":"string"}')
        summary = str(payload.get("summary_cn", "")).strip()
        return summary or "（趋势总结生成失败）"


def _safe_json_loads(text: str) -> dict[str, Any]:
    s = text.strip()
    # Handle cases where the model wraps JSON in code fences.
    if s.startswith("```"):
        s = s.strip("`")
        # remove optional leading 'json'
        s = s.replace("json\n", "", 1)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Attempt to extract first {...} block.
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start : end + 1])
        raise


def _normalize_base_url(base_url: str) -> str:
    s = (base_url or "").strip()
    if not s:
        return ""
    return s.rstrip("/")


def _detect_provider(base_url: str) -> str:
    if "/gemini" in (base_url or ""):
        return "gemini_v1beta"
    return "openai_compat"


_GEMINI_MODEL_ALIASES: dict[str, str] = {
    # Some gateways expose preview names; map the stable name to a known model id.
    "gemini-3-flash": "gemini-3-flash-preview",
}


def _gemini_generate_text(
    *,
    http: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float,
) -> str:
    """
    Google Gemini (Generative Language API v1beta) compatible call:
      POST {base_url}/v1beta/models/{model}:generateContent
      Header: x-api-key: <key>
    """
    if not base_url:
        raise ValueError("Gemini provider requires llm.base_url.")
    if not api_key:
        raise ValueError("Gemini provider requires llm.api_key (or GEMINI_API_KEY/OPENAI_API_KEY env var).")

    m = _GEMINI_MODEL_ALIASES.get(model, model)
    url = f"{base_url}/v1beta/models/{m}:generateContent"
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": f"{system}\n\n{user}"}]},
        ],
        "generationConfig": {"temperature": float(temperature)},
    }
    r = _post_with_retry(http, url, api_key=api_key, payload=payload)
    r.raise_for_status()
    data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return text.strip()
    except Exception:
        raise RuntimeError(f"Unexpected Gemini response shape: {data!r}")


def _post_with_retry(http: httpx.Client, url: str, *, api_key: str, payload: dict[str, Any]) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return http.post(url, headers={"x-api-key": api_key}, json=payload)
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
            last_exc = e
            time.sleep(1.5 * (2**attempt))
    assert last_exc is not None
    raise last_exc
