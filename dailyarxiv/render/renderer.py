from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape


_TEMPLATES_BY_SHORT_NAME: dict[str, str] = {
    "baseline": "report.html.j2",
    "editorial": "report_editorial.html.j2",
    "modern": "report_modern.html.j2",
    "compact": "report_compact.html.j2",
}


def render_report_html(report: dict[str, Any], out_path: Path, *, template_name: str = "editorial") -> None:
    env = Environment(autoescape=select_autoescape(["html", "xml"]))
    template_file = _resolve_template_name(template_name)
    template = env.from_string(_load_text("templates", template_file))
    html = template.render(report=report)
    out_path.write_text(html, encoding="utf-8")


def _load_text(*parts: str) -> str:
    pkg = __package__ or "dailyarxiv.render"
    return resources.files(pkg).joinpath(*parts).read_text(encoding="utf-8")


def _resolve_template_name(template_name: str) -> str:
    name = (template_name or "").strip()
    if not name:
        return _TEMPLATES_BY_SHORT_NAME["editorial"]

    short = name.lower()
    if short in _TEMPLATES_BY_SHORT_NAME:
        return _TEMPLATES_BY_SHORT_NAME[short]

    if name.endswith(".j2"):
        return name

    supported = ", ".join(sorted(_TEMPLATES_BY_SHORT_NAME.keys()))
    raise ValueError(f"Unknown template_name={template_name!r}. Use one of: {supported}, or a '*.j2' filename.")
