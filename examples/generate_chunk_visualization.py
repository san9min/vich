"""Generate examples/chunk_visualization.html from
examples/nimbus_storage_plan.{pdf,jsonl}: a self-contained page showing each
source page image next to the chunks vich extracted from it.

Re-run after regenerating the example PDF or re-running `vich parse`:

    python examples/generate_chunk_visualization.py
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

import fitz  # PyMuPDF

EXAMPLES_DIR = Path(__file__).parent
PDF_PATH = EXAMPLES_DIR / "nimbus_storage_plan.pdf"
JSONL_PATH = EXAMPLES_DIR / "nimbus_storage_plan.jsonl"
OUTPUT_PATH = EXAMPLES_DIR / "chunk_visualization.html"

CONTENT_TYPE_COLORS = {
    "paragraph": "#3b6fd6",
    "table": "#1f9d55",
    "boxed_section": "#c9852b",
    "list": "#8452c9",
    "footnote": "#0f9aa8",
    "figure": "#c14f8a",
    "mixed": "#666666",
}


def render_pages_base64(pdf_path: Path, zoom: float = 2.0) -> dict[int, str]:
    doc = fitz.open(pdf_path)
    images: dict[int, str] = {}
    try:
        for i in range(doc.page_count):
            pix = doc.load_page(i).get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            images[i + 1] = base64.b64encode(pix.tobytes("png")).decode("utf-8")
    finally:
        doc.close()
    return images


def load_chunks(jsonl_path: Path) -> list[dict]:
    with jsonl_path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def table_markdown_to_html(markdown_table: str) -> str:
    rows = [r.strip() for r in markdown_table.strip().splitlines() if r.strip()]
    if len(rows) < 2:
        return f"<pre>{html.escape(markdown_table)}</pre>"

    def cells(row: str) -> list[str]:
        return [c.strip() for c in row.strip("|").split("|")]

    header = cells(rows[0])
    body_rows = [cells(r) for r in rows[2:]]  # rows[1] is the '---' separator

    thead = "".join(f"<th>{html.escape(c)}</th>" for c in header)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in body_rows
    )
    return f'<table class="chunk-table"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>'


def heading_breadcrumb(chunk: dict) -> str:
    parts = [
        chunk.get("level_1_heading"),
        chunk.get("level_2_heading"),
        chunk.get("level_3_heading"),
    ]
    parts = [p for p in parts if p]
    return " &rsaquo; ".join(html.escape(p) for p in parts)


def chunk_card_html(chunk: dict) -> str:
    content_type = chunk.get("content_type") or "mixed"
    color = CONTENT_TYPE_COLORS.get(content_type, "#666666")
    body = (
        table_markdown_to_html(chunk["table_markdown"])
        if chunk.get("table_markdown")
        else f"<p>{html.escape(chunk.get('chunk_text') or '')}</p>"
    )
    keywords = ", ".join(chunk.get("keywords") or [])
    keywords_html = f'<div class="keywords">keywords: {html.escape(keywords)}</div>' if keywords else ""

    return f"""
    <div class="chunk-card" style="--accent: {color}">
      <div class="chunk-head">
        <span class="badge" style="background:{color}">{html.escape(content_type)}</span>
        <code class="chunk-id">{html.escape(chunk['chunk_id'])}</code>
      </div>
      <div class="breadcrumb">{heading_breadcrumb(chunk)}</div>
      <div class="chunk-body">{body}</div>
      {keywords_html}
    </div>
    """


def build() -> None:
    page_images = render_pages_base64(PDF_PATH)
    chunks = load_chunks(JSONL_PATH)

    pages_html = []
    for page_num, image_b64 in sorted(page_images.items()):
        page_chunks = [c for c in chunks if c["page_start"] <= page_num <= c["page_end"]]
        cards = "\n".join(chunk_card_html(c) for c in page_chunks) or "<p class='empty'>No chunks.</p>"
        pages_html.append(
            f"""
        <section class="page-row">
          <div class="page-image">
            <img src="data:image/png;base64,{image_b64}" alt="Source PDF page {page_num}" />
            <div class="page-label">page {page_num}</div>
          </div>
          <div class="page-chunks">{cards}</div>
        </section>
        """
        )

    legend = "".join(
        f'<span class="legend-item"><span class="dot" style="background:{color}"></span>{name}</span>'
        for name, color in CONTENT_TYPE_COLORS.items()
    )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>ViCH chunk visualization</title>
<style>
  :root {{
    --bg: #ffffff; --fg: #1a1d24; --muted: #6b7280; --border: #e2e5ea; --card-bg: #fafbfc;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #14161a; --fg: #e7e9ee; --muted: #9aa1ad; --border: #2a2e37; --card-bg: #1b1e24; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 24px 64px; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); margin-top: 0; margin-bottom: 20px; font-size: 0.95rem; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 28px; font-size: 0.85rem; color: var(--muted); }}
  .legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .page-row {{ display: grid; grid-template-columns: minmax(220px, 320px) 1fr; gap: 24px; margin-bottom: 40px; align-items: start; }}
  .page-image {{ position: sticky; top: 16px; }}
  .page-image img {{ width: 100%; border: 1px solid var(--border); border-radius: 6px; display: block; }}
  .page-label {{ text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 6px; }}
  .page-chunks {{ display: flex; flex-direction: column; gap: 14px; min-width: 0; }}
  .chunk-card {{ border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: 6px; padding: 12px 14px; background: var(--card-bg); }}
  .chunk-head {{ display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }}
  .badge {{ color: white; font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.02em; }}
  .chunk-id {{ font-size: 0.75rem; color: var(--muted); }}
  .breadcrumb {{ font-size: 0.8rem; color: var(--muted); margin-bottom: 8px; }}
  .chunk-body p {{ margin: 0; line-height: 1.5; font-size: 0.92rem; white-space: pre-wrap; }}
  .keywords {{ margin-top: 8px; font-size: 0.78rem; color: var(--muted); }}
  table.chunk-table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
  table.chunk-table th, table.chunk-table td {{ border: 1px solid var(--border); padding: 6px 8px; text-align: left; }}
  table.chunk-table th {{ background: rgba(59,111,214,0.12); }}
  .empty {{ color: var(--muted); font-size: 0.85rem; }}
  @media (max-width: 720px) {{
    .page-row {{ grid-template-columns: 1fr; }}
    .page-image {{ position: static; }}
  }}
</style>
</head>
<body>
  <h1>ViCH chunk visualization</h1>
  <p class="subtitle">examples/nimbus_storage_plan.pdf &rarr; {len(chunks)} chunks. Each card is one chunk vich extracted from the page on its left.</p>
  <div class="legend">{legend}</div>
  {''.join(pages_html)}
</body>
</html>
"""

    OUTPUT_PATH.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(chunks)} chunks across {len(page_images)} pages)")


if __name__ == "__main__":
    build()
