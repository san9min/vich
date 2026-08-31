"""Generate examples/chunk_visualization.html from
examples/nimbus_storage_plan.{pdf,jsonl}: a self-contained page showing each
source page with its chunks boxed directly on the page image, plus a card
per chunk with its full text/table and metadata.

vich's chunks don't carry bounding boxes (the VLM reasons over the whole
page image, not coordinates), so the box for each chunk is *estimated* by
matching the chunk's own text back onto the PDF's text layer (word by word,
tolerant of minor rewording) and taking the bounding rect of the matched
words. This only works for text-based PDFs, and is purely a docs/demo
convenience -- it is not part of the vich package or its output schema.

Re-run after regenerating the example PDF or re-running `vich parse`:

    python examples/generate_chunk_visualization.py
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

EXAMPLES_DIR = Path(__file__).parent
PDF_PATH = EXAMPLES_DIR / "nimbus_storage_plan.pdf"
JSONL_PATH = EXAMPLES_DIR / "nimbus_storage_plan.jsonl"
OUTPUT_PATH = EXAMPLES_DIR / "chunk_visualization.html"
ASSETS_DIR = EXAMPLES_DIR / "assets"

ZOOM = 2.0

CONTENT_TYPE_COLORS = {
    "paragraph": "#3b6fd6",
    "table": "#1f9d55",
    "boxed_section": "#c9852b",
    "list": "#8452c9",
    "footnote": "#0f9aa8",
    "figure": "#c14f8a",
    "mixed": "#666666",
}


def load_chunks(jsonl_path: Path) -> list[dict]:
    with jsonl_path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# ---------------------------------------------------------------------------
# Chunk text -> approximate bounding box, by matching against the PDF's own
# text layer (word-for-word, tolerant of small VLM rewording / skips).
# ---------------------------------------------------------------------------


def _norm(token: str) -> str:
    return re.sub(r"[^\w가-힣]+", "", token).lower()


def _page_words(page: fitz.Page) -> list[tuple[float, float, float, float, str]]:
    words = page.get_text("words")  # x0, y0, x1, y1, text, block_no, line_no, word_no
    words.sort(key=lambda w: (w[5], w[6], w[7]))
    return [(w[0], w[1], w[2], w[3], w[4]) for w in words]


def _chunk_tokens(chunk: dict) -> list[str]:
    raw = chunk["table_markdown"] if chunk.get("table_markdown") else (chunk.get("chunk_text") or "")
    return [t for t in (_norm(tok) for tok in raw.split()) if t]


def _find_best_start(ptoks: list[str], ctoks: list[str], probe_len: int = 10, lookahead: int = 8) -> int | None:
    """Pick the occurrence of ctoks[0] in ptoks that best continues matching
    the next few chunk tokens, since a chunk's first word (e.g. "Plan") may
    also appear earlier on the page in an unrelated heading."""
    candidates = [idx for idx, w in enumerate(ptoks) if w == ctoks[0]]
    if not candidates:
        return None

    probe = ctoks[:probe_len]
    best_idx, best_score = None, -1
    for cand in candidates:
        pi, score = cand, 0
        for tok in probe:
            matched = False
            for look in range(lookahead):
                if pi + look < len(ptoks) and ptoks[pi + look] == tok:
                    pi = pi + look + 1
                    score += 1
                    matched = True
                    break
            if not matched:
                pi += 1
        if score > best_score:
            best_idx, best_score = cand, score

    return best_idx if best_score >= max(2, len(probe) // 3) else None


def estimate_chunk_bbox(page: fitz.Page, chunk: dict, lookahead: int = 8) -> tuple[fitz.Rect, float] | None:
    """Best-effort (bbox, match_ratio) for where `chunk` lives on `page`."""
    pwords = _page_words(page)
    ptoks = [_norm(w[4]) for w in pwords]
    ctoks = _chunk_tokens(chunk)
    if not ctoks:
        return None

    start = _find_best_start(ptoks, ctoks, lookahead=lookahead)
    if start is None:
        return None

    i, matched_rects = start, []
    for tok in ctoks:
        found = False
        for look in range(lookahead):
            if i + look < len(pwords) and ptoks[i + look] == tok:
                i = i + look
                matched_rects.append(pwords[i][:4])
                i += 1
                found = True
                break
        if not found:
            i += 1

    if not matched_rects:
        return None

    x0 = min(r[0] for r in matched_rects)
    y0 = min(r[1] for r in matched_rects)
    x1 = max(r[2] for r in matched_rects)
    y1 = max(r[3] for r in matched_rects)
    ratio = len(matched_rects) / len(ctoks)
    return fitz.Rect(x0, y0, x1, y1), ratio


# ---------------------------------------------------------------------------
# Rendering: page image with chunk boxes drawn on top.
# ---------------------------------------------------------------------------


def render_boxed_page(page: fitz.Page, page_chunks: list[tuple[int, dict]], zoom: float = ZOOM) -> Image.Image:
    """`page_chunks` is [(global_chunk_number, chunk), ...] for this page."""
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    base = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("Helvetica", 16)
    except OSError:
        font = ImageFont.load_default()

    for number, chunk in page_chunks:
        result = estimate_chunk_bbox(page, chunk)
        if result is None:
            continue
        rect, _ratio = result
        color = CONTENT_TYPE_COLORS.get(chunk.get("content_type") or "mixed", "#666666")
        box = (rect.x0 * zoom, rect.y0 * zoom, rect.x1 * zoom, rect.y1 * zoom)
        pad = 4
        box = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)

        draw.rounded_rectangle(box, radius=4, outline=color, width=3)
        draw.rectangle(box, fill=(*_hex_to_rgb(color), 28))

        badge_r = 11
        cx, cy = box[0] + badge_r, box[1] - 2
        draw.ellipse((cx - badge_r, cy - badge_r, cx + badge_r, cy + badge_r), fill=color)
        label = str(number)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2, cy - th / 2 - bbox[1]), label, fill="white", font=font)

    return Image.alpha_composite(base, overlay)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def image_to_base64_png(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------


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
    parts = [chunk.get("level_1_heading"), chunk.get("level_2_heading"), chunk.get("level_3_heading")]
    parts = [p for p in parts if p]
    return " &rsaquo; ".join(html.escape(p) for p in parts)


def chunk_card_html(number: int, chunk: dict) -> str:
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
        <span class="number-badge" style="background:{color}">{number}</span>
        <span class="badge" style="background:{color}">{html.escape(content_type)}</span>
        <code class="chunk-id">{html.escape(chunk['chunk_id'])}</code>
      </div>
      <div class="breadcrumb">{heading_breadcrumb(chunk)}</div>
      <div class="chunk-body">{body}</div>
      {keywords_html}
    </div>
    """


