"""`vich` command-line entrypoint.

TODO(migration): expose a `vich parse <pdf-or-dir>` command wrapping
vich.chunking's batch-processing loop (currently
mafio/data/preprocess.py:process_raw_pdfs), writing JSONL output.
"""


def main() -> None:
    raise SystemExit("vich CLI is not implemented yet.")


if __name__ == "__main__":
    main()
