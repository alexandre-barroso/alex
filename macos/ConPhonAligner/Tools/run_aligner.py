#!/usr/bin/env python3
"""GUI-local alignment wrapper that enforces canonical TextGrid tier names.

This script intentionally lives outside ``aligner/``. It delegates alignment to
the repository-local ALEX speech engine. New BP TextGrids are emitted with the
same canonical layer names the BioEar extractor accepts for every language:

phonemes, words, syllables, utterance

The post-run normalizer remains only as a compatibility safety net for older
embedded alignment outputs.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ALEX_ROOT = Path(__file__).resolve().parents[3]
ALIGNER_ROOT = Path(os.environ.get("CONPHON_ALIGNER_ROOT", ALEX_ROOT / "aligner")).expanduser()
SEQUENTIAL_ALIGNER_SCRIPT = ALIGNER_ROOT / "align_folder.py"
CHUNKED_ALIGNER_SCRIPT = ALIGNER_ROOT / "align_folder_chunked.py"
BUNDLED_ALIGNER_CACHE = ALIGNER_ROOT / "model_cache"
VENDOR_ROOT = ALIGNER_ROOT / "vendor"
BUNDLED_SPEECH_ENGINE = (
    VENDOR_ROOT / "speech_engine"
    if (VENDOR_ROOT / "speech_engine").exists()
    else VENDOR_ROOT / "speech_engine"
)
BUNDLED_BP_RECIPE = (
    VENDOR_ROOT / "bp_acoustic_recipe"
    if (VENDOR_ROOT / "bp_acoustic_recipe").exists()
    else VENDOR_ROOT / "bp_acoustic_recipe"
)
STANDARDIZER = Path(__file__).resolve().with_name("standardize_transcriptions.py")
SKIP_DIRS = {
    ".build",
    "dist",
    "conceptual_communication",
    "original_wav",
    "results",
    "resultados",
}
TIER_RENAMES = {
    "fonemas-ipa": "phonemes",
    "fonemas": "phonemes",
    "phone": "phonemes",
    "phones": "phonemes",
    "phoneme": "phonemes",
    "phonemes": "phonemes",
    "grafemas": "words",
    "pal_orto": "words",
    "word": "words",
    "words": "words",
    "silabas-fonemas-ipa": "syllables",
    "silabas-fonemas": "syllables",
    "sil_fon": "syllables",
    "syllable": "syllables",
    "syllables": "syllables",
    "syl": "syllables",
    "frase-fonemas-ipa": "sentence_phonemes",
    "frase-fonemas": "sentence_phonemes",
    "frase_fon": "sentence_phonemes",
    "frase-grafemas": "utterance",
    "frase_orto": "utterance",
    "sentence": "utterance",
    "sentences": "utterance",
    "utterance": "utterance",
    "utterances": "utterance",
}
REQUIRED_PREFIX = ("phonemes", "words", "syllables")
REQUIRED_SENTENCE_NAME = "utterance"
NAME_PATTERN = re.compile(r'(^\s*name\s*=\s*")([^"]+)("\s*$)', re.MULTILINE)
CHUNKED_NOOP_FLAGS = {
    "--skip-existing",
    "--continue-on-error",
    "--show-unmatched",
    "--list-pairs",
    "--annotation-validation",
    "--no-annotation-validation",
}
CHUNKED_DROPPED_VALUE_OPTIONS = {
    "--max-command-chars",
    "--sample-size",
    "--annotation-validator",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the ALEX TextGrid aligner and normalize tier names.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--engine",
        default=os.environ.get("ALEX_ALIGNER_ENGINE", "chunked"),
        choices=("chunked", "sequential"),
        help="Alignment engine. chunked batches many utterances per speech-engine run; sequential preserves the old one-pair path.",
    )
    parser.add_argument("input", type=Path, help="Pasta com pares .wav/.txt.")
    args, aligner_args = parser.parse_known_args()
    args.aligner_args = aligner_args
    return args

def default_cache_root() -> Path:
    override = os.environ.get("ALEX_CACHE_ROOT")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ALEX"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ALEX"


def symlink_dir(source: Path, target: Path) -> None:
    if target.is_symlink():
        if Path(os.readlink(target)) == source:
            return
        target.unlink()
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source, target_is_directory=True)


def copy_embedded_model_cache(target: Path) -> None:
    if not BUNDLED_ALIGNER_CACHE.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    required = ["data.tar.gz", "m2m.model.gz", "mono.tar.gz", "fb_nlplib.jar"]
    if all((target / name).exists() for name in required) and (target / "mono" / "final.mdl").exists():
        return
    shutil.copytree(BUNDLED_ALIGNER_CACHE, target, dirs_exist_ok=True)


def prepare_writable_backend() -> tuple[Path, Path]:
    cache_root = default_cache_root()
    runtime_engine = cache_root / "speech-engine-runtime"
    runtime_egs = runtime_engine / "egs"
    aligner_cache = cache_root / "aligner-cache"

    if not BUNDLED_SPEECH_ENGINE.exists():
        raise RuntimeError(f"Motor de fala ALEX embutido não encontrado: {BUNDLED_SPEECH_ENGINE}")

    runtime_engine.mkdir(parents=True, exist_ok=True)
    runtime_egs.mkdir(parents=True, exist_ok=True)
    for name in ["src", "tools"]:
        symlink_dir(BUNDLED_SPEECH_ENGINE / name, runtime_engine / name)
    for recipe in ["wsj", "librispeech"]:
        source = BUNDLED_SPEECH_ENGINE / "egs" / recipe
        if source.exists():
            symlink_dir(source, runtime_egs / recipe)
    (runtime_egs / "aligner").mkdir(parents=True, exist_ok=True)
    copy_embedded_model_cache(aligner_cache)
    return runtime_engine, aligner_cache


def option_present(args: list[str], option: str) -> bool:
    return any(item == option or item.startswith(option + "=") for item in args)


def backend_args_with_writable_paths(raw_args: list[str]) -> list[str]:
    args = list(raw_args)
    if os.environ.get("ALEX_USE_WRITABLE_SPEECH_ENGINE_RUNTIME") == "1":
        runtime_engine, aligner_cache = prepare_writable_backend()
    else:
        runtime_engine, aligner_cache = BUNDLED_SPEECH_ENGINE, BUNDLED_ALIGNER_CACHE
    work_dir = default_cache_root() / "chunked_alignment_work"
    if not option_present(args, "--speech-engine-root"):
        args.extend(["--speech-engine-root", str(runtime_engine)])
    if not option_present(args, "--bp-acoustic-recipe-root") and BUNDLED_BP_RECIPE.exists():
        args.extend(["--bp-acoustic-recipe-root", str(BUNDLED_BP_RECIPE)])
    if not option_present(args, "--aligner-dir"):
        args.extend(["--aligner-dir", str(aligner_cache)])
    if not option_present(args, "--work-dir"):
        args.extend(["--work-dir", str(work_dir)])
    return args


def chunked_args(raw_args: list[str]) -> list[str]:
    args: list[str] = []
    skip_next = False
    for item in raw_args:
        if skip_next:
            skip_next = False
            continue
        if item == "--no-skip-existing" or item.startswith("--skip-existing=false"):
            if "--overwrite" not in args:
                args.append("--overwrite")
            continue
        if item in CHUNKED_NOOP_FLAGS:
            continue
        if any(item.startswith(option + "=") for option in CHUNKED_DROPPED_VALUE_OPTIONS):
            continue
        if item in CHUNKED_DROPPED_VALUE_OPTIONS:
            skip_next = True
            continue
        args.append(item)
    jobs = os.environ.get("ALEX_ALIGNER_JOBS")
    if jobs and not option_present(args, "--jobs"):
        args.extend(["--jobs", jobs])
    return args


def aligner_script_for_engine(engine: str) -> Path:
    if engine == "sequential":
        return SEQUENTIAL_ALIGNER_SCRIPT
    return CHUNKED_ALIGNER_SCRIPT


def standardize_transcriptions(root: Path) -> int:
    if not STANDARDIZER.exists():
        print(f"Padronizador de transcrições não encontrado: {STANDARDIZER}", file=sys.stderr)
        return 2
    metadata_root = default_cache_root() / "transcription_standardization"
    command = [
        sys.executable,
        str(STANDARDIZER),
        "--input",
        str(root),
        "--output-root",
        str(metadata_root),
        "--json",
        "--remove-textgrid-on-change",
        "--quarantine-empty",
    ]
    completed = subprocess.run(command, cwd=str(ALEX_ROOT))
    return completed.returncode



def candidate_textgrids(root: Path) -> Iterable[Path]:
    for wav in sorted(root.rglob("*.wav")):
        if any(part in SKIP_DIRS for part in wav.relative_to(root).parts[:-1]):
            continue
        txt = wav.with_suffix(".txt")
        textgrid = wav.with_suffix(".TextGrid")
        if txt.exists() and textgrid.exists():
            yield textgrid


def normalize_textgrid(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    seen: list[str] = []

    def replace(match: re.Match[str]) -> str:
        old = match.group(2)
        new = TIER_RENAMES.get(old, old)
        seen.append(new)
        return f"{match.group(1)}{new}{match.group(3)}"

    updated = NAME_PATTERN.sub(replace, text)
    if seen[:3] != list(REQUIRED_PREFIX) or REQUIRED_SENTENCE_NAME not in seen[3:]:
        # Keep the file usable, but make the condition visible in the terminal log.
        print(
            "Warning: non-canonical TextGrid tier order/name in "
            f"{path}: {seen} (expected phonemes, words, syllables, utterance)",
            file=sys.stderr,
        )
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def normalize_folder(root: Path) -> int:
    changed = 0
    for textgrid in candidate_textgrids(root):
        if normalize_textgrid(textgrid):
            changed += 1
    return changed


def main() -> int:
    args = parse_args()
    input_root = args.input.expanduser().resolve()
    if not input_root.is_dir():
        print(f"Pasta de entrada não existe: {input_root}", file=sys.stderr)
        return 2
    aligner_script = aligner_script_for_engine(args.engine)
    if not aligner_script.exists():
        print(f"Backend do alinhador não encontrado: {aligner_script}", file=sys.stderr)
        return 2

    if os.environ.get("ALEX_SKIP_TEXT_STANDARDIZER") != "1":
        standardizer_rc = standardize_transcriptions(input_root)
        if standardizer_rc != 0:
            return standardizer_rc

    aligner_args = backend_args_with_writable_paths(args.aligner_args)
    if args.engine == "chunked":
        aligner_args = chunked_args(aligner_args)
    command = [sys.executable, str(aligner_script), str(input_root), *aligner_args]
    completed = subprocess.run(command, cwd=str(ALIGNER_ROOT))
    if completed.returncode != 0:
        return completed.returncode

    changed = normalize_folder(input_root)
    print(
        "Canonical TextGrid tiers enforced: "
        "phonemes, words, syllables, utterance "
        f"({changed} file(s) adjusted)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
