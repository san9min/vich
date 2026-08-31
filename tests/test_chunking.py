import pytest

from vich.chunking.client import extract_json_object
from vich.chunking.normalize import default_id_resolver, make_embedding_text, normalize_chunk
from vich.chunking.prompt import build_prompt


def test_extract_json_object_parses_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_object_strips_code_fence():
    text = '```json\n{"a": 1, "b": [1, 2]}\n```'
    assert extract_json_object(text) == {"a": 1, "b": [1, 2]}


def test_extract_json_object_recovers_object_from_prose():
    text = 'Sure, here is the JSON:\n{"a": 1}\nLet me know if you need more.'
    assert extract_json_object(text) == {"a": 1}


def test_extract_json_object_raises_when_no_object_present():
    with pytest.raises(ValueError):
        extract_json_object("no json here")


def test_default_id_resolver_falls_back_to_ascii_slug():
    assert default_id_resolver("어떤 문서", "어떤 문서_v2") == "v2"
    assert default_id_resolver("Term Deposit", "Term_Deposit_Guide") == "term_deposit_guide"


def test_make_embedding_text_includes_headings_and_body():
    chunk = {
        "level_1_heading": "Term Deposit",
        "level_2_heading": "Eligibility",
        "level_3_heading": "Age limit",
        "chunk_text": "Applicants must be 19 or older.",
        "keywords": ["eligibility", "age"],
        "entities": [],
    }
    text = make_embedding_text(chunk, source="term_deposit_guide")
    assert "Term Deposit" in text
    assert "Eligibility" in text
    assert "Applicants must be 19 or older." in text
    assert "eligibility, age" in text


def test_normalize_chunk_builds_valid_chunk_and_metadata():
    raw_chunk = {
        "chunk_text": "Early withdrawal forfeits bonus interest.",
        "level_1_heading": "Term Deposit",
        "level_2_heading": "Interest",
        "content_type": "boxed_section",
        "continuation_status": "new",
        "keywords": ["early withdrawal"],
    }

    chunk = normalize_chunk(
        raw_chunk=raw_chunk,
        document_id="term_deposit_guide",
        source="Term Deposit Guide",
        source_url="https://example.com/guide.pdf",
        page_start=3,
        page_end=3,
        idx=2,
    )

    assert chunk.chunk_id == "term_deposit_guide_2"
    assert chunk.page_start == 3
    assert chunk.content_type == "boxed_section"
    assert chunk.metadata.document_id == chunk.document_id
    assert chunk.metadata.source_url == "https://example.com/guide.pdf"
    assert "Early withdrawal forfeits bonus interest." in chunk.embedding_text


def test_build_prompt_fills_placeholders_and_leaves_schema_braces_intact():
    prompt = build_prompt(
        document_id="doc_1",
        source="Doc One",
        page_start=1,
        page_end=4,
        previous_batch_summary="Intro section covered.",
        previous_last_chunk="",
    )

    assert "doc_1" in prompt
    assert "Doc One" in prompt
    assert "1-4" in prompt
    assert "Intro section covered." in prompt
    # The JSON schema block's literal braces must survive templating.
    assert '"chunks": [' in prompt


def test_build_prompt_includes_extracted_page_text_when_given():
    prompt = build_prompt(
        document_id="doc_1",
        source="Doc One",
        page_start=1,
        page_end=1,
        previous_batch_summary="",
        previous_last_chunk="",
        extracted_page_text="--- page 1 ---\nApplicants must be 19 or older.",
    )

    assert "Applicants must be 19 or older." in prompt


def test_build_prompt_notes_missing_text_layer_when_not_given():
    prompt = build_prompt(
        document_id="doc_1",
        source="Doc One",
        page_start=1,
        page_end=1,
        previous_batch_summary="",
        previous_last_chunk="",
    )

    assert "no text layer" in prompt


def test_build_prompt_includes_known_outline_when_given():
    prompt = build_prompt(
        document_id="doc_1",
        source="Doc One",
        page_start=1,
        page_end=1,
        previous_batch_summary="",
        previous_last_chunk="",
        known_outline="- Doc One\n  - Introduction\n  - Results",
    )

    assert "- Introduction" in prompt
    assert "- Results" in prompt


def test_build_prompt_notes_missing_outline_when_not_given():
    prompt = build_prompt(
        document_id="doc_1",
        source="Doc One",
        page_start=1,
        page_end=1,
        previous_batch_summary="",
        previous_last_chunk="",
    )

    assert "none established" in prompt
