from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="behaviormatch",
        description="Convert MouseMaze behavior logs and sidecars into uniform HDF5 outputs.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help=(
            "CSV files and/or folders. A selected sidecar such as "
            "<base>_mega_sync.csv is used to find or infer the session."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write outputs here instead of next to each session's primary log.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search folders recursively and group sidecars by shared session basename.",
    )
    parser.add_argument("--emit-csv", action="store_true", help="Also export trials/events/sensor CSVs and a summary JSON.")
    mat_group = parser.add_mutually_exclusive_group()
    mat_group.add_argument(
        "--emit-mat",
        dest="emit_mat",
        action="store_true",
        default=True,
        help="Export a MATLAB .mat file. This is the default.",
    )
    mat_group.add_argument(
        "--no-emit-mat",
        dest="emit_mat",
        action="store_false",
        help="Only write the canonical HDF5 output; skip MATLAB .mat export.",
    )
    parser.add_argument(
        "--on-existing",
        choices=["skip", "overwrite", "versioned"],
        default="skip",
        help="Policy when an output already exists.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print discovered sessions without writing outputs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["parse"]:
        argv = argv[1:]
    args = build_parser().parse_args(argv)
    results = run(
        input_path=args.paths,
        output_dir=args.output_dir,
        emit_mat=args.emit_mat,
        emit_csv=args.emit_csv,
        on_existing=args.on_existing,
        recursive=args.recursive,
        dry_run=args.dry_run,
        log=print,
    )
    failed = [result for result in results if result.status == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
