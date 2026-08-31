"""VLM-driven chunk extraction: prompt building, VLM calls, normalization."""

from .client import call_vlm_chunker, extract_json_object
from .normalize import default_id_resolver, make_embedding_text, normalize_chunk
from .prompt import PROMPT_TEMPLATE, build_prompt

__all__ = [
    "PROMPT_TEMPLATE",
    "build_prompt",
    "call_vlm_chunker",
    "default_id_resolver",
    "extract_json_object",
    "make_embedding_text",
    "normalize_chunk",
]
