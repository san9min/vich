"""VLM call + JSON extraction.

Ported from mafio/data/utils/visual_chunking.py (call_vlm_chunker,
extract_json_object). Talks to any OpenAI-compatible Responses API;
swap in a different `openai.OpenAI`-compatible client (e.g. pointed at a
local/self-hosted VLM endpoint via `base_url`) to change providers.
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from vich.parsing.pdf_renderer import PageImage

from .prompt import PROMPT_TEMPLATE, build_prompt


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object out of a model response.

    Tolerates a ```json fence or stray prose around the object, which
    some models add despite being asked for JSON-only output.
    """
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in output:\n{text[:1000]}")

    return json.loads(match.group(0))


def call_vlm_chunker(
    client: OpenAI,
    model: str,
    document_id: str,
    source: str,
    page_start: int,
    page_end: int,
    page_images: list[PageImage],
    previous_batch_summary: str,
    previous_last_chunk: str,
    previous_heading_hierarchy: dict[str, Any],
    prompt_template: str = PROMPT_TEMPLATE,
    max_output_tokens: int = 8000,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """Send one page batch to the VLM and return the parsed batch result dict.

    Returns the raw parsed JSON (matching the schema in `prompt.py`);
    callers normalize individual chunks via `chunking.normalize`.
    """
    prompt = build_prompt(
        document_id=document_id,
        source=source,
        page_start=page_start,
        page_end=page_end,
        previous_batch_summary=previous_batch_summary,
        previous_last_chunk=previous_last_chunk,
        previous_heading_hierarchy=previous_heading_hierarchy,
        template=prompt_template,
    )

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
