#!/usr/bin/env python3
"""Batch CLI for a numbered ALEX corpus.

This is the non-GUI path for very large numbered corpora. Active
alignment/extraction may run in a staging download folder, but successful
full-root completion finalizes the corpus into the trainer-facing shape:

    data/corpus/
        1/<original>.wav
        1/<original>.txt
        2/<original>.wav
        2/<original>.txt
        ...

It deliberately separates the expensive phases:

1. create/normalize TextGrids in place
2. run per-folder biological auditory-periphery extraction
3. move the completed numbered corpus to ``data/corpus``
4. optionally build the consolidated ConPhon ``data/corpus/bioear`` corpus
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TOOLS_ROOT = Path(__file__).resolve().parent
ALEX_APP_ROOT = TOOLS_ROOT.parent
ALEX_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BACKEND_ROOT = ALEX_ROOT
if not (DEFAULT_BACKEND_ROOT / "src" / "conphon").exists():
    sibling_conphon = ALEX_ROOT.parent / "conphon"
    if (sibling_conphon / "src" / "conphon").exists():
        DEFAULT_BACKEND_ROOT = sibling_conphon
BACKEND_ROOT = Path(os.environ.get("CONPHON_BACKEND_ROOT", DEFAULT_BACKEND_ROOT)).expanduser().resolve()
DEFAULT_PYTHON = os.environ.get("CONPHON_PYTHON", sys.executable)
CANONICAL_DATA_ROOT = BACKEND_ROOT / "data"
CANONICAL_NUMBERED_ROOT = CANONICAL_DATA_ROOT / "corpus"
CANONICAL_METADATA_ROOT = CANONICAL_DATA_ROOT / "metadata" / "numbered_audio"
DEFAULT_STAGING_NUMBERED_ROOT = BACKEND_ROOT / "download" / "CORAA-NURC-SP-Audio-Corpus" / "filtered_audio"

ALIGNER = TOOLS_ROOT / "run_aligner.py"
BIOEAR_EXTRACTOR = TOOLS_ROOT / "extract_bioear.py"
STANDARDIZER = TOOLS_ROOT / "standardize_transcriptions.py"
STATE_DIRNAME = "numbered_audio_cli"
OFFICIAL_BIOEAR_BACKEND = "brucezilany"
VALID_BIOEAR_BACKENDS = {OFFICIAL_BIOEAR_BACKEND}
DEFAULT_EXTRACT_JOBS = max(1, int(os.environ.get("CONPHON_EXTRACT_JOBS", "32")))


@dataclass(frozen=True)
class NumberedFolder:
    number: int
    path: Path
    wav: Path | None
    txt: Path | None
    textgrid: Path | None
    issues: tuple[str, ...]

    @property
    def stem(self) -> str | None:
        return self.wav.stem if self.wav is not None else self.txt.stem if self.txt is not None else None

    @property
    def has_pair(self) -> bool:
        return self.wav is not None and self.txt is not None and self.wav.stem == self.txt.stem

    @property
    def has_triple(self) -> bool:
        return self.has_pair and self.textgrid is not None and self.textgrid.stem == self.wav.stem

    @property
    def bioear_output(self) -> Path | None:
        return self.wav.with_name(f"{self.wav.stem}_bioear.h5") if self.wav is not None else None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_dir(root: Path) -> Path:
    if root.name == "filtered_audio" and (root.parent / "filtered").exists():
        out = root.parent / "filtered" / "alex_numbered_cli"
    else:
        out = CANONICAL_METADATA_ROOT
    out.mkdir(parents=True, exist_ok=True)
    return out


def append_event(root: Path, event: dict[str, Any]) -> None:
    event = {"created_at_utc": utc_now(), **event}
    with (state_dir(root) / "progress.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def write_summary(root: Path, name: str, payload: dict[str, Any]) -> Path:
    path = state_dir(root) / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def numeric_folders(root: Path) -> list[Path]:
    return sorted(
        (item for item in root.iterdir() if item.is_dir() and item.name.isdigit()),
        key=lambda item: int(item.name),
    )


def has_numbered_folders(root: Path) -> bool:
    if not root.exists() or not root.is_dir():
        return False
    try:
        return any(item.is_dir() and item.name.isdigit() for item in root.iterdir())
    except OSError:
        return False


def default_input_root() -> Path:
    if has_numbered_folders(CANONICAL_NUMBERED_ROOT):
        return CANONICAL_NUMBERED_ROOT
    if has_numbered_folders(DEFAULT_STAGING_NUMBERED_ROOT):
        return DEFAULT_STAGING_NUMBERED_ROOT
    return CANONICAL_NUMBERED_ROOT


def inspect_numbered_folder(path: Path) -> NumberedFolder:
    wavs = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".wav")
    txts = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".txt")
    textgrids = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".textgrid")
    issues: list[str] = []
    wav = wavs[0] if len(wavs) == 1 else None
    txt = txts[0] if len(txts) == 1 else None
    textgrid = textgrids[0] if len(textgrids) == 1 else None
    if len(wavs) != 1:
        issues.append(f"expected_one_wav_found_{len(wavs)}")
    if len(txts) != 1:
        issues.append(f"expected_one_txt_found_{len(txts)}")
    if len(textgrids) > 1:
        issues.append(f"expected_at_most_one_textgrid_found_{len(textgrids)}")
    if wav is not None and txt is not None and wav.stem != txt.stem:
        issues.append("wav_txt_stem_mismatch")
    if wav is not None and textgrid is not None and wav.stem != textgrid.stem:
        issues.append("wav_textgrid_stem_mismatch")
    return NumberedFolder(
        number=int(path.name),
        path=path,
        wav=wav,
        txt=txt,
        textgrid=textgrid,
        issues=tuple(issues),
    )


def selected_folders(root: Path, *, start: int | None, end: int | None, limit: int | None) -> list[NumberedFolder]:
    folders = [inspect_numbered_folder(path) for path in numeric_folders(root)]
    if start is not None:
        folders = [item for item in folders if item.number >= start]
    if end is not None:
        folders = [item for item in folders if item.number <= end]
    if limit is not None:
        folders = folders[: max(0, int(limit))]
    return folders


def selection_requested(args: argparse.Namespace) -> bool:
    return (
        getattr(args, "start", None) is not None
        or getattr(args, "end", None) is not None
        or getattr(args, "limit", None) is not None
    )


def scan_payload(root: Path, folders: list[NumberedFolder]) -> dict[str, Any]:
    bioear_done_count = sum(is_valid_bioear_h5(item.bioear_output) for item in folders)
    return {
        "schema": "conphon.alex.numbered_cli.scan.v1",
        "ok": True,
        "root": str(root),
        **canonical_root_payload(root),
        "folder_count": len(folders),
        "pair_count": sum(item.has_pair for item in folders),
        "triple_count": sum(item.has_triple for item in folders),
        "textgrid_missing_count": sum(item.has_pair and item.textgrid is None for item in folders),
        "issue_count": sum(bool(item.issues) for item in folders),
        "bioear_done_count": bioear_done_count,
        "bioear_pending_count": len(folders) - bioear_done_count,
        "examples_with_issues": [
            {
                "number": item.number,
                "path": str(item.path),
                "wav": item.wav.name if item.wav else None,
                "txt": item.txt.name if item.txt else None,
                "textgrid": item.textgrid.name if item.textgrid else None,
                "issues": list(item.issues),
            }
            for item in folders
            if item.issues
        ][:25],
    }


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONPYCACHEPREFIX", "/tmp/conphon_alex_cli_pycache")
    env.setdefault("CONPHON_BACKEND_ROOT", str(BACKEND_ROOT))
    env.setdefault("ALEX_SKIP_TEXT_STANDARDIZER", "1")
    return env


def is_valid_bioear_h5(path: Path | None, *, profile: str | None = None) -> bool:
    if path is None or not path.exists():
        return False
    try:
        import h5py

        with h5py.File(path, "r") as h5:
            required = (
                "periphery/characteristic_frequency_hz",
                "periphery/spike_count_neurogram_1ms",
                "periphery/rate_neurogram_1ms_hz_per_fiber",
                "periphery/frame_model_time_s",
                "periphery/frame_original_time_s",
                "labels/frame_phone_id",
                "labels/frame_syllable_id",
                "labels/frame_word_id",
                "labels/frame_sentence_id",
                "labels/intervals/phone",
                "labels/intervals/syllable",
                "labels/intervals/word",
                "labels/intervals/sentence",
            )
            return (
                h5.attrs.get("schema") == "conphon.bioear.hdf5.v1"
                and h5.attrs.get("backend_module") in VALID_BIOEAR_BACKENDS
                and h5.attrs.get("extraction_profile") in {"fast", "balanced", "context-lite"}
                and (profile is None or h5.attrs.get("extraction_profile") == profile)
                and all(name in h5 for name in required)
            )
    except Exception:
        return False


def run_command(root: Path, command: list[str], *, dry_run: bool, phase: str, folder: NumberedFolder | None = None) -> int:
    event = {
        "phase": phase,
        "folder": None if folder is None else folder.number,
        "command": command,
        "dry_run": dry_run,
    }
    if dry_run:
        append_event(root, {**event, "status": "dry_run", "returncode": 0})
        print("DRY RUN:", " ".join(command))
        return 0
    start = time.monotonic()
    completed = subprocess.run(command, cwd=str(ALEX_ROOT), env=command_env(), check=False)
    duration_s = time.monotonic() - start
    append_event(
        root,
        {
            **event,
            "status": "ok" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "duration_s": duration_s,
        },
    )
    return completed.returncode


def run_textgrids(args: argparse.Namespace, root: Path, folders: list[NumberedFolder]) -> int:
    if not ALIGNER.exists():
        raise RuntimeError(f"aligner wrapper missing: {ALIGNER}")
    if getattr(args, "standardize_transcriptions", True):
        rc = run_standardize(args, root)
        if rc != 0:
            return rc
    command = [
        args.python,
        str(ALIGNER),
        "--engine",
        args.textgrid_engine,
        str(root),
        "--am-tag",
        args.am_tag,
        "--speech-recipe",
        args.speech_recipe,
        "--skip-existing",
        "--continue-on-error",
        "--show-unmatched",
        "--chunk-size",
        str(args.chunk_size),
        "--jobs",
        str(args.textgrid_jobs),
        "--retry-chunk-sizes",
        args.retry_chunk_sizes,
        "--max-initial-deferred-chunks",
        str(args.max_initial_deferred_chunks),
    ]
    if args.textgrids_per_folder or folders:
        failures = 0
        for folder in folders:
            if not folder.has_pair:
                append_event(root, {"phase": "textgrid", "folder": folder.number, "status": "blocked", "issues": list(folder.issues)})
                failures += 1
                continue
            cmd = [
                args.python,
                str(ALIGNER),
                "--engine",
                args.textgrid_engine,
                str(folder.path),
                "--am-tag",
                args.am_tag,
                "--speech-recipe",
                args.speech_recipe,
                "--skip-existing",
                "--continue-on-error",
                "--show-unmatched",
                "--chunk-size",
                "1",
                "--jobs",
                "1",
            ]
            failures += int(run_command(root, cmd, dry_run=args.dry_run, phase="textgrid", folder=folder) != 0)
        return 1 if failures else 0
    return run_command(root, command, dry_run=args.dry_run, phase="textgrid")


def run_standardize(args: argparse.Namespace, root: Path) -> int:
    if not STANDARDIZER.exists():
        raise RuntimeError(f"transcription standardizer missing: {STANDARDIZER}")
    command = [
        args.python,
        str(STANDARDIZER),
        "--input",
        str(root),
        "--json",
        "--remove-textgrid-on-change",
        "--quarantine-empty",
    ]
    for option in ("start", "end", "limit"):
        value = getattr(args, option, None)
        if value is not None:
            command.extend([f"--{option}", str(value)])
    return run_command(root, command, dry_run=args.dry_run, phase="standardize_transcriptions")


def should_skip_bioear(output: Path | None, replace_confirmed: bool, profile: str) -> bool:
    return bool(output is not None and is_valid_bioear_h5(output, profile=profile) and not replace_confirmed)


def extraction_commands(args: argparse.Namespace, folder: NumberedFolder) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = []
    if not should_skip_bioear(folder.bioear_output, args.replace_confirmed, args.extract_profile):
        cmd = [
            args.python,
            str(BIOEAR_EXTRACTOR),
            "run",
            "--input",
            str(folder.path),
            "--json",
            "--profile",
            args.extract_profile,
            "--jobs",
            "1",
        ]
        if args.replace_confirmed:
            cmd.append("--replace-confirmed")
        commands.append(("bioear_extract", cmd))
    return commands


def bulk_extraction_command(args: argparse.Namespace, root: Path) -> list[str]:
    command = [
        args.python,
        str(BIOEAR_EXTRACTOR),
        "run",
        "--input",
        str(root),
        "--json",
        "--profile",
        args.extract_profile,
        "--jobs",
        str(args.extract_jobs),
    ]
    for option in ("start", "end", "limit"):
        value = getattr(args, option, None)
        if value is not None:
            command.extend([f"--{option}", str(value)])
    if args.replace_confirmed:
        command.append("--replace-confirmed")
    return command


def run_extractions(args: argparse.Namespace, root: Path, folders: list[NumberedFolder]) -> int:
    selected = folders or selected_folders(root, start=args.start, end=args.end, limit=args.limit)
    blocked_folders = [inspect_numbered_folder(folder.path) for folder in selected if not inspect_numbered_folder(folder.path).has_triple]
    for folder in blocked_folders[:250]:
        append_event(
            root,
            {
                "phase": "extract",
                "folder": folder.number,
                "status": "blocked",
                "issues": list(folder.issues) or ["missing_textgrid"],
            },
        )
    if blocked_folders and not args.continue_on_error:
        summary = {
            "schema": "conphon.alex.numbered_cli.extract_summary.v1",
            "ok": False,
            "root": str(root),
            **canonical_root_payload(root),
            "selected_folder_count": len(selected),
            "done": 0,
            "skipped_existing": 0,
            "blocked": len(blocked_folders),
            "failures": 0,
            "extractor": "bioear",
            "extract_profile": args.extract_profile,
            "extract_jobs": args.extract_jobs,
            "blocked_examples": [folder.number for folder in blocked_folders[:25]],
        }
        write_summary(root, "last_extract_summary.json", summary)
        return 1

    before_done = sum(is_valid_bioear_h5(item.bioear_output) for item in selected)
    rc = run_command(root, bulk_extraction_command(args, root), dry_run=args.dry_run, phase="bioear_extract_bulk")
    refreshed = selected_folders(root, start=args.start, end=args.end, limit=args.limit)
    after_done = sum(is_valid_bioear_h5(item.bioear_output) for item in refreshed)
    failures = 1 if rc != 0 else 0
    blocked = len(blocked_folders)
    summary = {
        "schema": "conphon.alex.numbered_cli.extract_summary.v1",
        "ok": failures == 0 and blocked == 0 and after_done == len(refreshed),
        "root": str(root),
        **canonical_root_payload(root),
        "selected_folder_count": len(refreshed),
        "done": after_done,
        "created_or_confirmed": max(0, after_done - before_done),
        "skipped_existing": before_done,
        "blocked": blocked,
        "failures": failures,
        "extractor": "bioear",
        "extract_profile": args.extract_profile,
        "extract_jobs": args.extract_jobs,
        "blocked_examples": [folder.number for folder in blocked_folders[:25]],
    }
    path = write_summary(root, "last_extract_summary.json", summary)
    print(json.dumps({**summary, "summary_path": str(path)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def run_build_data(args: argparse.Namespace, root: Path) -> int:
    command = [
        args.python,
        str(BIOEAR_EXTRACTOR),
        "build-data",
        "--input",
        str(root),
        "--output",
        str(CANONICAL_NUMBERED_ROOT),
        "--json",
        "--profile",
        args.extract_profile,
    ]
    for option in ("start", "end", "limit"):
        value = getattr(args, option, None)
        if value is not None:
            command.extend([f"--{option}", str(value)])
    if args.replace_confirmed:
        command.append("--replace-confirmed")
    return run_command(root, command, dry_run=args.dry_run, phase="build_data")


def finalization_readiness(root: Path) -> dict[str, Any]:
    folders = selected_folders(root, start=None, end=None, limit=None)
    blocked_examples: list[dict[str, Any]] = []
    missing_pair_count = 0
    missing_textgrid_count = 0
    invalid_bioear_count = 0
    for folder in folders:
        reasons = list(folder.issues)
        if not folder.has_pair:
            missing_pair_count += 1
            reasons.append("missing_wav_txt_pair")
        if not folder.has_triple:
            missing_textgrid_count += 1
            reasons.append("missing_textgrid")
        if not is_valid_bioear_h5(folder.bioear_output):
            invalid_bioear_count += 1
            reasons.append("missing_or_invalid_bioear_h5")
        if reasons and len(blocked_examples) < 25:
            blocked_examples.append(
                {
                    "number": folder.number,
                    "path": str(folder.path),
                    "issues": reasons,
                }
            )
    ok = bool(folders) and missing_pair_count == 0 and missing_textgrid_count == 0 and invalid_bioear_count == 0
    return {
        "schema": "conphon.alex.numbered_cli.finalization_readiness.v1",
        "ok": ok,
        "root": str(root),
        "folder_count": len(folders),
        "missing_pair_count": missing_pair_count,
        "missing_textgrid_count": missing_textgrid_count,
        "invalid_bioear_count": invalid_bioear_count,
        "blocked_examples": blocked_examples,
    }


def same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve() == right.expanduser().resolve()


def move_existing_canonical_sidecars_into_source(source: Path) -> None:
    destination = CANONICAL_NUMBERED_ROOT
    if not destination.exists():
        return
    if has_numbered_folders(destination):
        raise RuntimeError(f"canonical corpus root already has numbered folders: {destination}")
    for item in sorted(destination.iterdir(), key=lambda path: path.name):
        target = source / item.name
        if target.exists():
            raise RuntimeError(f"cannot finalize corpus; destination sidecar would collide with source: {target}")
        shutil.move(str(item), str(target))
    destination.rmdir()


def finalize_completed_corpus(args: argparse.Namespace, root: Path) -> Path:
    if not getattr(args, "finalize_to_canonical", True):
        append_event(root, {"phase": "finalize_corpus", "status": "skipped", "reason": "disabled"})
        return root
    if same_path(root, CANONICAL_NUMBERED_ROOT):
        append_event(root, {"phase": "finalize_corpus", "status": "already_canonical", "target": str(CANONICAL_NUMBERED_ROOT)})
        return CANONICAL_NUMBERED_ROOT
    if selection_requested(args):
        append_event(root, {"phase": "finalize_corpus", "status": "skipped", "reason": "partial_selection"})
        return root

    readiness = finalization_readiness(root)
    if not readiness["ok"]:
        path = write_summary(root, "last_finalize_summary.json", {**readiness, "target": str(CANONICAL_NUMBERED_ROOT)})
        raise RuntimeError(f"completed corpus is not ready to move to data/corpus; see {path}")

    payload = {
        "phase": "finalize_corpus",
        "status": "dry_run" if getattr(args, "dry_run", False) else "started",
        "source": str(root),
        "target": str(CANONICAL_NUMBERED_ROOT),
        "readiness": readiness,
    }
    append_event(root, payload)
    if getattr(args, "dry_run", False):
        print("DRY RUN: move", root, CANONICAL_NUMBERED_ROOT)
        write_summary(root, "last_finalize_summary.json", {**payload, "ok": True})
        return root

    CANONICAL_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    move_existing_canonical_sidecars_into_source(root)
    shutil.move(str(root), str(CANONICAL_NUMBERED_ROOT))
    completed = {
        **payload,
        "status": "completed",
        "root": str(CANONICAL_NUMBERED_ROOT),
        "ok": True,
        **canonical_root_payload(CANONICAL_NUMBERED_ROOT),
    }
    path = write_summary(CANONICAL_NUMBERED_ROOT, "last_finalize_summary.json", completed)
    print(json.dumps({**completed, "summary_path": str(path)}, ensure_ascii=False, indent=2, sort_keys=True))
    return CANONICAL_NUMBERED_ROOT


def validate_root(root: Path) -> None:
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"input root does not exist or is not a directory: {root}")
    if not numeric_folders(root):
        raise RuntimeError(f"input root has no numeric folders: {root}")


def canonical_root_payload(root: Path) -> dict[str, Any]:
    try:
        relative = root.resolve().relative_to(BACKEND_ROOT)
        root_display = str(relative)
    except ValueError:
        root_display = str(root)
    return {
        "canonical_data_root": str(CANONICAL_DATA_ROOT),
        "canonical_numbered_root": str(CANONICAL_NUMBERED_ROOT),
        "canonical_bioear_root": str(CANONICAL_NUMBERED_ROOT / "bioear"),
        "canonical_metadata_root": str(CANONICAL_METADATA_ROOT),
        "input_root_relative_to_repo": root_display,
        "input_is_canonical_numbered_root": root.resolve() == CANONICAL_NUMBERED_ROOT.resolve(),
    }


def add_selection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=int, default=None, help="First numbered folder to include.")
    parser.add_argument("--end", type=int, default=None, help="Last numbered folder to include.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of selected numeric folders.")


def add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--python", default=DEFAULT_PYTHON, help="Python interpreter used for ALEX helper scripts.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands and write progress events without executing.")


def add_finalization_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--finalize-to-canonical",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After a complete full-root extraction, move the numbered corpus to data/corpus. Default: true.",
    )


def add_extraction_args(parser: argparse.ArgumentParser, *, include_jobs: bool) -> None:
    parser.add_argument(
        "--extract-profile",
        choices=("fast", "balanced", "context-lite"),
        default="balanced",
        help="BioEar extraction profile. Must stay homogeneous across the corpus. Default: balanced.",
    )
    if include_jobs:
        parser.add_argument(
            "--extract-jobs",
            type=int,
            default=DEFAULT_EXTRACT_JOBS,
            help=f"Parallel BioEar extraction worker processes. Default: {DEFAULT_EXTRACT_JOBS}.",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a numbered ALEX corpus through CLI-only TextGrid/extraction phases.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Inspect numbered folders.")
    scan.add_argument("--input", type=Path, default=default_input_root())
    scan.add_argument("--json", action="store_true")
    add_selection_args(scan)

    textgrids = sub.add_parser("textgrids", help="Create TextGrids first, with skip-existing resume behavior.")
    textgrids.add_argument("--input", type=Path, default=default_input_root())
    textgrids.add_argument("--am-tag", default="mono")
    textgrids.add_argument("--speech-recipe", default="auto", choices=("auto", "bp", "generic"))
    textgrids.add_argument("--textgrid-engine", default="chunked", choices=("chunked", "sequential"))
    textgrids.add_argument("--chunk-size", type=int, default=1000)
    textgrids.add_argument("--textgrid-jobs", type=int, default=8)
    textgrids.add_argument("--retry-chunk-sizes", default="", help="Comma-separated quarantine retry chunk sizes.")
    textgrids.add_argument("--max-initial-deferred-chunks", type=int, default=3)
    textgrids.add_argument("--textgrids-per-folder", action="store_true", help="Slower but records one TextGrid command per numeric folder.")
    textgrids.add_argument("--standardize-transcriptions", action=argparse.BooleanOptionalAction, default=True)
    add_selection_args(textgrids)
    add_runtime_args(textgrids)

    standardize = sub.add_parser("standardize", help="Rewrite same-stem .txt files into G2P-safe alignment text.")
    standardize.add_argument("--input", type=Path, default=default_input_root())
    standardize.add_argument("--remove-textgrid-on-change", action="store_true", default=True)
    standardize.add_argument("--quarantine-empty", action="store_true", default=True)
    add_selection_args(standardize)
    add_runtime_args(standardize)

    extract = sub.add_parser("extract", help="Run per-folder biological auditory-periphery extraction.")
    extract.add_argument("--input", type=Path, default=default_input_root())
    extract.add_argument("--replace-confirmed", action="store_true")
    extract.add_argument("--continue-on-error", action="store_true", default=True)
    extract.add_argument("--no-continue-on-error", action="store_false", dest="continue_on_error")
    add_extraction_args(extract, include_jobs=True)
    add_selection_args(extract)
    add_runtime_args(extract)
    add_finalization_args(extract)

    build_data = sub.add_parser("build-data", help="Build the consolidated ConPhon data/corpus/bioear corpus after TextGrids exist.")
    build_data.add_argument("--input", type=Path, default=default_input_root())
    build_data.add_argument("--replace-confirmed", action="store_true")
    add_extraction_args(build_data, include_jobs=False)
    add_selection_args(build_data)
    add_runtime_args(build_data)
    add_finalization_args(build_data)

    run = sub.add_parser("run", help="Run TextGrids first, then biological per-folder extraction.")
    run.add_argument("--input", type=Path, default=default_input_root())
    run.add_argument("--am-tag", default="mono")
    run.add_argument("--speech-recipe", default="auto", choices=("auto", "bp", "generic"))
    run.add_argument("--textgrid-engine", default="chunked", choices=("chunked", "sequential"))
    run.add_argument("--chunk-size", type=int, default=1000)
    run.add_argument("--textgrid-jobs", type=int, default=8)
    run.add_argument("--retry-chunk-sizes", default="", help="Comma-separated quarantine retry chunk sizes.")
    run.add_argument("--max-initial-deferred-chunks", type=int, default=3)
    run.add_argument("--textgrids-per-folder", action="store_true")
    run.add_argument("--standardize-transcriptions", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--replace-confirmed", action="store_true")
    run.add_argument("--continue-on-error", action="store_true", default=True)
    run.add_argument("--no-continue-on-error", action="store_false", dest="continue_on_error")
    run.add_argument("--build-data", action="store_true", help="Also build the final consolidated data/corpus/bioear corpus after per-folder extraction.")
    add_extraction_args(run, include_jobs=True)
    add_selection_args(run)
    add_runtime_args(run)
    add_finalization_args(run)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.input.expanduser().resolve()
    try:
        validate_root(root)
        needs_folder_selection = args.command not in {"build-data"} and (
            args.command not in {"textgrids", "run"}
            or args.textgrids_per_folder
            or selection_requested(args)
        )
        folders = (
            selected_folders(root, start=getattr(args, "start", None), end=getattr(args, "end", None), limit=getattr(args, "limit", None))
            if needs_folder_selection
            else []
        )
        if args.command == "scan":
            payload = scan_payload(root, folders)
            path = write_summary(root, "last_scan_summary.json", payload)
            if args.json:
                print(json.dumps({**payload, "summary_path": str(path)}, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(f"Folders: {payload['folder_count']}")
                print(f"Pairs: {payload['pair_count']}")
                print(f"Triples: {payload['triple_count']}")
                print(f"Missing TextGrid: {payload['textgrid_missing_count']}")
                print(f"Issues: {payload['issue_count']}")
                print(f"Summary: {path}")
            return 0
        if args.command == "standardize":
            return run_standardize(args, root)
        if args.command == "textgrids":
            return run_textgrids(args, root, folders)
        if args.command == "extract":
            rc = run_extractions(args, root, folders)
            if rc != 0:
                return rc
            finalize_completed_corpus(args, root)
            return 0
        if args.command == "build-data":
            root = finalize_completed_corpus(args, root)
            return run_build_data(args, root)
        if args.command == "run":
            rc = run_textgrids(args, root, folders)
            if rc != 0:
                return rc
            refreshed = selected_folders(root, start=args.start, end=args.end, limit=args.limit)
            rc = run_extractions(args, root, refreshed)
            if rc != 0:
                return rc
            root = finalize_completed_corpus(args, root)
            if args.build_data:
                return run_build_data(args, root)
            return 0
    except Exception as exc:  # noqa: BLE001 - CLI should report a machine-readable failure.
        payload = {"ok": False, "error": str(exc), "command": args.command, "root": str(root)}
        try:
            path = write_summary(root, "last_error.json", payload)
            payload["summary_path"] = str(path)
        except Exception:
            pass
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
