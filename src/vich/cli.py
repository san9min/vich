"""`vich` command-line entrypoint.

Wraps `vich.pipeline` (ported from mafio/data/preprocess.py's
process_raw_pdfs batch loop) into a `vich parse <pdf-or-dir>` command.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from vich.outline import build_outline, render_outline_markdown
from vich.pipeline import DEFAULT_OUTPUT_DIR, process_documents, process_pdf
from vich.schema import load_chunks


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vich", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser(
        "parse", help="Chunk a single PDF or every PDF in a directory into JSONL."
    )
    parse_cmd.add_argument("path", type=Path, help="A PDF file or a directory of PDFs.")
    parse_cmd.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write <document_id>.jsonl into (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parse_cmd.add_argument(
        "--model",
        default=None,
        help="VLM model id. Defaults to the VICH_VLM_MODEL env var.",
    )
    parse_cmd.add_argument(
        "--outline-model",
        default=None,
        help="Model for the one-off whole-document heading-structure pass that each "
        "chunking batch then classifies against (see the README's 'Two-stage design' "
        "note). Defaults to --model; pass a stronger model here if headings come out "
        "wrong -- getting this pass right matters more than any single chunking batch.",
    )
    parse_cmd.add_argument(
        "--batch-size",
        type=int,
        default=2,
        help="Pages sent to the VLM per call (default: 2; a bigger batch means a "
        "longer prompt, which raises the risk the model drops a paragraph outright).",
    )
    parse_cmd.add_argument(
        "--zoom",
        type=float,
        default=2.0,
        help="Page render zoom factor; higher improves legibility at more token cost (default: 2.0).",
    )
    parse_cmd.add_argument(
        "--overwrite",
        action="store_true",
        help="Reprocess and overwrite an existing output JSONL.",
    )

    outline_cmd = subparsers.add_parser(
        "outline", help="Print the heading tree assembled from a `vich parse` JSONL file."
    )
    outline_cmd.add_argument("jsonl_path", type=Path, help="A JSONL file produced by `vich parse`.")

    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "parse":
        if args.path.is_dir():
            process_documents(
                raw_dir=args.path,
                output_dir=args.output_dir,
                model=args.model,
                outline_model=args.outline_model,
                batch_size=args.batch_size,
                zoom=args.zoom,
                overwrite=args.overwrite,
            )
        elif args.path.is_file():
            process_pdf(
                client=OpenAI(),
                pdf_path=args.path,
                output_dir=args.output_dir,
                model=args.model,
                outline_model=args.outline_model,
                batch_size=args.batch_size,
                zoom=args.zoom,
                overwrite=args.overwrite,
            )
        else:
            raise SystemExit(f"Not a file or directory: {args.path}")

    elif args.command == "outline":
        chunks = load_chunks(args.jsonl_path)
        print(render_outline_markdown(build_outline(chunks)))


if __name__ == "__main__":
    main()