def build() -> None:
    doc = fitz.open(PDF_PATH)
    chunks = load_chunks(JSONL_PATH)
    numbered_chunks = list(enumerate(chunks, start=1))

    pages_html = []
    try:
        for page_index in range(doc.page_count):
            page_num = page_index + 1
            page = doc.load_page(page_index)
            page_chunks = [(n, c) for n, c in numbered_chunks if c["page_start"] <= page_num <= c["page_end"]]

            boxed_image = render_boxed_page(page, page_chunks)
            image_b64 = image_to_base64_png(boxed_image)

            ASSETS_DIR.mkdir(exist_ok=True)
            boxed_image.convert("RGB").save(ASSETS_DIR / f"nimbus_page_{page_num}.png")

            cards = "\n".join(chunk_card_html(n, c) for n, c in page_chunks) or "<p class='empty'>No chunks.</p>"
            pages_html.append(
                f"""
            <section class="page-row">
              <div class="page-image">
                <img src="data:image/png;base64,{image_b64}" alt="Source PDF page {page_num} with chunk boxes" />
                <div class="page-label">page {page_num}</div>
              </div>
              <div class="page-chunks">{cards}</div>
            </section>
            """
            )
    finally:
        doc.close()

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
  .subtitle {{ color: var(--muted); margin-top: 0; margin-bottom: 6px; font-size: 0.95rem; }}
  .caveat {{ color: var(--muted); margin-top: 0; margin-bottom: 20px; font-size: 0.8rem; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 28px; font-size: 0.85rem; color: var(--muted); }}
  .legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .page-row {{ display: grid; grid-template-columns: minmax(280px, 460px) 1fr; gap: 24px; margin-bottom: 40px; align-items: start; }}
  .page-image {{ position: sticky; top: 16px; }}
  .page-image img {{ width: 100%; border: 1px solid var(--border); border-radius: 6px; display: block; }}
  .page-label {{ text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 6px; }}
  .page-chunks {{ display: flex; flex-direction: column; gap: 14px; min-width: 0; }}
  .chunk-card {{ border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: 6px; padding: 12px 14px; background: var(--card-bg); }}
  .chunk-head {{ display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }}
  .number-badge {{ color: white; font-size: 0.72rem; font-weight: 700; width: 20px; height: 20px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }}
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
  <p class="subtitle">examples/nimbus_storage_plan.pdf &rarr; {len(chunks)} chunks. Numbered boxes on the page match the numbered cards on the right.</p>
  <p class="caveat">Boxes are estimated by matching each chunk's text back onto the PDF's text layer (vich's chunk schema has no bounding boxes) &mdash; a docs-only convenience, not part of vich's output.</p>
  <div class="legend">{legend}</div>
  {''.join(pages_html)}
</body>
</html>
"""

    OUTPUT_PATH.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(chunks)} chunks across {len(pages_html)} pages)")


if __name__ == "__main__":
    build()
