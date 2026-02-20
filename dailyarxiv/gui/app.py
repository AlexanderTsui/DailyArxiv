from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

import streamlit as st

from dailyarxiv.archivist_sqlite import ArchivistSQLite
from dailyarxiv.config import save_settings
from dailyarxiv.gui.forms import load_settings_or_default, settings_to_ui_dict, ui_dict_to_settings
from dailyarxiv.gui.i18n import tr
from dailyarxiv.gui.runner import drain_progress, run_in_background


APP_TITLE = "DailyArxiv GUI"


def main() -> int:
    if "lang" not in st.session_state:
        st.session_state.lang = "zh"

    # Streamlit requires set_page_config() to be the first Streamlit call.
    st.set_page_config(page_title=tr(st.session_state.lang, "app_title"), layout="wide")

    lang_label = st.sidebar.selectbox(
        label=tr(st.session_state.lang, "language"),
        options=["中文", "English"],
        index=0 if st.session_state.lang == "zh" else 1,
        key="__lang_label",
    )
    new_lang = "zh" if lang_label == "中文" else "en"
    if new_lang != st.session_state.lang:
        st.session_state.lang = new_lang
        st.rerun()

    st.title(tr(st.session_state.lang, "app_title"))

    page = st.sidebar.radio(
        tr(st.session_state.lang, "page"),
        [
            tr(st.session_state.lang, "run"),
            tr(st.session_state.lang, "history"),
            tr(st.session_state.lang, "settings"),
            tr(st.session_state.lang, "about"),
        ],
    )

    if page == tr(st.session_state.lang, "run"):
        _page_run()
    elif page == tr(st.session_state.lang, "history"):
        _page_history()
    elif page == tr(st.session_state.lang, "settings"):
        _page_settings()
    else:
        _page_about()
    return 0


