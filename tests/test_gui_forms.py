from __future__ import annotations

import threading

from dailyarxiv.config import Settings
from dailyarxiv.gui.forms import settings_to_ui_dict, ui_dict_to_settings
from dailyarxiv.llm_client import LLMClient
from dailyarxiv.models import PaperCandidate
from dailyarxiv.errors import CancelledError


def test_settings_ui_roundtrip() -> None:
    s = Settings()
    ui = settings_to_ui_dict(s)
    s2 = ui_dict_to_settings(ui)
    assert s2.search.mode == s.search.mode


def test_cancel_in_keywordless_filter_branch() -> None:
    # This branch must not call network; it should honor cancel immediately.
    client = object.__new__(LLMClient)  # bypass __init__
    # monkeypatch required fields used in branch
    client._model_fast = "x"
    client._model_smart = "x"
    client._temperature = 0.0
    client._provider = "gemini_v1beta"

    candidates = [
        PaperCandidate(
            id="1",
            title_en="t",
            authors=["a"],
            url="u",
            publish_date="2026-02-18T00:00:00+00:00",
            categories=["cs.CL"],
            primary_category="cs.CL",
            abstract="abs",
        )
    ]
    cancel = threading.Event()
    cancel.set()
    try:
        client.filter_relevance(
            candidates=candidates,
            keywords=[],
            max_selected=1,
            threshold=0,
            reviewer_mode="fast_only",
            cancel=cancel,
        )
        assert False, "Expected CancelledError"
    except CancelledError:
        assert True


def test_progress_mapping_monotonic() -> None:
    from dailyarxiv.gui.app import _compute_overall_progress

    p1 = _compute_overall_progress(stage="filter", done=1, total=10)
    p2 = _compute_overall_progress(stage="filter", done=5, total=10)
    p3 = _compute_overall_progress(stage="filter", done=10, total=10)
    assert 0.0 <= p1 < p2 < p3 <= 1.0
