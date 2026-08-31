"""Stage 1 of a two-stage chunking pipeline: establish the document's
canonical heading structure once, up front, in its own VLM call.

Why this exists: asking a single VLM call to *simultaneously* invent
heading hierarchy, transcribe body text verbatim, classify content_type,
and extract keywords -- for a growing batch of pages -- is a lot to ask
in one shot, and re-deriving the hierarchy fresh in every batch means
the same section can come back worded slightly differently between
batches (observed in practice: "Parser Backends" nested one way in one
run, flattened differently in another). Splitting "what is this
document's structure" out into its own lightweight, whole-document pass
means stage 2 (`vich.chunking.client.call_vlm_chunker`, per batch) only
has to *classify* each chunk against an already-settled list of headings
instead of inventing one -- a much easier, more consistent task -- and a
chunk whose section spans a page or batch break groups correctly via
`vich.outline.build_outline` without needing to be merged into one
physical chunk_text by the model.

Scaling note: this sends every page's image (though none of the body
text) in one call, so it doesn't (yet) shard for very long documents the
way stage 2's batching does -- fine for the papers/reports this has been
tested on, worth revisiting for documents of a few hundred+ pages.
"""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from vich.parsing.pdf_renderer import PageImage

from .client import extract_json_object

OUTLINE_PROMPT_TEMPLATE = """You are extracting a document's heading structure, not its content.

Read the provided PDF page images. Produce ONLY the document's 3-level heading hierarchy -- do not extract body text, tables, or chunks.

Input context:
- document_id: {{document_id}}
- source: {{source}}

Extracted text (from the PDF's own text layer, page-labeled; ground the exact wording of headings in this, but use the page images to judge which lines actually are headings -- larger/bold text, numbered sections, or a section's visual prominence):
---
{{extracted_text}}
---

Rules:
1. level_1 is the document's own title (usually one, at the very top of the first page).
2. Each level_2 is a major section; each level_3 is a subsection within one level_2.
3. Copy heading text EXACTLY as it appears in the source (including any section numbers like "3.2") -- do not paraphrase or reword it.
4. Infer conservatively from visual layout when a heading isn't marked with an explicit number, but do not invent structure that isn't really there -- when in doubt, treat something as body text rather than a heading.
5. Include unnumbered front-matter sections as their own level_2 entries, not folded into whatever comes after them -- an "Abstract", "Executive Summary", "Preface", or "Foreword" is a real heading even without a section number, and it is a *different* section from "1 Introduction" (or whatever the first numbered section is), not part of it.
6. Do not include page numbers, running headers/footers, figure/table captions, or a references/bibliography entry list as headings (a "References" section heading itself is fine).
7. Note the page each heading first appears on.

Return only valid JSON, matching this schema:

{
  "level_1": string,
  "sections": [
    {
      "level_2": string,
      "first_page": number,
      "subsections": [
        {"level_3": string, "first_page": number}
      ]
    }
  ]
}
"""


def build_outline_prompt(
    document_id: str, source: str, extracted_text: str, template: str = OUTLINE_PROMPT_TEMPLATE
) -> str:
    replacements = {
        "{{document_id}}": document_id,
        "{{source}}": source,
        "{{extracted_text}}": extracted_text or "(no text layer for this document)",
    }
    prompt = template
    for key, value in replacements.items():
        prompt = prompt.replace(key, value)
    return prompt


def extract_document_outline(
    client: OpenAI,
    model: str,
    document_id: str,
    source: str,
    page_images: list[PageImage],
    extracted_text: str,
    prompt_template: str = OUTLINE_PROMPT_TEMPLATE,
    max_output_tokens: int = 2000,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """One whole-document call: returns the raw outline JSON (matching the
    schema in `OUTLINE_PROMPT_TEMPLATE`), not yet rendered to text."""
    prompt = build_outline_prompt(document_id, source, extracted_text, prompt_template)

    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for item in page_images:
        content.append({"type": "input_image", "image_url": item["image_url"]})

    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": content}],
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    return extract_json_object(response.output_text)


def render_known_outline_text(outline: dict[str, Any]) -> str:
    """The raw outline JSON, rendered as a compact indented list to hand to
    stage 2 as "here are the headings to classify against" context."""
    level_1 = outline.get("level_1") or ""
    lines = [f"- {level_1}"] if level_1 else []

    for section in outline.get("sections") or []:
        level_2 = section.get("level_2")
        if not level_2:
            continue
        lines.append(f"  - {level_2}")
        for sub in section.get("subsections") or []:
            level_3 = sub.get("level_3")
            if level_3:
                lines.append(f"    - {level_3}")

    return "\n".join(lines)
