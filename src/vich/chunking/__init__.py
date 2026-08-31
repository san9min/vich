"""VLM-driven chunk extraction: prompt building, VLM calls, normalization."""

from .client import call_vlm_chunker, extract_json_object
from .coverage import coverage_ratio, significant_word_count
from .normalize import default_id_resolver, make_embedding_text, normalize_chunk
from .outline_extraction import (
    OUTLINE_PROMPT_TEMPLATE,
    build_outline_prompt,
    extract_document_outline,
    render_known_outline_text,
)
from .prompt import PROMPT_TEMPLATE, build_prompt
from .recovery import MIN_RECOVERABLE_WORDS, RECOVERY_COVERAGE_THRESHOLD, find_missed_blocks

__all__ = [
    "MIN_RECOVERABLE_WORDS",
    "OUTLINE_PROMPT_TEMPLATE",
    "PROMPT_TEMPLATE",
    "RECOVERY_COVERAGE_THRESHOLD",
    "build_outline_prompt",
    "build_prompt",
    "call_vlm_chunker",
    "coverage_ratio",
    "default_id_resolver",
    "extract_document_outline",
    "extract_json_object",
    "find_missed_blocks",
    "make_embedding_text",
    "normalize_chunk",
    "render_known_outline_text",
    "significant_word_count",
]
