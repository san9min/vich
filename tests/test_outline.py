from vich.outline import build_outline, render_outline_markdown
from vich.schema import Chunk, ChunkMetadata


def make_chunk(chunk_id, l1, l2=None, l3=None) -> Chunk:
    fields = {
        "document_id": "doc",
        "source": "doc",
        "page_start": 1,
        "page_end": 1,
        "level_1_heading": l1,
        "level_2_heading": l2,
        "level_3_heading": l3,
    }
    return Chunk(chunk_id=chunk_id, metadata=ChunkMetadata(**fields), **fields)


def test_build_outline_groups_chunks_under_shared_headings():
    chunks = [
        make_chunk("c0", "Doc", "Intro", "Overview"),
        make_chunk("c1", "Doc", "Design", "Parser"),
        make_chunk("c2", "Doc", "Design", "Pipelines"),
        make_chunk("c3", "Doc", "Design", "Parser"),  # same path as c1 -> same leaf
    ]

    roots = build_outline(chunks)

    assert len(roots) == 1
    root = roots[0]
    assert root.title == "Doc" and root.level == 1
    assert root.chunk_count == 4

    design = next(n for n in root.children if n.title == "Design")
    assert {n.title for n in design.children} == {"Parser", "Pipelines"}

    parser = next(n for n in design.children if n.title == "Parser")
    assert parser.chunk_ids == ["c1", "c3"]


def test_build_outline_handles_missing_lower_levels():
    chunks = [make_chunk("c0", "Doc"), make_chunk("c1", "Doc", "Intro")]

    roots = build_outline(chunks)

    assert len(roots) == 1
    root = roots[0]
    assert root.chunk_ids == ["c0"]
    assert len(root.children) == 1
    assert root.children[0].chunk_ids == ["c1"]


def test_build_outline_skips_chunks_with_no_heading():
    chunks = [make_chunk("c0", None)]

    assert build_outline(chunks) == []


def test_render_outline_markdown_indents_by_level_and_counts_chunks():
    chunks = [
        make_chunk("c0", "Doc", "Intro", "Overview"),
        make_chunk("c1", "Doc", "Intro", "Scope"),
    ]

    text = render_outline_markdown(build_outline(chunks))

    assert text == (
        "- Doc\n"
        "  - Intro\n"
        "    - Overview (1 chunk)\n"
        "    - Scope (1 chunk)"
    )