def _page_run() -> None:
    lang = st.session_state.lang
    st.sidebar.subheader(tr(lang, "config"))
    default_cfg = "config.local.yaml" if Path("config.local.yaml").exists() else "config.yaml"
    config_path = st.sidebar.text_input(tr(lang, "config_path"), value=default_cfg)
    settings = load_settings_or_default(config_path)
    ui = settings_to_ui_dict(settings)

    st.sidebar.subheader(tr(lang, "save_config"))
    save_path = st.sidebar.text_input(tr(lang, "save_path"), value="config.local.yaml")
    autosave_on_run = st.sidebar.checkbox(tr(lang, "autosave_on_run"), value=True)
    save_api_key = st.sidebar.checkbox(tr(lang, "save_api_key"), value=False)

    st.sidebar.subheader(tr(lang, "llm"))
    st.sidebar.caption(tr(lang, "llm_caption"))
    llm_api_key = st.sidebar.text_input(tr(lang, "api_key_session"), value="", type="password")
    ui["llm"]["base_url"] = st.sidebar.text_input(tr(lang, "base_url"), value=ui["llm"].get("base_url", ""))
    ui["llm"]["model_fast"] = st.sidebar.text_input(tr(lang, "model_fast"), value=ui["llm"].get("model_fast", "gemini-3-flash"))
    ui["llm"]["model_smart"] = st.sidebar.text_input(tr(lang, "model_smart"), value=ui["llm"].get("model_smart", "gemini-3-flash"))
    ui["llm"]["temperature"] = st.sidebar.slider(tr(lang, "temperature"), min_value=0.0, max_value=1.0, value=float(ui["llm"].get("temperature", 0.0)), step=0.1)

    st.sidebar.subheader(tr(lang, "search"))
    ui["search"]["categories"] = st.sidebar.multiselect(
        tr(lang, "categories"),
        options=_default_categories(),
        default=ui.get("search", {}).get("categories", []),
    )
    ui["search"]["mode"] = st.sidebar.selectbox(
        tr(lang, "mode"),
        options=["latest_update_day", "fixed_window"],
        index=0 if ui["search"].get("mode") == "latest_update_day" else 1,
    )
    ui["search"]["timezone"] = st.sidebar.text_input(tr(lang, "timezone"), value=ui["search"].get("timezone", "UTC"))
    ui["search"]["lookback_days"] = st.sidebar.number_input(tr(lang, "lookback_days"), min_value=1, max_value=30, value=int(ui["search"].get("lookback_days", 7)))
    ui["search"]["time_window_hours"] = st.sidebar.number_input(tr(lang, "time_window_hours"), min_value=1, max_value=168, value=int(ui["search"].get("time_window_hours", 24)))
    ui["search"]["max_results"] = st.sidebar.number_input(tr(lang, "max_results"), min_value=1, max_value=500, value=int(ui["search"].get("max_results", 120)))

    st.sidebar.subheader(tr(lang, "filter"))
    ui["search"]["keywords_include"] = st.sidebar.text_area(tr(lang, "kw_include"), value="\n".join(ui["search"].get("keywords_include", []))).splitlines()
    ui["search"]["keywords_exclude"] = st.sidebar.text_area(tr(lang, "kw_exclude"), value="\n".join(ui["search"].get("keywords_exclude", []))).splitlines()
    ui["filter"]["relevance_threshold"] = st.sidebar.slider(tr(lang, "relevance_threshold"), min_value=0, max_value=100, value=int(ui["filter"].get("relevance_threshold", 60)))
    ui["filter"]["max_selected"] = st.sidebar.number_input(tr(lang, "max_selected"), min_value=1, max_value=100, value=int(ui["filter"].get("max_selected", 20)))

    st.sidebar.subheader(tr(lang, "trend"))
    ui["trend"]["enable_weekly"] = st.sidebar.checkbox(tr(lang, "enable_weekly"), value=bool(ui["trend"].get("enable_weekly", True)))
    ui["trend"]["enable_monthly"] = st.sidebar.checkbox(tr(lang, "enable_monthly"), value=bool(ui["trend"].get("enable_monthly", True)))
    ui["trend"]["weekly_days"] = st.sidebar.number_input(tr(lang, "weekly_days"), min_value=1, max_value=60, value=int(ui["trend"].get("weekly_days", 7)))
    ui["trend"]["monthly_days"] = st.sidebar.number_input(tr(lang, "monthly_days"), min_value=1, max_value=180, value=int(ui["trend"].get("monthly_days", 30)))
    ui["trend"]["top_k_keywords"] = st.sidebar.number_input(tr(lang, "top_k_keywords"), min_value=5, max_value=100, value=int(ui["trend"].get("top_k_keywords", 20)))
    ui["trend"]["chart_type"] = st.sidebar.selectbox(tr(lang, "chart_type"), options=["bar", "wordcloud"], index=0 if ui["trend"].get("chart_type") == "bar" else 1)

    st.sidebar.subheader(tr(lang, "output"))
    out_dir = st.sidebar.text_input(tr(lang, "out_dir"), value="reports")
    template_options = ["editorial", "baseline", "modern", "compact"]
    current_template = str(ui["output"].get("html_template", "editorial") or "editorial")
    template_index = template_options.index(current_template) if current_template in template_options else 0
    ui["output"]["html_template"] = st.sidebar.selectbox(
        tr(lang, "html_template"),
        options=template_options,
        index=template_index,
    )
    ui["output"]["write_pdf"] = st.sidebar.checkbox(tr(lang, "write_pdf"), value=bool(ui["output"].get("write_pdf", True)))

    st.sidebar.subheader(tr(lang, "live"))
    refresh_ms = st.sidebar.slider(tr(lang, "auto_refresh_ms"), min_value=300, max_value=3000, value=800, step=100)

    st.subheader(tr(lang, "run_header"))
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
    date_arg = col1.text_input(tr(lang, "date"), value="auto", help=tr(lang, "auto_or_date_help"))
    dry_run = col2.checkbox(tr(lang, "dry_run"), value=False)
    html_only = col3.checkbox(tr(lang, "html_only"), value=False)
    pdf_only = col3.checkbox(tr(lang, "pdf_only"), value=False)

    max_results = col4.number_input(tr(lang, "override_max_results"), min_value=0, max_value=1000, value=0)
    max_selected = col4.number_input(tr(lang, "override_max_selected"), min_value=0, max_value=200, value=0)

    settings_obj = ui_dict_to_settings(ui)
    if llm_api_key.strip():
        settings_obj.llm.api_key = llm_api_key.strip()
        ui.setdefault("llm", {})
        ui["llm"]["api_key"] = llm_api_key.strip()

    if st.sidebar.button(tr(lang, "btn_save")):
        try:
            save_settings(Path(save_path), settings_obj, include_api_key=save_api_key)
            st.sidebar.success(tr(lang, "saved_ok", path=str(save_path)))
        except Exception as e:
            st.sidebar.error(tr(lang, "saved_fail", error=str(e)))

    if "job" not in st.session_state:
        st.session_state.job = None
    if "progress_q" not in st.session_state:
        st.session_state.progress_q = queue.Queue()
    if "cancel" not in st.session_state:
        st.session_state.cancel = threading.Event()
    if "last_result" not in st.session_state:
        st.session_state.last_result = None
    if "progress_log" not in st.session_state:
        st.session_state.progress_log = []
    if "progress_state" not in st.session_state:
        st.session_state.progress_state = {"stage": "", "message": "", "done": None, "total": None}

    run_btn = st.button(tr(lang, "btn_run"), type="primary", disabled=st.session_state.job is not None)
    cancel_btn = st.button(tr(lang, "btn_cancel"), disabled=st.session_state.job is None)

    if run_btn:
        if autosave_on_run:
            try:
                save_settings(Path(save_path), settings_obj, include_api_key=save_api_key)
            except Exception as e:
                st.sidebar.error(tr(lang, "saved_fail", error=str(e)))
                st.stop()
        st.session_state.cancel = threading.Event()
        st.session_state.progress_q = queue.Queue()
        st.session_state.progress_log = []
        thread = threading.Thread(
            target=_thread_entry,
            kwargs=dict(
                settings=settings_obj,
                out_dir=Path(out_dir),
                date_arg=date_arg,
                max_results=int(max_results) if int(max_results) > 0 else None,
                max_selected=int(max_selected) if int(max_selected) > 0 else None,
                dry_run=dry_run,
                html_only=html_only,
                pdf_only=pdf_only,
                progress_q=st.session_state.progress_q,
                cancel=st.session_state.cancel,
            ),
            daemon=True,
        )
        st.session_state.job = thread
        thread.start()
        st.rerun()

    if cancel_btn:
        st.session_state.cancel.set()
        st.warning(tr(lang, "cancel_requested"))
        st.rerun()

    _render_progress(out_root=Path(out_dir), refresh_ms=refresh_ms)
    _render_last_result()


