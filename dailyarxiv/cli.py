from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_settings
from .pipeline import run_pipeline
from .render.weasyprint_renderer import render_html_to_pdf_if_available
from .render.renderer import render_report_html


def _cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings(Path(args.config))
    if getattr(args, "template", None):
        settings.output.html_template = str(args.template)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        settings=settings,
        out_root=out_dir,
        date_arg=args.date,
        max_results=args.max_results,
        max_selected=args.max_selected,
        dry_run=args.dry_run,
        html_only=args.html_only,
        pdf_only=args.pdf_only,
    )

    print(f"Report date: {result['report_date']}")
    print(f"Output dir:  {result['out_dir']}")
    if result.get("html_path"):
        print(f"HTML:       {result['html_path']}")
    if result.get("pdf_path"):
        print(f"PDF:        {result['pdf_path']}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    in_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report = json.loads(in_path.read_text(encoding="utf-8"))
    html_path = out_dir / "report.html"
    render_report_html(report, html_path, template_name=str(args.template))

    pdf_path = out_dir / "report.pdf"
    if not args.html_only:
        render_html_to_pdf_if_available(html_path, pdf_path)
    print(f"HTML: {html_path}")
    if pdf_path.exists():
        print(f"PDF:  {pdf_path}")
    return 0


def _cmd_db(args: argparse.Namespace) -> int:
    from .archivist_sqlite import ArchivistSQLite

    db_path = Path(args.db)
    arch = ArchivistSQLite(db_path)
    if args.subcmd == "stats":
        stats = arch.stats(days=args.days)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    if args.subcmd == "export":
        payload = arch.export_report(date=args.date)
        if args.format == "json":
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            if args.out:
                out_path = Path(args.out)
                out_path.write_text(text, encoding="utf-8")
                print(str(out_path))
                return 0
            sys.stdout.write(text)
            return 0
        raise ValueError(f"Unsupported format: {args.format}")
    raise ValueError(f"Unknown db subcmd: {args.subcmd}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dailyarxiv")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Harvest, filter, analyze, and render HTML/PDF.")
    p_run.add_argument("--config", default="config.yaml")
    p_run.add_argument("--out-dir", default="reports")
    p_run.add_argument("--date", default="auto", help="auto or YYYY-MM-DD")
    p_run.add_argument("--max-results", type=int, default=None)
    p_run.add_argument("--max-selected", type=int, default=None)
    p_run.add_argument("--dry-run", action="store_true", help="Only harvest; do not call LLM.")
    p_run.add_argument("--html-only", action="store_true")
    p_run.add_argument("--pdf-only", action="store_true")
    p_run.add_argument(
        "--template",
        default=None,
        help="HTML template: editorial|baseline|modern|compact, or a '*.j2' filename.",
    )
    p_run.set_defaults(func=_cmd_run)

    p_render = sub.add_parser("render", help="Render HTML/PDF from daily_report.json.")
    p_render.add_argument("--input", required=True)
    p_render.add_argument("--out-dir", required=True)
    p_render.add_argument("--html-only", action="store_true")
    p_render.add_argument(
        "--template",
        default="editorial",
        help="HTML template: editorial|baseline|modern|compact, or a '*.j2' filename.",
    )
    p_render.set_defaults(func=_cmd_render)

    p_db = sub.add_parser("db", help="Inspect the SQLite archive.")
    p_db.add_argument("--db", default="dailyarxiv.sqlite")
    sub_db = p_db.add_subparsers(dest="subcmd", required=True)
    p_stats = sub_db.add_parser("stats")
    p_stats.add_argument("--days", type=int, default=30)
    p_export = sub_db.add_parser("export")
    p_export.add_argument("--date", required=True)
    p_export.add_argument("--format", default="json")
    p_export.add_argument("--out", default=None, help="Write output to file (utf-8) instead of stdout.")
    p_db.set_defaults(func=_cmd_db)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
