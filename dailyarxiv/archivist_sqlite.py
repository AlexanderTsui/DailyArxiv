from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

from zoneinfo import ZoneInfo

from .models import DailyReport, PaperAnalysis, PaperCandidate, PeriodTrend, RelevanceJudgement


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    report_date: str


class ArchivistSQLite:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
        except Exception:
            try:
                con.rollback()
            finally:
                con.close()
            raise
        else:
            try:
                con.commit()
            finally:
                con.close()

    def _init_db(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS runs (
                  run_id TEXT PRIMARY KEY,
                  report_date TEXT NOT NULL,
                  generated_at TEXT NOT NULL,
                  source_range_start TEXT NOT NULL,
                  source_range_end TEXT NOT NULL,
                  categories_json TEXT NOT NULL,
                  keywords_json TEXT NOT NULL,
                  counts_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS candidates (
                  run_id TEXT NOT NULL,
                  paper_id TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  PRIMARY KEY (run_id, paper_id)
                );

                CREATE TABLE IF NOT EXISTS judgements (
                  run_id TEXT NOT NULL,
                  paper_id TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  PRIMARY KEY (run_id, paper_id)
                );

                CREATE TABLE IF NOT EXISTS analyses (
                  run_id TEXT NOT NULL,
                  paper_id TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  publish_date TEXT NOT NULL,
                  PRIMARY KEY (run_id, paper_id)
                );

                CREATE TABLE IF NOT EXISTS trends (
                  run_id TEXT NOT NULL,
                  period TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  PRIMARY KEY (run_id, period)
                );

                CREATE TABLE IF NOT EXISTS reports (
                  run_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                );
                """
            )

    def begin_run(
        self,
        *,
        report_date: str,
        generated_at: str,
        source_range_start: str,
        source_range_end: str,
        categories: list[str],
        keywords: list[str],
        counts: dict[str, Any],
    ) -> str:
        run_id = f"{report_date}-{generated_at}"
        with self._connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO runs
                (run_id, report_date, generated_at, source_range_start, source_range_end, categories_json, keywords_json, counts_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    report_date,
                    generated_at,
                    source_range_start,
                    source_range_end,
                    json.dumps(categories, ensure_ascii=False),
                    json.dumps(keywords, ensure_ascii=False),
                    json.dumps(counts, ensure_ascii=False),
                ),
            )
        return run_id

    def write_candidates(self, run_id: str, candidates: Iterable[PaperCandidate]) -> None:
        rows = [(run_id, c.id, json.dumps(c.model_dump(), ensure_ascii=False)) for c in candidates]
        with self._connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO candidates (run_id, paper_id, payload_json) VALUES (?, ?, ?)",
                rows,
            )

    def write_judgements(self, run_id: str, judgements_by_id: dict[str, RelevanceJudgement]) -> None:
        rows: list[tuple[str, str, str]] = []
        for pid, j in judgements_by_id.items():
            rows.append((run_id, str(pid), json.dumps(j.model_dump(), ensure_ascii=False)))
        with self._connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO judgements (run_id, paper_id, payload_json) VALUES (?, ?, ?)",
                rows,
            )

    def write_analyses(self, run_id: str, analyses: Iterable[PaperAnalysis]) -> None:
        rows = [
            (run_id, a.id, json.dumps(a.model_dump(), ensure_ascii=False), a.publish_date)
            for a in analyses
        ]
        with self._connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO analyses (run_id, paper_id, payload_json, publish_date) VALUES (?, ?, ?, ?)",
                rows,
            )

    def write_trend(self, run_id: str, trend: PeriodTrend) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO trends (run_id, period, payload_json) VALUES (?, ?, ?)",
                (run_id, trend.period, json.dumps(trend.model_dump(), ensure_ascii=False)),
            )

    def write_daily_report(self, run_id: str, report: DailyReport) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO reports (run_id, payload_json) VALUES (?, ?)",
                (run_id, json.dumps(report.model_dump(), ensure_ascii=False)),
            )

    def get_analyses_between(self, *, days: int, timezone: str = "UTC") -> list[PaperAnalysis]:
        """
        Returns analyses from the most recent run per day in the last N days (inclusive).
        This is a simple heuristic to build weekly/monthly trends without overcounting multiple runs per day.
        """
        tz = ZoneInfo(timezone)
        end = datetime.now(tz).date()
        start = end - timedelta(days=max(0, days - 1))
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        with self._connect() as con:
            run_rows = con.execute(
                """
                SELECT report_date, MAX(generated_at) AS gen
                FROM runs
                WHERE report_date BETWEEN ? AND ?
                GROUP BY report_date
                """,
                (start_iso, end_iso),
            ).fetchall()

            run_ids: list[str] = []
            for rr in run_rows:
                rd = rr["report_date"]
                gen = rr["gen"]
                run_ids.append(f"{rd}-{gen}")

            if not run_ids:
                return []

            qmarks = ",".join("?" for _ in run_ids)
            arows = con.execute(
                f"SELECT payload_json FROM analyses WHERE run_id IN ({qmarks})",
                run_ids,
            ).fetchall()

        out: list[PaperAnalysis] = []
        for r in arows:
            out.append(PaperAnalysis.model_validate(json.loads(r["payload_json"])))
        return out

    def stats(self, *, days: int = 30) -> dict[str, Any]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT report_date, counts_json
                FROM runs
                ORDER BY report_date DESC
                LIMIT ?
                """,
                (days,),
            ).fetchall()
        out = []
        for r in rows:
            out.append({"report_date": r["report_date"], "counts": json.loads(r["counts_json"])})
        return {"recent_runs": out}

    def export_report(self, *, date: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT r.payload_json
                FROM reports r
                JOIN runs u ON u.run_id = r.run_id
                WHERE u.report_date = ?
                ORDER BY u.generated_at DESC
                LIMIT 1
                """,
                (date,),
            ).fetchone()
        if not row:
            raise FileNotFoundError(f"No report for date={date}")
        return json.loads(row["payload_json"])