def _thread_entry(**kwargs: Any) -> None:
    try:
        result = run_in_background(**kwargs)
        kwargs["progress_q"].put(("__RESULT__", result))
    except Exception as e:
        kwargs["progress_q"].put(("__ERROR__", str(e)))


def _render_progress(*, out_root: Path, refresh_ms: int) -> None:
    lang = st.session_state.lang
    status_box = st.empty()
    progress_bar = st.progress(0.0)
    files_box = st.empty()

    prog = drain_progress(st.session_state.progress_q)
    for ev in prog:
        if isinstance(ev, tuple) and ev and ev[0] in ("__RESULT__", "__ERROR__"):
            if ev[0] == "__RESULT__":
                st.session_state.last_result = ev[1]
            else:
                st.session_state.last_result = {"error": ev[1]}
            st.session_state.job = None
            continue
        st.session_state.progress_log.append(ev)
        st.session_state.progress_state = {
            "stage": getattr(ev, "stage", ""),
            "message": getattr(ev, "message", ""),
            "done": getattr(ev, "done", None),
            "total": getattr(ev, "total", None),
        }

    ps = st.session_state.progress_state
    stage = ps.get("stage") or "idle"
    msg = ps.get("message") or ""
    done = ps.get("done")
    total = ps.get("total")
    pct = _compute_overall_progress(stage=stage, done=done, total=total)
    progress_bar.progress(min(max(pct, 0.0), 1.0))
    sep = " | "
    stage_label = tr(lang, "stage")
    if done is not None and total is not None and total:
        status_box.info(f"{stage_label}: {stage}{sep}{msg} ({done}/{total})".strip())
    else:
        status_box.info(f"{stage_label}: {stage}{sep}{msg}".strip())

    # Show any produced artifacts as they appear.
    # We can't guarantee HTML exists until render stage, but debug JSON will appear earlier.
    latest_dir = _guess_latest_out_dir(out_root)
    if latest_dir:
        html_path = latest_dir / "report.html"
        pdf_path = latest_dir / "report.pdf"
        json_path = latest_dir / "daily_report.json"
        debug_path = latest_dir / "debug_candidates.json"
        lines = [f"{tr(lang, 'output_dir')}: {latest_dir}"]
        for p in [debug_path, json_path, html_path, pdf_path]:
            if p.exists():
                lines.append(f"- {p.name}: {p.stat().st_size} bytes")
        files_box.code("\n".join(lines), language="text")
        if html_path.exists():
            with st.expander(tr(lang, "live_html_preview"), expanded=False):
                st.components.v1.html(html_path.read_text(encoding="utf-8"), height=600, scrolling=True)
    else:
        files_box.caption(tr(lang, "no_progress"))

    # Show tail log
    if st.session_state.progress_log:
        lines = []
        for ev in st.session_state.progress_log[-80:]:
            if getattr(ev, "done", None) is not None and getattr(ev, "total", None) is not None:
                lines.append(f"[{ev.stage}] {ev.message} ({ev.done}/{ev.total})")
            else:
                lines.append(f"[{ev.stage}] {ev.message}")
        st.code("\n".join(lines), language="text")

    if st.session_state.job is not None:
        time.sleep(max(0.2, refresh_ms / 1000.0))
        st.rerun()


def _guess_latest_out_dir(out_root: Path) -> Path | None:
    try:
        if not out_root.exists():
            return None
        dirs = [p for p in out_root.iterdir() if p.is_dir()]
        if not dirs:
            return None
        dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return dirs[0]
    except Exception:
        return None


