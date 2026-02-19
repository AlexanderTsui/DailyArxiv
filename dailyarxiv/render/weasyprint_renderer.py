from __future__ import annotations

from pathlib import Path


def render_html_to_pdf_if_available(html_path: Path, pdf_path: Path) -> None:
    try:
        from weasyprint import HTML  # type: ignore
    except Exception:
        return

    try:
        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    except Exception:
        # Best-effort: HTML is still produced.
        return

