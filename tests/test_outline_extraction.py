from vich.chunking.outline_extraction import build_outline_prompt, render_known_outline_text


def test_render_known_outline_text_renders_nested_structure():
    outline = {
        "level_1": "Doc Title",
        "sections": [
            {"level_2": "Introduction", "first_page": 1, "subsections": []},
            {
                "level_2": "Design",
                "first_page": 2,
                "subsections": [
                    {"level_3": "Data Model", "first_page": 2},
                    {"level_3": "Parser", "first_page": 3},
                ],
            },
        ],
    }

    text = render_known_outline_text(outline)

    assert text == (
        "- Doc Title\n"
        "  - Introduction\n"
        "  - Design\n"
        "    - Data Model\n"
        "    - Parser"
    )


def test_render_known_outline_text_skips_sections_missing_a_title():
    outline = {
        "level_1": "Doc Title",
        "sections": [
            {"level_2": "", "first_page": 1, "subsections": []},
            {"level_2": "Real Section", "first_page": 1, "subsections": [{"level_3": "", "first_page": 1}]},
        ],
    }

    text = render_known_outline_text(outline)

    assert text == "- Doc Title\n  - Real Section"


def test_render_known_outline_text_handles_empty_outline():
    assert render_known_outline_text({}) == ""


def test_build_outline_prompt_fills_placeholders():
    prompt = build_outline_prompt(
        document_id="doc_1", source="Doc One", extracted_text="--- page 1 ---\nIntroduction text."
    )

    assert "doc_1" in prompt
    assert "Doc One" in prompt
    assert "Introduction text." in prompt


def test_build_outline_prompt_notes_missing_text():
    prompt = build_outline_prompt(document_id="doc_1", source="Doc One", extracted_text="")

    assert "no text layer" in prompt
