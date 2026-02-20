from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dailyarxiv.render.renderer import render_report_html


def _latest_report_json() -> Path | None:
    root = Path("reports")
    if not root.exists():
        return None
    candidates = list(root.glob("*/daily_report.json"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def main() -> int:
    report_json = _latest_report_json()
    if not report_json:
        raise SystemExit("No reports/*/daily_report.json found. Run `dailyarxiv run` first.")

    report = json.loads(report_json.read_text(encoding="utf-8"))

    out_dir = Path("previews")
    out_dir.mkdir(parents=True, exist_ok=True)

    variants: list[tuple[str, str]] = [
        ("baseline", "report.html.j2"),
        ("modern", "report_modern.html.j2"),
        ("editorial", "report_editorial.html.j2"),
        ("compact", "report_compact.html.j2"),
    ]

    generated: list[tuple[str, Path]] = []
    for name, template in variants:
        out_path = out_dir / f"report_preview_{name}.html"
        render_report_html(report, out_path, template_name=template)
        generated.append((name, out_path))

    index = out_dir / "index.html"
    cards = "\n".join(
        f"""
        <a class="card" href="{p.name}">
          <div class="t">{name}</div>
          <div class="s">{p.name}</div>
        </a>
        """.strip()
        for name, p in generated
    )
    index.write_text(
        f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>DailyArxiv · Layout Previews</title>
    <style>
      body{{margin:0;background:#0b1020;color:#e5e7eb;font-family:system-ui,-apple-system,"Segoe UI",Arial,"Microsoft YaHei",sans-serif}}
      .wrap{{max-width:1000px;margin:28px auto;padding:0 16px 56px}}
      h1{{margin:0 0 6px;font-size:22px}}
      p{{margin:0 0 18px;color:#9ca3af}}
      .grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}
      .card{{display:block;border:1px solid rgba(148,163,184,.24);background:rgba(15,23,42,.7);border-radius:14px;padding:12px 12px 10px;text-decoration:none;color:inherit}}
      .card:hover{{border-color:rgba(99,102,241,.55)}}
      .t{{font-weight:800;letter-spacing:-.1px}}
      .s{{margin-top:6px;color:#9ca3af;font-size:12px}}
      code{{background:rgba(148,163,184,.12);padding:2px 6px;border-radius:999px}}
      @media (max-width:720px){{.grid{{grid-template-columns:1fr}}}}
    </style>
  </head>
  <body>
    <div class="wrap">
      <h1>DailyArxiv · Layout Previews</h1>
      <p>基于 <code>{report_json.as_posix()}</code> 生成。点击下面任意方案打开预览。</p>
      <div class="grid">{cards}</div>
    </div>
  </body>
</html>
""",
        encoding="utf-8",
    )

    print(f"Wrote {len(generated)} previews to {out_dir.as_posix()}/ (open {index.as_posix()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
