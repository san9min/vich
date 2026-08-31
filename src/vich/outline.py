"""Document-wide heading outline, built from a list of chunks.

`vich parse` gives every chunk a flat 3-level heading label
(level_1/2/3_heading) but never assembles them into a tree — this module
does that assembly as a separate, free (no VLM call) step over
already-produced chunks.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

from vich.schema import Chunk


class OutlineNode(BaseModel):
    """One heading in the document tree.

    `chunk_ids` holds the chunks whose heading path ends *exactly* here
    (e.g. a table and its surrounding paragraph filed under the same
    level_3 heading both land in that node's `chunk_ids`, not in separate
    leaves).
    """

    title: str
    level: int  # 1, 2, or 3
    children: list[OutlineNode] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)

    @property
    def chunk_count(self) -> int:
        """Chunks filed under this heading, including its descendants."""
        return len(self.chunk_ids) + sum(child.chunk_count for child in self.children)


def build_outline(chunks: Iterable[Chunk]) -> list[OutlineNode]:
    """Assemble chunks' level_1/2/3_heading paths into a tree.

    Chunks are visited in order and a node is created the first time its
    heading path is seen; later chunks sharing a path reuse the same node.
    Root order (and each node's child order) therefore follows first
    appearance in `chunks`, which for `vich parse` output is reading order.
    """
    # Plain nested dicts first (title -> {"children": {...}, "chunk_ids": [...]})
    # so we get insertion-order-preserving de-duplication for free, then
    # convert to OutlineNode at the end.
    tree: dict[str, dict] = {}

    for chunk in chunks:
        path = [h for h in (chunk.level_1_heading, chunk.level_2_heading, chunk.level_3_heading) if h]
        if not path:
            continue

        level = tree
        entry = None
        for title in path:
            entry = level.setdefault(title, {"children": {}, "chunk_ids": []})
            level = entry["children"]
        entry["chunk_ids"].append(chunk.chunk_id)

    def convert(level: int, node_dict: dict[str, dict]) -> list[OutlineNode]:
        return [
            OutlineNode(
                title=title,
                level=level,
                children=convert(level + 1, entry["children"]),
                chunk_ids=entry["chunk_ids"],
            )
            for title, entry in node_dict.items()
        ]

    return convert(1, tree)


def render_outline_markdown(nodes: list[OutlineNode], depth: int = 0) -> str:
    """Render an outline tree as an indented markdown bullet list."""
    lines: list[str] = []
    for node in nodes:
        n = len(node.chunk_ids)
        suffix = f" ({n} chunk{'s' if n != 1 else ''})" if n else ""
        lines.append("  " * depth + f"- {node.title}{suffix}")
        if node.children:
            lines.append(render_outline_markdown(node.children, depth + 1))
    return "\n".join(lines)