def _compute_overall_progress(*, stage: str, done: int | None, total: int | None) -> float:
    weights: dict[str, tuple[float, float]] = {
        "harvest": (0.00, 0.10),
        "filter": (0.10, 0.25),
        "analyze": (0.35, 0.45),
        "trend": (0.80, 0.10),
        "archive": (0.90, 0.05),
        "render": (0.95, 0.05),
        "idle": (0.00, 0.00),
    }
    base, span = weights.get(stage, (0.00, 0.05))
    frac = 0.0
    if done is not None and total is not None and total > 0:
        frac = min(max(done / total, 0.0), 1.0)
    elif stage in ("render", "archive"):
        frac = 0.5
    return base + span * frac


def _render_last_result() -> None:
    lang = st.session_state.lang
    res = st.session_state.last_result
    if not res:
        return
    if "error" in res:
        st.error(res["error"])
        return

    st.subheader(tr(lang, "result"))
    st.json(res)
    out_dir = Path(res["out_dir"])
    html_path = out_dir / "report.html"
    pdf_path = out_dir / "report.pdf"
    json_path = out_dir / "daily_report.json"
    debug_path = out_dir / "debug_candidates.json"

    cols = st.columns(4)
    if html_path.exists():
        cols[0].download_button(tr(lang, "download_html"), data=html_path.read_bytes(), file_name="report.html")
    if pdf_path.exists():
        cols[1].download_button(tr(lang, "download_pdf"), data=pdf_path.read_bytes(), file_name="report.pdf")
    if json_path.exists():
        cols[2].download_button(tr(lang, "download_json"), data=json_path.read_bytes(), file_name="daily_report.json")
    if debug_path.exists():
        cols[3].download_button(tr(lang, "download_debug"), data=debug_path.read_bytes(), file_name="debug_candidates.json")

    if html_path.exists():
        st.subheader(tr(lang, "html_preview"))
        st.components.v1.html(html_path.read_text(encoding="utf-8"), height=900, scrolling=True)


def _page_history() -> None:
    lang = st.session_state.lang
    st.subheader(tr(lang, "history_title"))
    db_path = st.text_input(tr(lang, "sqlite_path"), value="dailyarxiv.sqlite")
    p = Path(db_path)
    if not p.exists():
        st.info(tr(lang, "no_sqlite"))
        return

    arch = ArchivistSQLite(p)
    stats = arch.stats(days=60).get("recent_runs", [])
    st.dataframe(stats, use_container_width=True)

    st.subheader(tr(lang, "export_by_date"))
    date = st.text_input(tr(lang, "date_input"), value="")
    if st.button(tr(lang, "btn_export_json")):
        if not date.strip():
            st.warning(tr(lang, "need_date"))
        else:
            payload = arch.export_report(date=date.strip())
            st.download_button(
                tr(lang, "download_exported_json"),
                data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name="exported_report.json",
            )

    st.divider()
    st.subheader(tr(lang, "browse_reports"))
    reports_root = st.text_input(tr(lang, "reports_root"), value="reports")
    root = Path(reports_root)
    if root.exists() and root.is_dir():
        dates = sorted([p.name for p in root.iterdir() if p.is_dir()], reverse=True)
        chosen = st.selectbox(tr(lang, "report_date"), options=[tr(lang, "select")] + dates)
        if chosen != tr(lang, "select"):
            d = root / chosen
            html_path = d / "report.html"
            pdf_path = d / "report.pdf"
            if html_path.exists():
                st.download_button(tr(lang, "download_html"), data=html_path.read_bytes(), file_name=f"{chosen}-report.html")
                st.components.v1.html(html_path.read_text(encoding="utf-8"), height=900, scrolling=True)
            if pdf_path.exists():
                st.download_button(tr(lang, "download_pdf"), data=pdf_path.read_bytes(), file_name=f"{chosen}-report.pdf")
    else:
        st.caption(tr(lang, "no_reports_dir"))


def _page_settings() -> None:
    lang = st.session_state.lang
    st.subheader(tr(lang, "diagnostics"))
    st.write(tr(lang, "env_gemini") + ":", tr(lang, "set") if os.getenv("GEMINI_API_KEY") else tr(lang, "missing"))
    st.write(tr(lang, "env_openai") + ":", tr(lang, "set") if os.getenv("OPENAI_API_KEY") else tr(lang, "missing"))

    st.write(tr(lang, "weasyprint") + ":", _weasyprint_ok())
    st.caption(tr(lang, "weasyprint_hint"))


def _page_about() -> None:
    lang = st.session_state.lang
    st.markdown(tr(lang, "about_md"))


def _default_categories() -> list[str]:
    return [
        "cs.AI",
        "cs.CL",
        "cs.CV",
        "cs.LG",
        "cs.RO",
        "stat.ML",
    ]


def _weasyprint_ok() -> bool:
    try:
        from weasyprint import HTML  # noqa: F401

        return True
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
