#!/usr/bin/env python3
"""Recursively align every same-stem WAV/TXT pair in a selected folder."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Pair:
    wav: Path
    txt: Path


def default_python() -> str:
    venv_python = SCRIPT_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable or "python3"


def select_folder() -> Path:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title="Select a folder containing .wav/.txt pairs"
        )
        root.destroy()
        if selected:
            return Path(selected).expanduser().resolve()
    except Exception:
        pass

    if not sys.stdin.isatty():
        raise SystemExit("error: pass a folder path when no GUI prompt is available")

    selected = input("Folder containing .wav/.txt pairs: ").strip()
    if not selected:
        raise SystemExit("error: no folder selected")
    return Path(selected).expanduser().resolve()


def find_pairs(root: Path) -> tuple[list[Pair], list[Path], list[Path]]:
    txt_by_parent_and_stem: dict[tuple[Path, str], Path] = {}
    wavs: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".txt":
            txt_by_parent_and_stem[(path.parent.resolve(), path.stem)] = path.resolve()
        elif suffix == ".wav":
            wavs.append(path.resolve())

    pairs: list[Pair] = []
    unmatched_wavs: list[Path] = []
    for wav in sorted(wavs):
        txt = txt_by_parent_and_stem.get((wav.parent.resolve(), wav.stem))
        if txt is None:
            unmatched_wavs.append(wav)
        else:
            pairs.append(Pair(wav=wav, txt=txt))

    paired_txts = {pair.txt for pair in pairs}
    unmatched_txts = sorted(
        txt for txt in txt_by_parent_and_stem.values() if txt not in paired_txts
    )
    return pairs, unmatched_wavs, unmatched_txts


def bool_arg(value: bool) -> str:
    return "true" if value else "false"


def display_paths(paths: Iterable[Path], root: Path, limit: int) -> None:
    for path in list(paths)[:limit]:
        try:
            print(f"  - {path.relative_to(root)}")
        except ValueError:
            print(f"  - {path}")


def command_chars(args: Iterable[str]) -> int:
    return sum(len(arg) + 1 for arg in args)


def pair_chars(pair: Pair) -> int:
    return len(str(pair.wav)) + len(str(pair.txt)) + 2


def chunk_pairs(args: argparse.Namespace, pairs: list[Pair]) -> list[list[Pair]]:
    base_chars = command_chars(build_command(args, []))
    chunks_out: list[list[Pair]] = []
    current: list[Pair] = []
    current_chars = base_chars

    for pair in pairs:
        extra_chars = pair_chars(pair)
        would_exceed_count = len(current) >= args.chunk_size
        would_exceed_chars = (
            current
            and current_chars + extra_chars > args.max_command_chars
        )
        if would_exceed_count or would_exceed_chars:
            chunks_out.append(current)
            current = []
            current_chars = base_chars

        current.append(pair)
        current_chars += extra_chars

    if current:
        chunks_out.append(current)
    return chunks_out


def build_command(args: argparse.Namespace, pairs: list[Pair]) -> list[str]:
    backend = SCRIPT_DIR / "aligner_backend.sh"
    cmd = [
        "bash",
        str(backend),
        "--python",
        str(Path(args.python).expanduser()),
        "--aligner-dir",
        str(Path(args.aligner_dir).expanduser()),
        "--am-tag",
        args.am_tag,
        "--annotation-validation",
        bool_arg(args.annotation_validation),
        "--continue-on-error",
        bool_arg(args.continue_on_error),
        "--overwrite",
        bool_arg(args.overwrite),
    ]
    if args.speech_recipe:
        cmd.extend(["--speech-recipe", args.speech_recipe])
    if args.speech_engine_root:
        cmd.extend(["--speech-engine-root", str(Path(args.speech_engine_root).expanduser())])
    if args.bp_acoustic_recipe_root:
        cmd.extend(["--bp-acoustic-recipe-root", str(Path(args.bp_acoustic_recipe_root).expanduser())])
    if args.annotation_validator:
        cmd.extend(["--annotation-validator", str(Path(args.annotation_validator).expanduser())])
    if args.work_dir:
        cmd.extend(["--work-dir", str(Path(args.work_dir).expanduser())])
    for pair in pairs:
        cmd.extend([str(pair.wav), str(pair.txt)])
    return cmd


def run_alignment(args: argparse.Namespace, pairs: list[Pair]) -> int:
    env = build_env()
    pair_chunks = chunk_pairs(args, pairs)
    total_chunks = len(pair_chunks)
    failures = 0

    for chunk_index, pair_chunk in enumerate(pair_chunks, start=1):
        print(
            f"Running chunk {chunk_index}/{total_chunks} "
            f"({len(pair_chunk)} pair(s))..."
        )
        cmd = build_command(args, pair_chunk)
        result = subprocess.run(cmd, env=env, check=False)
        if result.returncode != 0:
            failures += 1
            if not args.continue_on_error:
                return result.returncode

    return 1 if failures else 0


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    java_home = env.get("JAVA_HOME")
    if java_home:
        java_bin = Path(java_home) / "bin"
        if java_bin.is_dir():
            env["PATH"] = f"{java_bin}{os.pathsep}{env.get('PATH', '')}"
            return env
    openjdk_bin = Path("/opt/homebrew/opt/openjdk/bin")
    if openjdk_bin.is_dir():
        env["PATH"] = f"{openjdk_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Select a folder and recursively align every .wav/.txt pair whose "
            "filenames have the exact same stem."
        )
    )
    parser.add_argument(
        "folder",
        nargs="?",
        help="Folder to scan. If omitted, a folder picker is shown when possible.",
    )
    parser.add_argument(
        "--am-tag",
        default="mono",
        help="Acoustic model tag: mono, tri1b, tri1, tri2b, tri3b, or tdnn.",
    )
    parser.add_argument(
        "--python",
        default=default_python(),
        help="Python interpreter for the aligner backend.",
    )
    parser.add_argument(
        "--aligner-dir",
        default=str(SCRIPT_DIR / ".aligner-cache"),
        help="Model/resource cache directory.",
    )
    parser.add_argument(
        "--speech-recipe",
        default="auto",
        choices=("auto", "bp", "generic"),
        help="Speech recipe preference. Default: auto.",
    )
    parser.add_argument(
        "--speech-engine-root",
        default=str(SCRIPT_DIR / "vendor" / "speech_engine"),
        help="Speech engine root.",
    )
    parser.add_argument(
        "--bp-acoustic-recipe-root",
        default=str(SCRIPT_DIR / "vendor" / "bp_acoustic_recipe"),
        help="BP acoustic recipe root.",
    )
    parser.add_argument(
        "--annotation-validator",
        default="",
        help="Annotation validator executable used only when --annotation-validation is enabled.",
    )
    parser.add_argument(
        "--work-dir",
        default=os.environ.get("ALIGNER_WORK_DIR", ""),
        help="Writable speech recipe workspace. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing TextGrids instead of adding _1, _2, ... suffixes.",
    )
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip pairs whose same-stem TextGrid already exists. Default: true.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep processing later pairs after a failed alignment.",
    )
    parser.add_argument(
        "--annotation-validation",
        action="store_true",
        help="Validate generated TextGrids with the annotation validator. Default: false for large folder batches.",
    )
    parser.add_argument(
        "--no-annotation-validation",
        action="store_false",
        dest="annotation_validation",
        help="Keep annotation validation disabled. This is the default.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary information without running alignment.",
    )
    parser.add_argument(
        "--list-pairs",
        action="store_true",
        help="With --dry-run, print every matched pair.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="With --dry-run, print this many sample pairs unless --list-pairs is used.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=100,
        help="Maximum wav/txt pairs passed to one backend command. Default: 100.",
    )
    parser.add_argument(
        "--max-command-chars",
        type=int,
        default=120_000,
        help="Approximate maximum command-line size per backend call. Default: 120000.",
    )
    parser.add_argument(
        "--show-unmatched",
        action="store_true",
        help="Print WAV/TXT files that did not have exact same-stem partners.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.folder).expanduser().resolve() if args.folder else select_folder()

    if not root.is_dir():
        print(f"error: folder does not exist: {root}", file=sys.stderr)
        return 1

    if args.chunk_size < 1:
        print("error: --chunk-size must be at least 1", file=sys.stderr)
        return 1

    if args.max_command_chars < 10_000:
        print("error: --max-command-chars must be at least 10000", file=sys.stderr)
        return 1

    if args.sample_size < 0:
        print("error: --sample-size cannot be negative", file=sys.stderr)
        return 1

    pairs, unmatched_wavs, unmatched_txts = find_pairs(root)
    print(f"Scanning: {root}")
    print(f"Matched wav/txt pairs: {len(pairs)}")
    print(f"Unmatched wav files: {len(unmatched_wavs)}")
    print(f"Unmatched txt files: {len(unmatched_txts)}")

    if args.show_unmatched:
        if unmatched_wavs:
            print("Unmatched WAV files:")
            display_paths(unmatched_wavs, root, limit=200)
        if unmatched_txts:
            print("Unmatched TXT files:")
            display_paths(unmatched_txts, root, limit=200)

    if not pairs:
        print("No exact same-stem .wav/.txt pairs found.")
        return 1

    if args.skip_existing and not args.overwrite:
        before = len(pairs)
        pairs = [
            pair
            for pair in pairs
            if not pair.wav.with_suffix(".TextGrid").exists()
        ]
        print(f"Existing TextGrids skipped: {before - len(pairs)}")
        if not pairs:
            print("All matched pairs already have same-stem TextGrid files.")
            return 0

    print(f"Backend chunk size: {args.chunk_size}")
    print(f"Backend command budget: {args.max_command_chars} chars")
    print(f"Backend chunks: {len(chunk_pairs(args, pairs))}")

    if args.dry_run:
        if args.list_pairs:
            print("Pairs:")
            visible_pairs = pairs
        else:
            visible_pairs = pairs[: args.sample_size]
            if visible_pairs:
                print("Sample pairs:")
        for pair in visible_pairs:
            print(f"  {pair.wav} :: {pair.txt}")
        hidden = len(pairs) - len(visible_pairs)
        if hidden > 0:
            print(f"... {hidden} more pair(s) not shown. Use --list-pairs to print all.")
        return 0

    return run_alignment(args, pairs)


if __name__ == "__main__":
    raise SystemExit(main())
