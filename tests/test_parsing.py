from pathlib import Path

from vich.parsing.pdf_renderer import safe_stem, slugify


def test_slugify_collapses_punctuation_and_spaces():
    assert slugify("Hana Bank: Term Deposit (v2).pdf") == "Hana_Bank_Term_Deposit_v2_.pdf"


def test_slugify_preserves_hangul():
    assert slugify("하나은행 정기예금") == "하나은행_정기예금"


def test_safe_stem_uses_filename_without_extension():
    assert safe_stem(Path("/tmp/raw/Product Guide v2.pdf")) == "Product_Guide_v2"
