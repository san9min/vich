"""VLM chunking prompt.

Generalized from mafio/data/utils/visual_chunking.py's PROMPT_TEMPLATE:
domain-specific wording (Korean banking documents) has been replaced with
document-agnostic instructions. The chunking *approach* — layout-aware
units, 3-level heading hierarchy, careful table/footnote handling,
continuity across batches — is unchanged.
"""

from __future__ import annotations

import json
from typing import Any

PROMPT_TEMPLATE = """You are a document chunking engine for a RAG system.

Your task is to read the provided PDF page images and convert them into high-quality retrieval chunks.

The document may contain tables, boxed notes, multi-column layouts, footnotes, captions, and page-level visual structure. It may be in any language.

Return only valid JSON. Do not add explanations outside JSON.

Input context:
- document_id: {{document_id}}
- source: {{source}}
- page_range: {{page_start}}-{{page_end}}
- previous_batch_summary: {{previous_batch_summary}}
- previous_last_chunk: {{previous_last_chunk}}
- previous_heading_hierarchy: {{previous_heading_hierarchy}}

Chunking rules:

1. Preserve meaning and structure.
- Do not summarize aggressively.
- Do not omit important conditions, exceptions, footnotes, warnings, tables, or clauses.
- Preserve the source document's original language; do not translate unless the document itself already contains translated text.

2. Use a 3-level heading hierarchy for every chunk.
- level_1_heading: document or top-level title
- level_2_heading: major section
- level_3_heading: specific topic or subtopic
- If headings are visually implied but not explicit, infer them conservatively from the page layout.

3. Handle tables carefully.
- Do not flatten tables into unreadable text.
- For each logical table, preserve column headers.
- If a table has multiple rows with materially different content, create one chunk per logical row or row group.
- Each table chunk must repeat the table title and column headers so it can stand alone.
- If a table continues from a previous page or batch, use previous context to preserve continuity.

4. Handle boxed sections and footnotes.
- Treat boxed sections as meaningful layout units.
- Preserve caution notes, exceptions, limits, conditions, and warnings.
- Link footnotes to the relevant content when possible.

5. Handle multi-page continuity.
- If content continues from the previous batch, mark continuation_status as "continues".
- If this chunk starts new content, mark continuation_status as "new".
- If uncertain, mark continuation_status as "partial".

6. Avoid useless chunks.
- Exclude page numbers, repeated headers, repeated footers, watermarks, and table of contents unless they contain substantive information.
- Do not create chunks from empty or decorative content.
- Avoid chunks shorter than 2 meaningful lines unless the content is a critical condition, rate, fee, or warning.

7. Make chunks retrieval-friendly.
Each chunk should be understandable by itself.
Include enough context in the chunk_text so that a RAG system can answer questions without needing the entire page.

Output JSON schema:

{
  "document_id": string,
  "source": string,
  "page_range": string,
  "batch_summary": string,
  "heading_hierarchy": {
    "level_1": string,
    "level_2_candidates": [string],
    "level_3_candidates": [string]
  },
  "chunks": [
    {
      "chunk_id": string,
      "page_start": number,
      "page_end": number,
      "level_1_heading": string,
      "level_2_heading": string,
      "level_3_heading": string,
      "content_type": "paragraph" | "table" | "boxed_section" | "list" | "footnote" | "figure" | "mixed",
      "continuation_status": "new" | "continues" | "partial",
      "chunk_text": string,
      "table_markdown": string | null,
      "keywords": [string],
      "entities": [string],
      "source_notes": string
    }
  ]
}
"""


def build_prompt(
    document_id: str,
    source: str,
    page_start: int,
    page_end: int,
    previous_batch_summary: str,
    previous_last_chunk: str,
    previous_heading_hierarchy: dict[str, Any],
    template: str = PROMPT_TEMPLATE,
) -> str:
    """Fill `template` with per-batch context.

    A custom `template` may be supplied to add domain-specific instructions
    (e.g. "this is a financial disclosure document...") while keeping the
    `{{...}}` placeholders this function fills in.
    """
    replacements = {
        "{{document_id}}": document_id,
        "{{source}}": source,
        "{{page_start}}": str(page_start),
        "{{page_end}}": str(page_end),
        "{{previous_batch_summary}}": previous_batch_summary or "",
        "{{previous_last_chunk}}": previous_last_chunk or "",
        "{{previous_heading_hierarchy}}": json.dumps(
            previous_heading_hierarchy or {},
            ensure_ascii=False,
        ),
    }

    prompt = template
    for key, value in replacements.items():
        prompt = prompt.replace(key, value)

    return prompt
