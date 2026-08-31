from pathlib import Path

import fitz

from vich.parsing.pdf_renderer import extract_page_blocks, extract_page_text, safe_stem, slugify


def _make_pdf(tmp_path: Path, pages: list[str]) -> Path:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    path = tmp_path / "doc.pdf"
    doc.save(path)
    doc.close()
    return path


def _make_pdf_with_blocks(tmp_path: Path, page_blocks: list[list[str]]) -> Path:
    """Each inner list is one page's separate text blocks, placed far
    enough apart vertically that PyMuPDF segments them individually."""
    doc = fitz.open()
    for blocks in page_blocks:
        page = doc.new_page()
        for i, text in enumerate(blocks):
            page.insert_text((72, 72 + i * 200), text)
    path = tmp_path / "doc.pdf"
    doc.save(path)
    doc.close()
    return path


def test_slugify_collapses_punctuation_and_spaces():
    assert slugify("Hana Bank: Term Deposit (v2).pdf") == "Hana_Bank_Term_Deposit_v2_.pdf"


def test_slugify_preserves_hangul():
    assert slugify("하나은행 정기예금") == "하나은행_정기예금"


def test_safe_stem_uses_filename_without_extension():
    assert safe_stem(Path("/tmp/raw/Product Guide v2.pdf")) == "Product_Guide_v2"


def test_extract_page_text_labels_each_page_and_preserves_order(tmp_path):
    pdf_path = _make_pdf(tmp_path, ["First page body.", "Second page body."])

    text = extract_page_text(pdf_path, page_start=1, page_end=2)

    assert "--- page 1 ---" in text
    assert "--- page 2 ---" in text
    assert text.index("First page body.") < text.index("--- page 2 ---")
    assert "Second page body." in text


def test_extract_page_text_respects_page_range(tmp_path):
    pdf_path = _make_pdf(tmp_path, ["Page one.", "Page two.", "Page three."])

    text = extract_page_text(pdf_path, page_start=2, page_end=2)

    assert "Page two." in text
    assert "Page one." not in text
    assert "Page three." not in text


def test_extract_page_text_empty_for_blank_pages(tmp_path):
    pdf_path = _make_pdf(tmp_path, [""])

    assert extract_page_text(pdf_path, page_start=1, page_end=1) == ""


def test_extract_page_blocks_splits_separate_blocks_in_reading_order(tmp_path):
    pdf_path = _make_pdf_with_blocks(tmp_path, [["First block.", "Second block."]])

    blocks = extract_page_blocks(pdf_path, page_start=1, page_end=1)

    texts = [b["text"] for b in blocks]
    assert texts.index("First block.") < texts.index("Second block.")
    assert all(b["page_num"] == 1 for b in blocks)


def test_extract_page_blocks_respects_page_range(tmp_path):
    pdf_path = _make_pdf_with_blocks(tmp_path, [["Page one."], ["Page two."], ["Page three."]])

    blocks = extract_page_blocks(pdf_path, page_start=2, page_end=2)

    assert [b["text"] for b in blocks] == ["Page two."]
    assert blocks[0]["page_num"] == 2


def test_extract_page_blocks_empty_for_blank_pages(tmp_path):
    pdf_path = _make_pdf(tmp_path, [""])

    assert extract_page_blocks(pdf_path, page_start=1, page_end=1) == []
