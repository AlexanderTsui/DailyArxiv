from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape


def render_report_html(report: dict[str, Any], out_path: Path) -> None:
    env = Environment(autoescape=select_autoescape(["html", "xml"]))
    template = env.from_string(_load_text("templates", "report.html.j2"))
    html = template.render(report=report)
    out_path.write_text(html, encoding="utf-8")


def _load_text(*parts: str) -> str:
    pkg = __package__ or "dailyarxiv.render"
    return resources.files(pkg).joinpath(*parts).read_text(encoding="utf-8")
