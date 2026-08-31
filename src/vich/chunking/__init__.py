"""VLM-driven chunk extraction: prompt building, VLM calls, normalization."""

from .client import call_vlm_chunker, extract_json_object
from .coverage import LOW_COVERAGE_WARNING_THRESHOLD, coverage_ratio
from .normalize import default_id_resolver, make_embedding_text, normalize_chunk
from .prompt import PROMPT_TEMPLATE, build_prompt

__all__ = [
    "LOW_COVERAGE_WARNING_THRESHOLD",
    "PROMPT_TEMPLATE",
    "build_prompt",
    "call_vlm_chunker",
    "coverage_ratio",
    "default_id_resolver",
    "extract_json_object",
    "make_embedding_text",
    "normalize_chunk",
]
