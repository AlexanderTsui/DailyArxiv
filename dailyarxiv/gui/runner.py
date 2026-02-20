from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from ..pipeline import run_pipeline


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    message: str
    done: int | None = None
    total: int | None = None


ProgressQueue = "queue.Queue[Any]"


def run_in_background(
    *,
    settings: Settings,
    out_dir: Path,
    date_arg: str,
    max_results: int | None,
    max_selected: int | None,
    dry_run: bool,
    html_only: bool,
    pdf_only: bool,
    progress_q: ProgressQueue,
    cancel: threading.Event,
) -> dict[str, Any]:
    def progress_cb(stage: str, payload: dict[str, Any]) -> None:
        progress_q.put(
            ProgressEvent(
                stage=stage,
                message=str(payload.get("message", "")),
                done=payload.get("done"),
                total=payload.get("total"),
            )
        )

    return run_pipeline(
        settings=settings,
        out_root=out_dir,
        date_arg=date_arg,
        max_results=max_results,
        max_selected=max_selected,
        dry_run=dry_run,
        html_only=html_only,
        pdf_only=pdf_only,
        progress_cb=progress_cb,
        cancel=cancel,
    )


def drain_progress(progress_q: ProgressQueue) -> list[ProgressEvent]:
    items: list[Any] = []
    while True:
        try:
            items.append(progress_q.get_nowait())
        except queue.Empty:
            return items
