#!/usr/bin/env python3
"""ALEX bridge for the canonical ConPhon biological ear extractor."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ALEX_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BACKEND_ROOT = ALEX_ROOT
if not (DEFAULT_BACKEND_ROOT / "src" / "conphon").exists():
    sibling_conphon = ALEX_ROOT.parent / "conphon"
    if (sibling_conphon / "src" / "conphon").exists():
        DEFAULT_BACKEND_ROOT = sibling_conphon
BACKEND_ROOT = Path(os.environ.get("CONPHON_BACKEND_ROOT", DEFAULT_BACKEND_ROOT))
if not (BACKEND_ROOT / "src" / "conphon").exists():
    raise RuntimeError(f"Canonical ConPhon backend not found at {BACKEND_ROOT}")
DEFAULT_EXTRACT_JOBS = max(1, int(os.environ.get("CONPHON_EXTRACT_JOBS", "32")))
DEFAULT_PROFILE = "balanced"

for candidate in (BACKEND_ROOT, BACKEND_ROOT / "src"):
    text = str(candidate)
    while text in sys.path:
        sys.path.remove(text)
    sys.path.insert(0, text)

from conphon.bioear.extractor import (  # noqa: E402
    build_canonical_corpus,
    doctor_payload,
    extract_biological_ear,
    run_folder,
    scan_payload,
    validate_bioear_h5,
)


def emit(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        ok = "OK" if payload.get("ok") else "FAILED"
        print(f"{ok}: {payload.get('schema', 'bioear')}")


def add_selection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=int, default=None, help="First numbered folder to include.")
    parser.add_argument("--end", type=int, default=None, help="Last numbered folder to include.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of selected pairs/folders.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Bruce-Zilany-Carney biological ear HDF5 files.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Validate that the required brucezilany backend is importable.")
    doctor.add_argument("--json", action="store_true")

    scan = sub.add_parser("scan", help="Scan for WAV/TextGrid pairs and validated _bioear.h5 outputs.")
    scan.add_argument("--input", required=True, type=Path)
    scan.add_argument("--json", action="store_true")
    add_selection_args(scan)

    run = sub.add_parser("run", help="Write <stem>_bioear.h5 beside each WAV/TextGrid pair.")
    run.add_argument("--input", required=True, type=Path)
    run.add_argument("--replace-confirmed", action="store_true")
    run.add_argument("--profile", choices=("fast", "balanced", "context-lite"), default=DEFAULT_PROFILE)
    run.add_argument("--jobs", type=int, default=DEFAULT_EXTRACT_JOBS, help=f"Parallel worker processes. Default: {DEFAULT_EXTRACT_JOBS}.")
    run.add_argument("--language-tag", default="cust", help="Four-character user language tag stored in generated H5 metadata.")
    run.add_argument("--json", action="store_true")
    run.add_argument("--quiet", action="store_true")
    add_selection_args(run)

    pair = sub.add_parser("pair", help="Write one _bioear.h5 from one WAV and one TextGrid.")
    pair.add_argument("--wav", required=True, type=Path)
    pair.add_argument("--textgrid", required=True, type=Path)
    pair.add_argument("--out", type=Path, default=None)
    pair.add_argument("--replace-confirmed", action="store_true")
    pair.add_argument("--profile", choices=("fast", "balanced", "context-lite"), default=DEFAULT_PROFILE)
    pair.add_argument("--language-tag", default="cust", help="Four-character user language tag stored in generated H5 metadata.")
    pair.add_argument("--json", action="store_true")
    pair.add_argument("--quiet", action="store_true")

    build = sub.add_parser("build-data", help="Build canonical data/corpus/bioear HDF5 corpus.")
    build.add_argument("--input", required=True, type=Path)
    build.add_argument("--output", type=Path, default=BACKEND_ROOT / "data" / "corpus")
    build.add_argument("--replace-confirmed", action="store_true")
    build.add_argument("--profile", choices=("fast", "balanced", "context-lite"), default=DEFAULT_PROFILE)
    build.add_argument("--json", action="store_true")
    build.add_argument("--quiet", action="store_true")
    add_selection_args(build)

    validate = sub.add_parser("validate", help="Validate one _bioear.h5 file.")
    validate.add_argument("path", type=Path)
    validate.add_argument("--json", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "doctor":
            payload = doctor_payload()
            emit(payload, json_output=args.json)
            return 0 if payload.get("ok") else 1
        if args.command == "scan":
            payload = scan_payload(args.input.resolve(), start=args.start, end=args.end, limit=args.limit)
            emit(payload, json_output=args.json)
            return 0
        if args.command == "run":
            payload = run_folder(
                args.input.resolve(),
                replace=args.replace_confirmed,
                limit=args.limit,
                start=args.start,
                end=args.end,
                progress=not args.quiet,
                profile=args.profile,
                jobs=args.jobs,
                language_tag=args.language_tag,
            )
            emit(payload, json_output=args.json)
            return 0 if payload.get("ok") else 1
        if args.command == "pair":
            payload = extract_biological_ear(
                args.wav.resolve(),
                args.textgrid.resolve(),
                args.out.resolve() if args.out is not None else None,
                replace=args.replace_confirmed,
                progress=not args.quiet,
                profile=args.profile,
                language_tag=args.language_tag,
            )
            emit(payload, json_output=args.json)
            return 0 if payload.get("ok") else 1
        if args.command == "build-data":
            payload = build_canonical_corpus(
                args.input.resolve(),
                output_root=args.output.resolve(),
                replace=args.replace_confirmed,
                limit=args.limit,
                start=args.start,
                end=args.end,
                progress=not args.quiet,
                command_provenance=sys.argv,
                profile=args.profile,
            )
            emit(payload, json_output=args.json)
            return 0 if payload.get("ok") else 1
        if args.command == "validate":
            payload = validate_bioear_h5(args.path)
            emit(payload, json_output=args.json)
            return 0 if payload.get("ok") else 1
    except Exception as exc:  # noqa: BLE001 - app bridge reports machine-readable failures.
        payload = {"ok": False, "command": args.command, "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
