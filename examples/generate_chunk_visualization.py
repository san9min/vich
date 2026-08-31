"""Generate examples/chunk_visualization.html from
examples/docling_example.{pdf,jsonl}: a self-contained page showing each
source page with its chunks boxed directly on the page image, a cropped
image thumbnail of what each box covers, a card per chunk with its full
text/table and metadata, and a document-wide heading outline (via
vich.outline) linking down to each chunk.

Color is used to show the heading hierarchy, not content_type: every
distinct level_2 (falling back to level_1) heading gets its own color, so
a page's boxes and a page's cards visually cluster by section -- matching
the "hierarchical" half of what vich actually does. content_type still
shows up as a text badge on each card, just not via color anymore. Cards
within a page are additionally grouped (and visually bracketed) by their
full level_2/level_3 heading pair.

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
or two (observed on this very example -- several of its chunks), so each
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
import colorsys
import html
import io
import json
import re
from itertools import groupby, pairwise
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
    "footnote": "#0f9aa8",
    "figure": "#c14f8a",
    "mixed": "#666666",
}


def load_chunks(jsonl_path: Path) -> list[dict]:
    with jsonl_path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# ---------------------------------------------------------------------------
# Heading-based color assignment: every distinct section gets its own color,
# so boxes/cards visually cluster by where they sit in the document's
# hierarchy rather than by their (separately badged) content_type.
# ---------------------------------------------------------------------------


def section_key(chunk: dict) -> str:
    """The heading a chunk's color is grouped by: level_2, falling back to
    level_1 for chunks with no section heading of their own."""
    return chunk.get("level_2_heading") or chunk.get("level_1_heading") or "Untitled"


def _heading_group_key(chunk: dict) -> tuple[str | None, str | None]:
    """Finer-grained than section_key(): used to cluster cards within a
    page, since two chunks can share a level_2 section but sit under
    different level_3 subtopics."""
    return (chunk.get("level_2_heading"), chunk.get("level_3_heading"))


_GOLDEN_ANGLE = 0.6180339887498949  # 137.5..deg / 360, as a hue-wheel fraction


def assign_section_colors(chunks: list[dict]) -> dict[str, str]:
    """One color per distinct section_key(), in order of first appearance.

    Adjacent *sections* in reading order are exactly the ones that end up
    next to each other on a page, so evenly spacing hues by 360/n is the
    wrong distribution -- it puts sequential sections at the *smallest*
    hue step from one another. Stepping by the golden angle instead
    spreads every consecutive pair far apart on the wheel (the classic
    phyllotaxis trick), so neighboring sections stay visually distinct
    regardless of how many sections there are.
    """
    order: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        key = section_key(chunk)
        if key not in seen:
            seen.add(key)
            order.append(key)

    colors = []
    for i in range(len(order)):
        hue = (i * _GOLDEN_ANGLE) % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.45, 0.6)
        colors.append(f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}")

    return dict(zip(order, colors))


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


def _match_from(pwords: list, ptoks: list[str], ctoks: list[str], lookahead: int) -> list[Rect]:
    """Walk forward through `ctoks` from its own first token, anchoring
    into `ptoks` and advancing past misses without aborting."""
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


def _match_word_rects(
    page: fitz.Page, chunk: dict, lookahead: int = 14, num_anchors: int = 6
) -> tuple[list[Rect], int]:
    """Word rects on `page` that plausibly correspond to `chunk`'s text, in
    reading order, plus the index into the chunk's own token list the
    match actually started from.

    A chunk that continues across a page break (which is the point of
    batching multiple pages into one VLM call: content isn't artificially
    split just because of where a page ends) only has its *tail* on a
    later page -- anchoring solely on the chunk's first token, as a single
    pass would, finds nothing there, since that token lives on the earlier
    page. Trying a handful of anchor points spread through the chunk (not
    just its start) and keeping whichever extends the furthest lets a
    later page's share of a split chunk match on its own merits.
    """
    pwords = _page_words(page)
    ptoks = [_norm(w[4]) for w in pwords]
    ctoks = _chunk_tokens(chunk)
    if not ctoks:
        return [], 0

    best_rects: list[Rect] = []
    best_offset = 0
    offsets = sorted({len(ctoks) * i // num_anchors for i in range(num_anchors)})
    for offset in offsets:
        sub_ctoks = ctoks[offset:]
        if not sub_ctoks:
            continue
        rects = _match_from(pwords, ptoks, sub_ctoks, lookahead)
        if len(rects) > len(best_rects):
            best_rects, best_offset = rects, offset

    return best_rects, best_offset


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


def find_matching_pages(
    doc: fitz.Document, chunk: dict, search_radius: int = 3, min_region_size: int = 3
) -> list[tuple[int, list[fitz.Rect]]]:
    """Search pages near `chunk`'s declared page_start/page_end for where
    it actually matches, and return [(page_num, regions), ...] -- usually
    one page, but two when the chunk genuinely continues across a page
    break (the point of batching multiple pages into one VLM call: content
    isn't artificially split just because of where a page ends -- a chunk
    like that should show up on both pages, not get silently collapsed
    onto whichever one "wins").

    The VLM's own self-reported page numbers are sometimes off by a page or
    two as well, so the declared page isn't trusted on its own either --
    every page in the search window is scored, and the one with the
    strongest match ("primary") wins by matched-word count, since a real
    match dominates a coincidental one by a wide margin in practice.

    A second page is added only when primary's own best match starts well
    into the chunk (`_match_word_rects`' anchor offset, not near token 0) --
    i.e. primary plausibly holds the *tail* of a split chunk -- and an
    earlier page in the window independently matches strongly starting
    near token 0, plausibly holding the *head*. (This catches a chunk
    split head/tail across two pages; a tail split across a *third* page
    isn't handled.)
    """
    declared_start = chunk["page_start"]
    declared_end = chunk.get("page_end") or declared_start
    lo = max(1, declared_start - search_radius)
    hi = min(doc.page_count, declared_end + search_radius)
    ctoks_len = len(_chunk_tokens(chunk))

    scored: dict[int, tuple[int, int, list[list[Rect]]]] = {}  # page -> (count, offset, regions)
    for page_num in range(lo, hi + 1):
        page = doc.load_page(page_num - 1)
        rects, offset = _match_word_rects(page, chunk)
        regions = [r for r in _split_into_regions(rects) if len(r) >= min_region_size]
        count = sum(len(r) for r in regions)
        if count >= MIN_MATCHED_WORDS:
            scored[page_num] = (count, offset, regions)

    if not scored:
        return []

    primary_page = max(scored, key=lambda p: scored[p][0])
    _primary_count, primary_offset, _primary_regions = scored[primary_page]
    result_pages = [primary_page]

    near_chunk_start = ctoks_len * 0.1
    # A head candidate needs to cover a real fraction of the chunk, not
    # just clear MIN_MATCHED_WORDS -- a handful of common words landing
    # near the top of an unrelated page is a coincidence, not a head split
    # (observed in practice: two chunks each had a same-sized ~14-word,
    # offset-0 "candidate" on an unrelated page, well short of this bar).
    min_head_count = max(20, int(ctoks_len * 0.15))
    if primary_offset > near_chunk_start:
        head_candidates = {
            p: v
            for p, v in scored.items()
            if p < primary_page and v[1] <= near_chunk_start and v[0] >= min_head_count
        }
        if head_candidates:
            result_pages.append(max(head_candidates, key=lambda p: head_candidates[p][0]))

    result_pages.sort()
    return [(p, _regions_to_boxes(doc.load_page(p - 1), chunk, scored[p][2])) for p in result_pages]


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
    section_colors: dict[str, str],
    zoom: float = ZOOM,
) -> Image.Image:
    overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("Helvetica", 16)
    except OSError:
        font = ImageFont.load_default()

    for number, chunk in page_chunks:
        color = section_colors.get(section_key(chunk), "#666666")

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
    number: int,
    chunk: dict,
    thumbnails: list[Image.Image],
    section_colors: dict[str, str],
    matched_pages: list[int] | None = None,
) -> str:
    matched_pages = matched_pages or []
    content_type = chunk.get("content_type") or "mixed"
    type_color = CONTENT_TYPE_COLORS.get(content_type, "#666666")
    accent_color = section_colors.get(section_key(chunk), "#666666")
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

    note_html = ""
    if len(matched_pages) > 1:
        pages_str = ", ".join(str(p) for p in matched_pages)
        note_html = (
            f'<div class="mismatch">&#8646; this chunk spans pages {pages_str} in the source '
            f"(vich labeled it page {chunk['page_start']}) &mdash; boxed on each.</div>"
        )
    elif len(matched_pages) == 1 and matched_pages[0] != chunk["page_start"]:
        note_html = (
            f'<div class="mismatch">&#9888; vich labeled this chunk page {chunk["page_start"]}, '
            f"but its text actually matches page {matched_pages[0]} &mdash; shown there instead.</div>"
        )

    return f"""
    <div class="chunk-card" id="chunk-{number}" style="--accent: {accent_color}">
      <div class="chunk-head">
        <span class="number-badge" style="background:{accent_color}">{number}</span>
        <span class="badge" style="background:{type_color}">{html.escape(content_type)}</span>
        <code class="chunk-id">{html.escape(chunk['chunk_id'])}</code>
      </div>
      <div class="breadcrumb">{heading_breadcrumb(chunk)}</div>
      {note_html}
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


def render_grouped_cards(
    declared_here: list[tuple[int, dict]],
    chunk_match: dict[int, list[tuple[int, list[fitz.Rect]]]],
    section_colors: dict[str, str],
    get_base_image,
) -> str:
    """Cards for one page's chunks, clustered into a bracketed, colored
    group per (level_2, level_3) heading pair -- so the card list itself
    shows the hierarchy, not just a breadcrumb line on each card."""
    if not declared_here:
        return "<p class='empty'>No chunks.</p>"

    groups_html = []
    for (l2, l3), group_iter in groupby(declared_here, key=lambda item: _heading_group_key(item[1])):
        group = list(group_iter)
        color = section_colors.get(section_key(group[0][1]), "#666666")
        label_parts = [p for p in (l2, l3) if p]
        label = " &rsaquo; ".join(html.escape(p) for p in label_parts) if label_parts else "No heading"

        cards_html = "\n".join(
            chunk_card_html(
                n,
                c,
                [crop_region(get_base_image(mp), rect) for mp, regions in matches for rect in regions],
                section_colors,
                matched_pages=[mp for mp, _regions in matches],
            )
            for n, c in group
            for matches in [chunk_match[n]]
        )
        groups_html.append(
            f'<div class="heading-group" style="--group-color: {color}">'
            f'<div class="heading-group-label">{label}</div>'
            f"{cards_html}"
            "</div>"
        )
    return "\n".join(groups_html)


def build() -> None:
    doc = fitz.open(PDF_PATH)
    raw_chunks = load_chunks(JSONL_PATH)
    numbered_chunks = list(enumerate(raw_chunks, start=1))
    chunk_by_number = dict(numbered_chunks)
    chunk_numbers = {c["chunk_id"]: n for n, c in numbered_chunks}
    section_colors = assign_section_colors(raw_chunks)

    outline_nodes = build_outline(Chunk.model_validate(c) for c in raw_chunks)

    # Pass 1: find each chunk's matching page(s) (which may differ from, or
    # outnumber, its declared page_start -- see find_matching_pages) up
    # front, since a card grouped under its declared page may need crops
    # sourced from a different page's (or several pages') rendered image.
    chunk_match = {n: find_matching_pages(doc, c) for n, c in numbered_chunks}

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
            matched_here = [
                (n, chunk_by_number[n])
                for n, matches in chunk_match.items()
                if any(mp == page_num for mp, _r in matches)
            ]
            regions_here = {
                n: next(r for mp, r in chunk_match[n] if mp == page_num) for n, _c in matched_here
            }

            boxed_image = compose_boxed_image(base_image, matched_here, regions_here, section_colors)
            image_b64 = image_to_base64_png(boxed_image)

            ASSETS_DIR.mkdir(exist_ok=True)
            boxed_image.convert("RGB").save(ASSETS_DIR / f"{ASSET_PREFIX}_{page_num}.png")

            cards = render_grouped_cards(declared_here, chunk_match, section_colors, get_base_image)
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

    section_legend = "".join(
        f'<span class="legend-item"><span class="dot" style="background:{color}"></span>{html.escape(name)}</span>'
        for name, color in section_colors.items()
    )
    type_legend = "".join(
        f'<span class="type-pill" style="background:{color}">{name}</span>'
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

  .type-pill {{ color: white; font-size: 0.72rem; font-weight: 600; padding: 2px 9px; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.02em; margin: 0 3px; display: inline-block; }}

  .page-row {{ display: grid; grid-template-columns: minmax(280px, 460px) 1fr; gap: 24px; margin-bottom: 40px; align-items: start; }}
  .page-image {{ position: sticky; top: 16px; }}
  .page-image img {{ width: 100%; border: 1px solid var(--border); border-radius: 6px; display: block; }}
  .page-label {{ text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 6px; }}
  .page-chunks {{ display: flex; flex-direction: column; gap: 20px; min-width: 0; }}

  .heading-group {{ border-left: 3px solid var(--group-color); padding-left: 12px; }}
  .heading-group-label {{
    font-size: 0.74rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em;
    color: var(--group-color); margin-bottom: 8px;
  }}
  .heading-group .chunk-card + .chunk-card {{ margin-top: 12px; }}

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
  <p class="subtitle">examples/docling_example.pdf &rarr; {len(raw_chunks)} chunks. Numbered boxes on the page match the numbered cards on the right; color shows which section (below) a chunk belongs to.</p>
  <p class="caveat">Boxes/crops are estimated by matching each chunk's text back onto the PDF's text layer (vich's chunk schema has no bounding boxes) &mdash; a docs-only convenience, not part of vich's output. A chunk is searched for near its declared page, not only on it, since the VLM's self-reported page numbers are sometimes off by one (flagged on the card when that happens), and boxed on <em>every</em> page it genuinely spans, not just one, since batching multiple pages into a call is meant to let a chunk continue across a page break; some chunks still won't get a confident enough match to draw. The outline below, though, <em>is</em> a real vich feature (see <code>vich.outline</code>).</p>
  <div class="legend">{section_legend}</div>
  <p class="caveat">content_type (shown as a badge on each card, not by color): {type_legend}</p>
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
