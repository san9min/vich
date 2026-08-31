"""Generate examples/chunk_visualization.html from
examples/docling_example.{pdf,jsonl}: a self-contained page showing each
source page with its chunks boxed directly on the page image, a cropped
image thumbnail of what each box covers, a card per chunk with its full
text/table and metadata, and a document-wide heading outline (via
vich.outline) linking down to each chunk.

vich's chunks don't carry bounding boxes (the VLM reasons over the whole
page image, not coordinates), so the box(es) for each chunk are *estimated*
by matching the chunk's own text back onto the PDF's text layer (word by
word, tolerant of rewording/skips) and grouping the matched words into
regions: a new region starts wherever the matched reading position jumps
back up the page (a two-column wrap) or skips a large vertical gap (likely
unrelated content in between). A chunk spanning a column break correctly
gets two boxes instead of one giant box swallowing the gutter between them.
`figure` chunks are a special case: a figure itself has no extractable
text, so only its caption matches -- the region is nudged upward to the
nearest preceding text block so the box/crop actually includes the figure,
not just its caption line.

The search isn't limited to a chunk's own declared page_start/page_end,
either: the VLM's self-reported page numbers are sometimes off by a page
or two (observed on this very example -- almost half its chunks), so each
chunk is matched against a small window of nearby pages and shown wherever
the match actually lands, with a note on the card when that differs from
what vich labeled it.

This only works for text-based PDFs, some chunks (especially short,
heavily-paraphrased ones) won't get a confident match at all, and it's
purely a docs/demo convenience -- it is not part of the vich package or its
output schema. (The outline *is* part of vich -- see vich.outline.)

Re-run after regenerating the example PDF or re-running `vich parse`:

    python examples/generate_chunk_visualization.py
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
from itertools import pairwise
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

from vich.outline import OutlineNode, build_outline
from vich.schema import Chunk

EXAMPLES_DIR = Path(__file__).parent
PDF_PATH = EXAMPLES_DIR / "docling_example.pdf"
JSONL_PATH = EXAMPLES_DIR / "docling_example.jsonl"
OUTPUT_PATH = EXAMPLES_DIR / "chunk_visualization.html"
ASSETS_DIR = EXAMPLES_DIR / "assets"
ASSET_PREFIX = "docling_page"

# A chunk needs at least this many matched words, after splitting into
# column/gap-aware regions, before we trust its position enough to draw it.
MIN_MATCHED_WORDS = 6

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
# Chunk text -> approximate bounding box(es), by matching against the PDF's
# own text layer (word-for-word, tolerant of rewording / skips).
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


def _find_best_start(ptoks: list[str], ctoks: list[str], probe_len: int = 10, lookahead: int = 14) -> int | None:
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

    return best_idx if best_score >= max(2, len(probe) // 4) else None


Rect = tuple[float, float, float, float]


def _match_word_rects(page: fitz.Page, chunk: dict, lookahead: int = 14) -> list[Rect]:
    """Word rects on `page` that plausibly correspond to `chunk`'s text, in
    reading order. Tolerant of paraphrasing: a miss just advances the
    pointer rather than aborting, so later distinctive words can still
    re-anchor the match."""
    pwords = _page_words(page)
    ptoks = [_norm(w[4]) for w in pwords]
    ctoks = _chunk_tokens(chunk)
    if not ctoks:
        return []

    start = _find_best_start(ptoks, ctoks, lookahead=lookahead)
    if start is None:
        return []

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

    return matched_rects


def _split_into_regions(rects: list[Rect], gap_tol: float = 40, line_tol: float = 3) -> list[list[Rect]]:
    """Split matched word rects (in reading order) into separate regions
    wherever the reading position jumps back up the page (a column wrap) or
    skips a large vertical gap (likely unrelated content in between, so the
    next match may just be coincidental)."""
    if not rects:
        return []

    regions = [[rects[0]]]
    for prev, curr in pairwise(rects):
        jumped_up = curr[1] < prev[1] - line_tol and curr[1] < prev[3] - line_tol
        big_gap = curr[1] > prev[3] + gap_tol
        if jumped_up or big_gap:
            regions.append([curr])
        else:
            regions[-1].append(curr)
    return regions


def _extend_figure_region_upward(page: fitz.Page, rect: fitz.Rect, max_extend: float = 260) -> fitz.Rect:
    """A figure itself has no extractable text -- only its caption matches
    -- so nudge the region's top edge up to just below the nearest real
    preceding paragraph in the same column, capturing the figure above the
    caption instead of just the caption line(s).

    "Nearest preceding text block" alone isn't enough: a diagram's own
    internal labels (e.g. "PDF", "OCR", "docx") are text blocks too, and
    without filtering them out the extension stops at the diagram's own
    last label instead of reaching above the diagram. Requiring at least a
    handful of words excludes short labels while still matching real
    prose.
    """
    blocks = page.get_text("blocks")  # x0, y0, x1, y1, text, block_no, block_type
    preceding_prose = [
        b
        for b in blocks
        if b[3] <= rect.y0 + 2
        and min(b[2], rect.x1) > max(b[0], rect.x0)
        and len(b[4].split()) >= 8
    ]
    if preceding_prose:
        new_top = max(b[3] for b in preceding_prose) + 4
    else:
        new_top = rect.y0 - max_extend
    new_top = max(new_top, rect.y0 - max_extend, 0)
    return fitz.Rect(rect.x0, new_top, rect.x1, rect.y1)


def _regions_to_boxes(page: fitz.Page, chunk: dict, regions: list[list[Rect]]) -> list[fitz.Rect]:
    boxes = []
    for region in regions:
        x0 = min(r[0] for r in region)
        y0 = min(r[1] for r in region)
        x1 = max(r[2] for r in region)
        y1 = max(r[3] for r in region)
        boxes.append(fitz.Rect(x0, y0, x1, y1))

    if chunk.get("content_type") == "figure" and boxes:
        boxes[0] = _extend_figure_region_upward(page, boxes[0])

    return boxes


def find_best_page_and_regions(
    doc: fitz.Document, chunk: dict, search_radius: int = 3, min_region_size: int = 3
) -> tuple[int | None, list[fitz.Rect]]:
    """Search pages near `chunk`'s declared page_start/page_end for the one
    with the strongest text match, and return (page_num, regions) for it.

    The VLM's own self-reported page numbers are sometimes off by a page or
    two (observed on this very example -- a chunk about "Parser Backends"
    labeled page 2 whose text actually lives on page 3), so trusting the
    declared page alone silently produces "no match" for a chunk that's
    perfectly matchable one page over. Ties are broken by matched-word
    count, not by proximity to the declared page, since a real match
    dominates a coincidental one by a wide margin in practice.
    """
    declared_start = chunk["page_start"]
    declared_end = chunk.get("page_end") or declared_start
    lo = max(1, declared_start - search_radius)
    hi = min(doc.page_count, declared_end + search_radius)

    best_page, best_regions, best_count = None, [], MIN_MATCHED_WORDS - 1
    for page_num in range(lo, hi + 1):
        page = doc.load_page(page_num - 1)
        rects = _match_word_rects(page, chunk)
        regions = [r for r in _split_into_regions(rects) if len(r) >= min_region_size]
        count = sum(len(r) for r in regions)
        if count > best_count:
            best_page, best_count = page_num, count
            best_regions = regions

    if best_page is None:
        return None, []

    return best_page, _regions_to_boxes(doc.load_page(best_page - 1), chunk, best_regions)


# ---------------------------------------------------------------------------
# Rendering: page image, chunk boxes drawn on top, and per-chunk crops.
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def render_page_base(page: fitz.Page, zoom: float = ZOOM) -> Image.Image:
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")


def compose_boxed_image(
    base_image: Image.Image,
    page_chunks: list[tuple[int, dict]],
    chunk_regions: dict[int, list[fitz.Rect]],
    zoom: float = ZOOM,
) -> Image.Image:
    overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("Helvetica", 16)
    except OSError:
        font = ImageFont.load_default()

    for number, chunk in page_chunks:
        color = CONTENT_TYPE_COLORS.get(chunk.get("content_type") or "mixed", "#666666")

        for region_idx, rect in enumerate(chunk_regions.get(number, [])):
            box = (rect.x0 * zoom, rect.y0 * zoom, rect.x1 * zoom, rect.y1 * zoom)
            pad = 4
            box = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)

            draw.rounded_rectangle(box, radius=4, outline=color, width=3)
            draw.rectangle(box, fill=(*_hex_to_rgb(color), 28))

            if region_idx > 0:
                continue  # one number badge per chunk, on its first region

            badge_r = 11
            cx, cy = box[0] + badge_r, box[1] - 2
            draw.ellipse((cx - badge_r, cy - badge_r, cx + badge_r, cy + badge_r), fill=color)
            label = str(number)
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((cx - tw / 2, cy - th / 2 - bbox[1]), label, fill="white", font=font)

    return Image.alpha_composite(base_image, overlay)


def crop_region(base_image: Image.Image, rect: fitz.Rect, zoom: float = ZOOM, pad: int = 4) -> Image.Image:
    box = (
        max(rect.x0 * zoom - pad, 0),
        max(rect.y0 * zoom - pad, 0),
        min(rect.x1 * zoom + pad, base_image.width),
        min(rect.y1 * zoom + pad, base_image.height),
    )
    return base_image.crop(tuple(round(v) for v in box))


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


def chunk_card_html(
    number: int, chunk: dict, thumbnails: list[Image.Image], mismatch_page: int | None = None
) -> str:
    content_type = chunk.get("content_type") or "mixed"
    color = CONTENT_TYPE_COLORS.get(content_type, "#666666")
    body = (
        table_markdown_to_html(chunk["table_markdown"])
        if chunk.get("table_markdown")
        else f"<p>{html.escape(chunk.get('chunk_text') or '')}</p>"
    )
    keywords = ", ".join(chunk.get("keywords") or [])
    keywords_html = f'<div class="keywords">keywords: {html.escape(keywords)}</div>' if keywords else ""
    thumbs_html = "".join(
        f'<img class="thumb" src="data:image/png;base64,{image_to_base64_png(t)}" alt="Cropped source region for {html.escape(chunk["chunk_id"])}" />'
        for t in thumbnails
    )
    thumbs_block = f'<div class="thumbs">{thumbs_html}</div>' if thumbs_html else ""
    mismatch_html = (
        f'<div class="mismatch">&#9888; vich labeled this chunk page {chunk["page_start"]}, '
        f"but its text actually matches page {mismatch_page} &mdash; shown there instead.</div>"
        if mismatch_page is not None
        else ""
    )

    return f"""
    <div class="chunk-card" id="chunk-{number}" style="--accent: {color}">
      <div class="chunk-head">
        <span class="number-badge" style="background:{color}">{number}</span>
        <span class="badge" style="background:{color}">{html.escape(content_type)}</span>
        <code class="chunk-id">{html.escape(chunk['chunk_id'])}</code>
      </div>
      <div class="breadcrumb">{heading_breadcrumb(chunk)}</div>
      {mismatch_html}
      {thumbs_block}
      <div class="chunk-body">{body}</div>
      {keywords_html}
    </div>
    """


def outline_html(nodes: list[OutlineNode], chunk_numbers: dict[str, int]) -> str:
    items = []
    for node in nodes:
        own_links = "".join(
            f'<a class="outline-chunk-link" href="#chunk-{chunk_numbers[cid]}">{chunk_numbers[cid]}</a>'
            for cid in node.chunk_ids
            if cid in chunk_numbers
        )
        children_html = outline_html(node.children, chunk_numbers) if node.children else ""
        items.append(
            f'<li class="outline-l{node.level}">'
            f'<span class="outline-title">{html.escape(node.title)}</span>'
            f'{own_links}'
            f"{children_html}"
            "</li>"
        )
    return f"<ul>{''.join(items)}</ul>"


def build() -> None:
    doc = fitz.open(PDF_PATH)
    raw_chunks = load_chunks(JSONL_PATH)
    numbered_chunks = list(enumerate(raw_chunks, start=1))
    chunk_by_number = dict(numbered_chunks)
    chunk_numbers = {c["chunk_id"]: n for n, c in numbered_chunks}

    outline_nodes = build_outline(Chunk.model_validate(c) for c in raw_chunks)

    # Pass 1: find each chunk's best-matching page (which may differ from
    # its declared page_start -- see find_best_page_and_regions) up front,
    # since a card grouped under its declared page may need a crop sourced
    # from a different page's rendered image.
    chunk_match = {n: find_best_page_and_regions(doc, c) for n, c in numbered_chunks}

    base_images: dict[int, Image.Image] = {}

    def get_base_image(page_num: int) -> Image.Image:
        if page_num not in base_images:
            base_images[page_num] = render_page_base(doc.load_page(page_num - 1))
        return base_images[page_num]

    pages_html = []
    try:
        for page_index in range(doc.page_count):
            page_num = page_index + 1
            base_image = get_base_image(page_num)

            # Cards are grouped under each chunk's *first* declared page (a
            # multi-page chunk would otherwise get one duplicate <div id=...>
            # card per page it spans); boxes are drawn on whichever page(s)
            # the chunk actually matched, which may be neither.
            declared_here = [(n, c) for n, c in numbered_chunks if c["page_start"] == page_num]
            matched_here = [(n, chunk_by_number[n]) for n, (mp, _r) in chunk_match.items() if mp == page_num]
            regions_here = {n: chunk_match[n][1] for n, _c in matched_here}

            boxed_image = compose_boxed_image(base_image, matched_here, regions_here)
            image_b64 = image_to_base64_png(boxed_image)

            ASSETS_DIR.mkdir(exist_ok=True)
            boxed_image.convert("RGB").save(ASSETS_DIR / f"{ASSET_PREFIX}_{page_num}.png")

            cards = (
                "\n".join(
                    chunk_card_html(
                        n,
                        c,
                        [crop_region(get_base_image(mp), rect) for rect in regions] if mp else [],
                        mismatch_page=mp if mp and mp != c["page_start"] else None,
                    )
                    for n, c in declared_here
                    for mp, regions in [chunk_match[n]]
                )
                or "<p class='empty'>No chunks.</p>"
            )
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
    --bg: #ffffff; --fg: #1a1d24; --muted: #6b7280; --border: #e2e5ea; --card-bg: #fafbfc; --accent-soft: #eef1f8;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #14161a; --fg: #e7e9ee; --muted: #9aa1ad; --border: #2a2e37; --card-bg: #1b1e24; --accent-soft: #1c2333; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 24px 64px; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  h2 {{ font-size: 1.05rem; margin: 0 0 10px; }}
  .subtitle {{ color: var(--muted); margin-top: 0; margin-bottom: 6px; font-size: 0.95rem; }}
  .caveat {{ color: var(--muted); margin-top: 0; margin-bottom: 20px; font-size: 0.8rem; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 28px; font-size: 0.85rem; color: var(--muted); }}
  .legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}

  .outline {{ border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; margin-bottom: 32px; background: var(--card-bg); }}
  .outline ul {{ list-style: none; margin: 0; padding-left: 18px; }}
  .outline > ul {{ padding-left: 0; }}
  .outline li {{ margin: 3px 0; }}
  .outline-title {{ font-size: 0.9rem; }}
  .outline-l1 > .outline-title {{ font-weight: 700; font-size: 1rem; }}
  .outline-l2 > .outline-title {{ font-weight: 600; color: var(--fg); }}
  .outline-l3 > .outline-title {{ color: var(--muted); }}
  .outline-chunk-link {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 18px; height: 18px; margin-left: 6px; border-radius: 50%;
    background: var(--accent-soft); color: var(--fg); font-size: 0.68rem; font-weight: 600;
    text-decoration: none; vertical-align: middle;
  }}
  .outline-chunk-link:hover {{ outline: 1px solid var(--muted); }}

  .page-row {{ display: grid; grid-template-columns: minmax(280px, 460px) 1fr; gap: 24px; margin-bottom: 40px; align-items: start; }}
  .page-image {{ position: sticky; top: 16px; }}
  .page-image img {{ width: 100%; border: 1px solid var(--border); border-radius: 6px; display: block; }}
  .page-label {{ text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 6px; }}
  .page-chunks {{ display: flex; flex-direction: column; gap: 14px; min-width: 0; }}
  .chunk-card {{ border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: 6px; padding: 12px 14px; background: var(--card-bg); scroll-margin-top: 16px; }}
  .chunk-card:target {{ outline: 2px solid var(--accent); }}
  .chunk-head {{ display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }}
  .number-badge {{ color: white; font-size: 0.72rem; font-weight: 700; width: 20px; height: 20px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }}
  .badge {{ color: white; font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.02em; }}
  .chunk-id {{ font-size: 0.75rem; color: var(--muted); }}
  .breadcrumb {{ font-size: 0.8rem; color: var(--muted); margin-bottom: 8px; }}
  .mismatch {{ font-size: 0.76rem; color: #a35b00; background: rgba(201,133,43,0.12); border-radius: 4px; padding: 4px 8px; margin-bottom: 8px; }}
  .thumbs {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }}
  .thumbs .thumb {{ max-width: 100%; max-height: 160px; border: 1px solid var(--border); border-radius: 4px; display: block; }}
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
  <p class="subtitle">examples/docling_example.pdf &rarr; {len(raw_chunks)} chunks. Numbered boxes on the page match the numbered cards on the right.</p>
  <p class="caveat">Boxes/crops are estimated by matching each chunk's text back onto the PDF's text layer (vich's chunk schema has no bounding boxes) &mdash; a docs-only convenience, not part of vich's output. A chunk is searched for near its declared page, not only on it, since the VLM's self-reported page numbers are sometimes off by one (flagged on the card when that happens); some chunks still won't get a confident enough match to draw. The outline below, though, <em>is</em> a real vich feature (see <code>vich.outline</code>).</p>
  <div class="legend">{legend}</div>
  <div class="outline">
    <h2>Document outline</h2>
    {outline_html(outline_nodes, chunk_numbers)}
  </div>
  {''.join(pages_html)}
</body>
</html>
"""

    OUTPUT_PATH.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(raw_chunks)} chunks across {len(pages_html)} pages)")


if __name__ == "__main__":
    build()
