#!/usr/bin/env python3
"""Chunked folder aligner for large same-stem WAV/TXT corpora.

This runner keeps the aligner's speech-engine/TextGrid contract but prepares and
aligns many utterances per speech-engine batch. It is intended for large corpora where
calling aligner.sh once per file is too slow.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CORPUS = Path("data") / "corpus"
DEFAULT_WORK_DIR = Path("data") / "metadata" / "numbered_audio" / "chunked_alignment_work"
MAX_ALIGNER_TOKEN_CHARS = 48
LONG_LOW_DIVERSITY_TOKEN_CHARS = 32
LOW_DIVERSITY_RATIO = 0.18
UTT_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
SCAN_SKIP_DIRS = {"metadata", "bioear", "__pycache__"}


@dataclass(frozen=True)
class Pair:
    wav: Path
    txt: Path
    textgrid: Path
    utt_id: str


@dataclass(frozen=True)
class SanitizedAlignmentText:
    text: str
    dropped_tokens: tuple[str, ...]


def default_python() -> str:
    venv_python = SCRIPT_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable or "python3"


def absolute_path_preserve_symlink(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return Path.cwd() / candidate


def legacy_engine_key(suffix: str) -> str:
    return "".join(("KA", "LD", suffix))


def utc_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_jsonl(handle: TextIO, payload: dict) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    handle.flush()


def run(cmd: list[str], *, env: dict[str, str], log: TextIO, cwd: Path | None = None) -> int:
    log.write("$ " + " ".join(cmd) + "\n")
    log.flush()
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, stdout=log, stderr=subprocess.STDOUT)
    log.flush()
    return int(proc.returncode)


def run_shell(script: str, *, env: dict[str, str], log: TextIO, cwd: Path) -> int:
    log.write("$ bash -c <chunk-script>\n")
    log.flush()
    proc = subprocess.run(["bash", "-c", script], cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT)
    log.flush()
    return int(proc.returncode)


def find_pairs(root: Path, overwrite: bool) -> tuple[list[Pair], list[Pair], list[Path], list[Path]]:
    txt_by_key: dict[tuple[Path, str], Path] = {}
    wavs: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if should_skip_corpus_file(root, path):
            continue
        if path.suffix.lower() == ".txt":
            txt_by_key[(path.parent.resolve(), path.stem)] = path.resolve()
        elif path.suffix.lower() == ".wav":
            wavs.append(path.resolve())

    pairs: list[Pair] = []
    skipped_existing: list[Pair] = []
    unmatched_wavs: list[Path] = []
    for wav in sorted(wavs):
        txt = txt_by_key.get((wav.parent.resolve(), wav.stem))
        if txt is None:
            unmatched_wavs.append(wav)
            continue
        pair = Pair(wav=wav, txt=txt, textgrid=wav.with_suffix(".TextGrid"), utt_id=utterance_id(root, wav))
        if pair.textgrid.exists() and not overwrite:
            skipped_existing.append(pair)
        else:
            pairs.append(pair)

    matched_txts = {pair.txt for pair in pairs} | {pair.txt for pair in skipped_existing}
    unmatched_txts = sorted(txt for txt in txt_by_key.values() if txt not in matched_txts)
    return pairs, skipped_existing, unmatched_wavs, unmatched_txts


def should_skip_corpus_file(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    parent_parts = relative.parts[:-1]
    if any(part in SCAN_SKIP_DIRS or part.startswith(".") for part in parent_parts):
        return True
    if root.name.isdigit():
        return path.parent != root
    if len(relative.parts) == 1:
        return False
    return not (len(relative.parts) == 2 and relative.parts[0].isdigit())


def chunks(items: list[Pair], size: int) -> list[list[Pair]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def utterance_id(root: Path, wav: Path) -> str:
    relative = wav.relative_to(root).with_suffix("")
    raw = "__".join(relative.parts)
    utt_id = UTT_ID_SAFE_RE.sub("_", raw).strip("_")
    return utt_id or wav.stem


def ensure_symlink(source: Path, target: Path) -> None:
    if target.is_symlink() or target.exists():
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.symlink_to(source)


def ensure_speech_engine_lib_dir(speech_engine_root: Path) -> None:
    """Expose speech-engine dylibs at src/lib for @loader_path/../lib rpaths."""
    src_root = speech_engine_root / "src"
    lib_dir = src_root / "lib"
    if lib_dir.exists() and not lib_dir.is_dir():
        return
    try:
        lib_dir.mkdir(exist_ok=True)
    except OSError:
        return
    for dylib in sorted(src_root.glob("*/libkaldi-*.dylib")):
        if dylib.parent == lib_dir:
            continue
        target = lib_dir / dylib.name
        relative = Path("..") / dylib.parent.name / dylib.name
        try:
            if target.is_symlink():
                if Path(os.readlink(target)) == relative:
                    continue
                target.unlink()
            if target.exists():
                continue
            target.symlink_to(relative)
        except OSError:
            continue


def base_letters(token: str) -> str:
    letters = "".join(ch for ch in token.casefold() if ch.isalpha())
    decomposed = unicodedata.normalize("NFD", letters)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def is_pathological_alignment_token(token: str) -> bool:
    letters = base_letters(token)
    if not letters:
        return False
    if len(letters) > MAX_ALIGNER_TOKEN_CHARS:
        return True
    if len(letters) >= LONG_LOW_DIVERSITY_TOKEN_CHARS:
        diversity = len(set(letters)) / max(1, len(letters))
        if diversity <= LOW_DIVERSITY_RATIO:
            return True
    return False


def sanitize_alignment_text(text: str) -> SanitizedAlignmentText:
    kept: list[str] = []
    dropped: list[str] = []
    for token in text.split():
        if is_pathological_alignment_token(token):
            dropped.append(token)
        else:
            kept.append(token)
    return SanitizedAlignmentText(text=" ".join(kept).strip(), dropped_tokens=tuple(dropped))


def select_recipe_workspace(speech_engine_root: Path, bp_acoustic_recipe_root: Path, recipe: str) -> Path:
    bp_s5 = bp_acoustic_recipe_root / "bp_default_recipe"
    generic_s5 = speech_engine_root / "egs" / "wsj" / "s5"

    if recipe not in {"auto", "bp", "generic"}:
        raise SystemExit(f"bad speech recipe: {recipe}")

    if recipe != "generic" and bp_acoustic_recipe_root.is_dir():
        if (bp_s5 / "steps").exists() and (bp_s5 / "utils").exists() and (bp_s5 / "path.sh").exists():
            return bp_s5
        if recipe == "bp":
            raise SystemExit("BP acoustic recipe requested but support files are unavailable")

    if (generic_s5 / "steps").exists() and (generic_s5 / "utils").exists() and (generic_s5 / "path.sh").exists():
        return generic_s5

    raise SystemExit(f"no usable speech recipe found under {speech_engine_root}")


def prepare_egs(args: argparse.Namespace, env: dict[str, str], log: TextIO) -> Path:
    speech_engine_root = Path(args.speech_engine_root).expanduser().resolve()
    bp_acoustic_recipe_root = Path(args.bp_acoustic_recipe_root).expanduser().resolve()
    aligner_dir = Path(args.aligner_dir).expanduser().resolve()
    ensure_speech_engine_lib_dir(speech_engine_root)
    recipe_workspace = select_recipe_workspace(speech_engine_root, bp_acoustic_recipe_root, args.speech_recipe)
    work_dir = Path(args.work_dir).expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    ensure_symlink(speech_engine_root / "tools", work_dir / "tools")
    ensure_symlink(speech_engine_root / "src", work_dir / "src")
    egs_dir = work_dir / "egs" / "aligner" / "s5"

    for folder in (aligner_dir, egs_dir):
        folder.mkdir(parents=True, exist_ok=True)

    check = [
        "bash",
        str(SCRIPT_DIR / "utils" / "check_dependencies.sh"),
        "--python",
        str(Path(args.python).expanduser()),
        "--locale",
        args.locale,
        "--speech-recipe",
        args.speech_recipe,
        "--bp-acoustic-recipe-root",
        str(bp_acoustic_recipe_root),
        "--require-annotation-validator",
        "false",
    ]
    if run(check, env=env, log=log) != 0:
        raise SystemExit("dependency check failed")

    for artifact in ("data", "m2m", args.am_tag):
        cmd = [
            "bash",
            str(SCRIPT_DIR / "utils" / "download_model.sh"),
            "--python",
            str(Path(args.python).expanduser()),
            artifact,
            str(aligner_dir),
        ]
        if run(cmd, env=env, log=log) != 0:
            raise SystemExit(f"model download/check failed for {artifact}")

    for child in ("data", "conf", "local"):
        target = egs_dir / child
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
    for child in ("steps", "utils", "path.sh"):
        target = egs_dir / child
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
    shutil.copytree(SCRIPT_DIR / "conf", egs_dir / "conf")
    shutil.copytree(SCRIPT_DIR / "local", egs_dir / "local")
    shutil.copytree(aligner_dir / "data", egs_dir / "data")
    ensure_symlink(recipe_workspace / "steps", egs_dir / "steps")
    ensure_symlink(recipe_workspace / "utils", egs_dir / "utils")
    ensure_symlink(recipe_workspace / "path.sh", egs_dir / "path.sh")
    return egs_dir


def write_chunk_data(egs_dir: Path, pairs: list[Pair]) -> tuple[list[Pair], list[Pair], list[tuple[Pair, tuple[str, ...], bool]]]:
    alignme = egs_dir / "data" / "alignme"
    if alignme.exists():
        shutil.rmtree(alignme)
    alignme.mkdir(parents=True)
    (egs_dir / "data" / "local").mkdir(parents=True, exist_ok=True)

    good: list[Pair] = []
    empty: list[Pair] = []
    sanitized_records: list[tuple[Pair, tuple[str, ...], bool]] = []
    with (alignme / "wav.scp").open("w", encoding="utf-8") as wav_scp, (
        alignme / "text"
    ).open("w", encoding="utf-8") as text_file, (alignme / "utt2spk").open(
        "w", encoding="utf-8"
    ) as utt2spk, (egs_dir / "data" / "local" / "chunk_transcripts.txt").open(
        "w", encoding="utf-8"
    ) as chunk_text:
        for pair in sorted(pairs, key=lambda item: item.utt_id):
            raw_text = pair.txt.read_text(encoding="utf-8").strip()
            sanitized = sanitize_alignment_text(raw_text)
            text = sanitized.text
            if sanitized.dropped_tokens:
                sanitized_records.append((pair, sanitized.dropped_tokens, not bool(text)))
            if not text:
                empty.append(pair)
                continue
            wav_scp.write(f"{pair.utt_id} {pair.wav}\n")
            text_file.write(f"{pair.utt_id} {text}\n")
            utt2spk.write(f"{pair.utt_id} {pair.utt_id}\n")
            chunk_text.write(text + "\n")
            good.append(pair)
    return good, empty, sanitized_records


def write_transcript_corpus(egs_dir: Path, pairs: list[Pair], name: str) -> tuple[Path, int, int, int]:
    local_dir = egs_dir / "data" / "local"
    local_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = local_dir / name
    written = 0
    empty = 0
    dropped = 0
    with transcript_file.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            raw_text = pair.txt.read_text(encoding="utf-8").strip()
            sanitized = sanitize_alignment_text(raw_text)
            text = sanitized.text
            dropped += len(sanitized.dropped_tokens)
            if not text:
                empty += 1
                continue
            handle.write(text + "\n")
            written += 1
    return transcript_file, written, empty, dropped


def mark_failed_pairs(ledger: TextIO, pairs: list[Pair], *, chunk: str, reason: str) -> None:
    for pair in pairs:
        write_jsonl(
            ledger,
            {
                "event": "failed_pair",
                "reason": reason,
                "chunk": chunk,
                "utt_id": pair.utt_id,
                "wav": str(pair.wav),
                "txt": str(pair.txt),
                "textgrid": str(pair.textgrid),
            },
        )


def quarantine_pair_folder(args: argparse.Namespace, pair: Pair, *, reason: str, ledger: TextIO) -> None:
    source = pair.wav.parent
    quarantine_value = getattr(args, "quarantine_dir", None)
    if not quarantine_value or not source.name.isdigit():
        write_jsonl(
            ledger,
            {
                "event": "unalignable_pair_not_quarantined",
                "reason": reason,
                "utt_id": pair.utt_id,
                "wav": str(pair.wav),
                "txt": str(pair.txt),
                "folder": str(source),
            },
        )
        return
    quarantine_root = Path(quarantine_value).expanduser()
    try:
        source_resolved = source.resolve()
        quarantine_resolved = quarantine_root.resolve()
        if source_resolved == quarantine_resolved or quarantine_resolved in source_resolved.parents:
            raise RuntimeError("source already inside quarantine root")
        destination_dir = quarantine_root / reason
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        suffix = 1
        while destination.exists():
            suffix += 1
            destination = destination_dir / f"{source.name}_{suffix}"
        shutil.move(str(source), str(destination))
        write_jsonl(
            ledger,
            {
                "event": "unalignable_folder_quarantined",
                "reason": reason,
                "utt_id": pair.utt_id,
                "source": str(source),
                "destination": str(destination),
                "wav": str(pair.wav),
                "txt": str(pair.txt),
            },
        )
    except Exception as exc:  # noqa: BLE001 - quarantine should not hide the root alignment failure.
        write_jsonl(
            ledger,
            {
                "event": "unalignable_folder_quarantine_failed",
                "reason": reason,
                "utt_id": pair.utt_id,
                "folder": str(source),
                "error": str(exc),
            },
        )


def quarantine_failed_pairs(args: argparse.Namespace, pairs: list[Pair], *, chunk: str, reason: str, ledger: TextIO) -> None:
    mark_failed_pairs(ledger, pairs, chunk=chunk, reason=reason)
    for pair in pairs:
        quarantine_pair_folder(args, pair, reason=reason, ledger=ledger)


def keep_or_quarantine_deferred_pairs(
    args: argparse.Namespace,
    attempts: dict[str, int],
    pairs: list[Pair],
    *,
    chunk: str,
    ledger: TextIO,
) -> list[Pair]:
    max_attempts = max(1, int(getattr(args, "max_deferred_attempts", 3)))
    keep: list[Pair] = []
    exhausted: list[Pair] = []
    for pair in pairs:
        attempts[pair.utt_id] = attempts.get(pair.utt_id, 0) + 1
        if attempts[pair.utt_id] >= max_attempts:
            exhausted.append(pair)
        else:
            keep.append(pair)
    if exhausted:
        quarantine_failed_pairs(args, exhausted, chunk=chunk, reason="retry_attempts_exhausted", ledger=ledger)
        write_jsonl(
            ledger,
            {
                "event": "retry_attempts_exhausted",
                "chunk": chunk,
                "max_attempts": max_attempts,
                "quarantined": len(exhausted),
            },
        )
    return keep


def failed_decode_utterances(egs_dir: Path) -> set[str]:
    """Return utterance ids that the speech engine explicitly failed to decode."""
    log_dir = egs_dir / "data" / "alignme_ali" / "log"
    failed: set[str] = set()
    if not log_dir.exists():
        return failed
    pattern = re.compile(r"Did not successfully decode file\s+(\S+),")
    for path in sorted(log_dir.glob("align.*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        failed.update(match.group(1) for match in pattern.finditer(text))
    return failed


def zero_feature_utterances(egs_dir: Path) -> set[str]:
    path = egs_dir / "data" / "alignme" / "zero_feature_utts"
    if not path.exists():
        return set()
    return {line.strip().split()[0] for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()}


def retry_sizes(initial_size: int, value: str) -> list[int]:
    if value.strip():
        sizes = [int(item.strip()) for item in value.split(",") if item.strip()]
    else:
        candidates = [max(1, initial_size // 10), 100, 20, 5, 1]
        sizes = []
        for size in candidates:
            if size < initial_size and size not in sizes:
                sizes.append(size)
    return [size for size in sizes if size >= 1]


def prepare_global_lang(args: argparse.Namespace, env: dict[str, str], egs_dir: Path, pairs: list[Pair], ledger: TextIO, log: TextIO) -> None:
    started = time.time()
    transcript_file, written, empty, dropped = write_transcript_corpus(egs_dir, pairs, "all_transcripts.txt")
    write_jsonl(
        ledger,
        {
            "event": "global_lang_started",
            "transcript_file": str(transcript_file),
            "transcript_count": written,
            "empty_transcript_count": empty,
            "sanitized_dropped_token_count": dropped,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    code = run_shell(
        prepare_lang_script(args, "data/local/all_transcripts.txt"),
        env=env,
        log=log,
        cwd=egs_dir,
    )
    write_jsonl(
        ledger,
        {
            "event": "global_lang_completed" if code == 0 else "global_lang_failed",
            "returncode": code,
            "duration_s": round(time.time() - started, 3),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if code != 0:
        raise SystemExit("global language graph build failed")


def speech_path_block() -> str:
    return """
. path.sh
KALDI_ROOT_ABS="$(cd "$KALDI_ROOT" && pwd -P)"
ALEX_KALDI_LIB_PATHS="$(find -L "$KALDI_ROOT_ABS/src" -mindepth 2 -maxdepth 2 -name 'libkaldi-*.dylib' -exec dirname {} \\; | sort -u | paste -sd: -)"
if [ -n "$ALEX_KALDI_LIB_PATHS" ]; then
  export DYLD_LIBRARY_PATH="${ALEX_KALDI_LIB_PATHS}${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi
export PATH="$KALDI_ROOT_ABS/tools/openfst-1.8.4/bin:$KALDI_ROOT_ABS/tools/openfst/bin:$PWD/utils/parallel:$PWD/utils:$PWD:$PATH"
command -v run.pl >/dev/null || { echo "run.pl not found after path setup" >&2; exit 127; }
command -v fstcompile >/dev/null || { echo "fstcompile not found after path setup" >&2; exit 127; }
"""


def prepare_lang_script(args: argparse.Namespace, transcript_file: str) -> str:
    am_tag = args.am_tag
    python_bin = shlex.quote(str(absolute_path_preserve_symlink(args.python)))
    aligner_dir = shlex.quote(str(Path(args.aligner_dir).expanduser().resolve()))
    locale = shlex.quote(args.locale)
    return f"""
set -euo pipefail
{speech_path_block()}
export PYTHON_BIN={python_bin}
export ALIGNER_DIR={aligner_dir}
export ALIGNER_LOCALE={locale}
export PATH="$(dirname "$PYTHON_BIN"):$PATH"
ALIGNER_DIR="$ALIGNER_DIR" ALIGNER_LOCALE="$ALIGNER_LOCALE" PYTHON_BIN="$PYTHON_BIN" \\
  bash local/ext_dict.sh {transcript_file} data/dict/lexicon.txt data/dict/syllables.txt data/dict/syllphones.txt
rm -f data/dict/lexiconp.txt data/dict/lexiconp_disambig.txt
rm -rf data/lang_tmp data/lang
utils/prepare_lang.sh data/dict "<UNK>" data/lang_tmp data/lang
test -s data/lang/words.txt
"""


def chunk_script(args: argparse.Namespace, jobs: int) -> str:
    am_tag = args.am_tag
    conf = "conf/mfcc_hires.conf" if am_tag == "tdnn" else "conf/mfcc.conf"
    python_bin = shlex.quote(str(absolute_path_preserve_symlink(args.python)))
    aligner_dir = shlex.quote(str(Path(args.aligner_dir).expanduser().resolve()))
    locale = shlex.quote(args.locale)
    tdnn_ivectors = ""
    tdnn_align = ""
    if am_tag == "tdnn":
        tdnn_ivectors = (
            'steps/online/nnet2/extract_ivectors_online.sh --nj "$JOBS" '
            'data/alignme "$ALIGNER_DIR/ie" data/alignme/ivector_hires || exit 1\n'
        )
        tdnn_align = (
            'steps/nnet3/align.sh --nj "$JOBS" --use-gpu false '
            f'--beam "{args.beam}" --retry-beam "{args.retry_beam}" '
            "--online-ivector-dir data/alignme/ivector_hires "
            "--scale-opts '--transition-scale=1.0 --acoustic-scale=1.0 --self-loop-scale=1.0' "
            f'data/alignme data/lang "$ALIGNER_DIR/{am_tag}" data/alignme_ali || exit 1'
        )
    else:
        tdnn_align = (
            f'steps/align_si.sh --nj "$JOBS" --beam "{args.beam}" --retry-beam "{args.retry_beam}" '
            f'data/alignme data/lang "$ALIGNER_DIR/{am_tag}" data/alignme_ali || exit 1'
        )

    frame_shift = '--frame-shift=0.03' if am_tag == "tdnn" else ""
    if args.prebuild_lang:
        lang_block = 'test -s data/lang/words.txt || { echo "prebuilt data/lang is missing" >&2; exit 1; }'
    else:
        lang_block = prepare_lang_script(args, "data/local/chunk_transcripts.txt")
    return f"""
set -euo pipefail
{speech_path_block()}
export PYTHON_BIN={python_bin}
export ALIGNER_DIR={aligner_dir}
export ALIGNER_LOCALE={locale}
export PATH="$(dirname "$PYTHON_BIN"):$PATH"
export JOBS={jobs}
rm -rf data/alignme_ali data/{am_tag}.phonemes.ctm data/{am_tag}.graphemes.ctm
utils/utt2spk_to_spk2utt.pl data/alignme/utt2spk > data/alignme/spk2utt
{lang_block}
steps/make_mfcc.sh --nj "$JOBS" --mfcc-config "{conf}" data/alignme
feat-to-len scp:data/alignme/feats.scp ark,t:data/alignme/utt2num_frames
awk '$2 == 0 {{print $1}}' data/alignme/utt2num_frames > data/alignme/zero_feature_utts
if [ -s data/alignme/zero_feature_utts ]; then
  for table in feats.scp wav.scp text utt2spk; do
    cp "data/alignme/$table" "data/alignme/$table.before_zero_feature_filter"
    awk 'NR==FNR {{bad[$1]=1; next}} !($1 in bad)' data/alignme/zero_feature_utts "data/alignme/$table" > "data/alignme/$table.tmp"
    mv "data/alignme/$table.tmp" "data/alignme/$table"
  done
  utils/utt2spk_to_spk2utt.pl data/alignme/utt2spk > data/alignme/spk2utt
fi
test -s data/alignme/feats.scp || {{ echo "all utterances produced zero-frame MFCCs" >&2; exit 42; }}
SURVIVING_UTTS=$(wc -l < data/alignme/utt2spk | tr -d ' ')
if [ "$SURVIVING_UTTS" -lt "$JOBS" ]; then
  export JOBS="$SURVIVING_UTTS"
fi
steps/compute_cmvn_stats.sh data/alignme
utils/fix_data_dir.sh data/alignme
{tdnn_ivectors}{tdnn_align}
: > data/{am_tag}.phonemes.ctm
: > data/{am_tag}.graphemes.ctm
for ali in data/alignme_ali/ali.*.gz ; do
  [ ! -e "$ali" ] && echo "no alignment archives found" >&2 && exit 1
  ali-to-phones {frame_shift} --ctm-output=true "$ALIGNER_DIR/{am_tag}/final.mdl" ark:"gunzip -c $ali |" - | \\
    tee "${{ali%.gz}}_p.ctm" | \\
    utils/int2sym.pl -f 5 data/lang/phones.txt | \\
    "$PYTHON_BIN" local/strip.py >> data/{am_tag}.phonemes.ctm
  linear-to-nbest "ark:gunzip -c $ali |" \\
    "ark:utils/sym2int.pl --map-oov 2 -f 2- data/lang/words.txt < data/alignme/text |" \\
    '' '' ark:- | \\
    lattice-align-words data/lang/phones/word_boundary.int "$ALIGNER_DIR/{am_tag}/final.mdl" ark:- ark:- | \\
    nbest-to-ctm {frame_shift} --precision=3 --print-silence=true ark:- - | \\
    tee "${{ali%.gz}}_w.ctm" | \\
    utils/int2sym.pl -f 5 data/lang/words.txt | \\
    "$PYTHON_BIN" local/strip.py >> data/{am_tag}.graphemes.ctm
done
"$PYTHON_BIN" local/ctm2tg.py \\
  --graphemes-ctm-file "$PWD/data/{am_tag}.graphemes.ctm" \\
  --phonemes-ctm-file "$PWD/data/{am_tag}.phonemes.ctm" \\
  --phonetic-dictionary "$PWD/data/dict/lexicon.txt" \\
  --syllphones-dictionary "$PWD/data/dict/syllphones.txt" \\
  --output-dir "$CHUNK_OUTPUT_DIR"
"""


def align_chunk(
    *,
    args: argparse.Namespace,
    env: dict[str, str],
    egs_dir: Path,
    pairs: list[Pair],
    chunk_index: str,
    ledger: TextIO,
    log: TextIO,
) -> tuple[int, int, int, list[Pair], bool]:
    if not pairs:
        return 0, 0, 0, [], False

    good, empty, sanitized_records = write_chunk_data(egs_dir, pairs)
    for pair, dropped_tokens, empty_after_sanitization in sanitized_records:
        write_jsonl(
            ledger,
            {
                "event": "alignment_text_sanitized",
                "chunk": chunk_index,
                "utt_id": pair.utt_id,
                "txt": str(pair.txt),
                "dropped_token_count": len(dropped_tokens),
                "dropped_tokens": list(dropped_tokens[:20]),
                "empty_after_sanitization": empty_after_sanitization,
            },
        )
    for pair in empty:
        write_jsonl(
            ledger,
            {
                "event": "skipped_empty_transcript",
                "utt_id": pair.utt_id,
                "wav": str(pair.wav),
                "txt": str(pair.txt),
                "textgrid": str(pair.textgrid),
                "chunk": chunk_index,
            },
        )
    if not good:
        return 0, len(empty), 0, [], False

    output_dir = Path(args.work_dir).expanduser().resolve() / "chunk_textgrids" / chunk_index
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunk_env = env.copy()
    chunk_env["CHUNK_OUTPUT_DIR"] = str(output_dir)
    jobs = max(1, min(int(args.jobs), len(good)))
    started = time.time()
    write_jsonl(
        ledger,
        {
            "event": "chunk_started",
            "chunk": chunk_index,
            "pairs": len(pairs),
            "alignable_pairs": len(good),
            "jobs": jobs,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    code = run_shell(chunk_script(args, jobs), env=chunk_env, log=log, cwd=egs_dir)
    zero_feature_utts = zero_feature_utterances(egs_dir)
    zero_feature_pairs = [pair for pair in good if pair.utt_id in zero_feature_utts]
    zero_feature_count = len(zero_feature_pairs)
    if zero_feature_pairs:
        quarantine_failed_pairs(args, zero_feature_pairs, chunk=chunk_index, reason="zero_frame_mfcc", ledger=ledger)
        good = [pair for pair in good if pair.utt_id not in zero_feature_utts]
        write_jsonl(
            ledger,
            {
                "event": "zero_frame_mfcc_filtered",
                "chunk": chunk_index,
                "filtered": zero_feature_count,
                "remaining_alignable_pairs": len(good),
            },
        )
    if code != 0 and not good and zero_feature_count:
        return 0, len(empty), 0, [], False
    if code != 0:
        failed_utts = failed_decode_utterances(egs_dir)
        write_jsonl(
            ledger,
            {
                "event": "chunk_failed",
                "chunk": chunk_index,
                "pairs": len(good),
                "returncode": code,
                "speech_decode_failed": len(failed_utts),
                "duration_s": round(time.time() - started, 3),
            },
        )
        failed_pairs = [pair for pair in good if pair.utt_id in failed_utts]
        if failed_pairs:
            if len(good) == 1:
                quarantine_failed_pairs(args, failed_pairs, chunk=chunk_index, reason="speech_decode_failed", ledger=ledger)
                return 0, len(empty), 0, [], False
            write_jsonl(
                ledger,
                {
                    "event": "chunk_deferred",
                    "reason": "retry_after_decode_failures",
                    "chunk": chunk_index,
                    "speech_decode_failed": len(failed_pairs),
                    "deferred_pairs": len(good),
                },
            )
            return 0, len(empty), 0, good, False
        if len(good) == 1:
            quarantine_failed_pairs(args, good, chunk=chunk_index, reason="chunk_failed_without_decode_id", ledger=ledger)
            return 0, len(empty), 0, [], False
        write_jsonl(
            ledger,
            {
                "event": "chunk_deferred",
                "reason": "chunk_failed_retry_later",
                "chunk": chunk_index,
                "deferred_pairs": len(good),
            },
        )
        return 0, len(empty), 0, good, True

    written = 0
    missing_pairs: list[Pair] = []
    for pair in good:
        generated = output_dir / f"{pair.utt_id}.TextGrid"
        if not generated.exists() or generated.stat().st_size == 0:
            missing_pairs.append(pair)
            write_jsonl(
                ledger,
                {
                    "event": "missing_textgrid_after_chunk",
                    "chunk": chunk_index,
                    "utt_id": pair.utt_id,
                    "wav": str(pair.wav),
                    "txt": str(pair.txt),
                    "expected_generated": str(generated),
                    "target": str(pair.textgrid),
                },
            )
            continue
        pair.textgrid.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(generated), str(pair.textgrid))
        written += 1

    write_jsonl(
        ledger,
        {
            "event": "chunk_completed",
            "chunk": chunk_index,
            "written": written,
            "missing": len(missing_pairs),
            "empty": len(empty),
            "zero_frame_mfcc_quarantined": zero_feature_count,
            "duration_s": round(time.time() - started, 3),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return written, len(empty), 0, missing_pairs, written == 0 and bool(missing_pairs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast chunked aligner TextGrid generation for folders.")
    parser.add_argument("folder", nargs="?", default=str(DEFAULT_CORPUS))
    parser.add_argument("--am-tag", default="mono", choices=("mono", "tri1", "tri1b", "tri2b", "tri3b", "tdnn"))
    parser.add_argument("--speech-recipe", default="auto", choices=("auto", "bp", "generic"))
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--beam", type=int, default=10)
    parser.add_argument("--retry-beam", type=int, default=40)
    parser.add_argument("--python", default=default_python())
    parser.add_argument("--locale", default=os.environ.get("ALIGNER_LOCALE", "pt_BR.UTF-8"))
    parser.add_argument("--aligner-dir", default=str(SCRIPT_DIR / ".aligner-cache"))
    parser.add_argument("--speech-engine-root", default=str(SCRIPT_DIR / "vendor" / "speech_engine"))
    parser.add_argument("--bp-acoustic-recipe-root", default=str(SCRIPT_DIR / "vendor" / "bp_acoustic_recipe"))
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument("--ledger", default="")
    parser.add_argument("--log", default="")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--prebuild-lang",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Build one global data/lang before chunking and reuse it. Default: true.",
    )
    parser.add_argument(
        "--retry-chunk-sizes",
        default="",
        help="Comma-separated quarantine retry chunk sizes. Default derives from --chunk-size, ending at 1.",
    )
    parser.add_argument(
        "--max-initial-deferred-chunks",
        type=int,
        default=3,
        help="Abort if this many primary chunks defer before any TextGrid is written, which usually means a setup bug.",
    )
    parser.add_argument(
        "--max-deferred-attempts",
        type=int,
        default=3,
        help="Quarantine a pair after this many failed deferred attempts. Default: 3.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.am_tag == "tri1":
        args.am_tag = "tri1b"

    root = Path(args.folder).expanduser().resolve()
    run_id = utc_id()
    metadata_dir = root.parent / "metadata" if root.name == "pairs" else root / "metadata"
    ledger_path = Path(args.ledger) if args.ledger else metadata_dir / f"textgrid_chunked_alignment_{run_id}.jsonl"
    log_path = Path(args.log) if args.log else metadata_dir / f"textgrid_chunked_alignment_{run_id}.log"
    latest_ledger = metadata_dir / "latest_textgrid_chunked_alignment.jsonl"
    latest_log = metadata_dir / "latest_textgrid_chunked_alignment.log"
    args.quarantine_dir = str(metadata_dir / "unalignable_alignment_folders")

    pairs, skipped_existing, unmatched_wavs, unmatched_txts = find_pairs(root, args.overwrite)
    planned_chunks = chunks(pairs, args.chunk_size)
    summary = {
        "run_id": run_id,
        "root": str(root),
        "matched_pending_pairs": len(pairs),
        "skipped_existing": len(skipped_existing),
        "unmatched_wavs": len(unmatched_wavs),
        "unmatched_txts": len(unmatched_txts),
        "chunk_size": args.chunk_size,
        "chunks": len(planned_chunks),
        "jobs": args.jobs,
        "prebuild_lang": bool(args.prebuild_lang),
        "retry_chunk_sizes": retry_sizes(args.chunk_size, args.retry_chunk_sizes),
        "max_deferred_attempts": args.max_deferred_attempts,
        "am_tag": args.am_tag,
        "log": str(log_path),
        "ledger": str(ledger_path),
        "dry_run": bool(args.dry_run),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if args.dry_run:
        return 0

    metadata_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHON_BIN"] = str(absolute_path_preserve_symlink(args.python))
    env["ALIGNER_LOCALE"] = args.locale
    env["ALIGNER_DIR"] = str(Path(args.aligner_dir).expanduser().resolve())
    env["ALEX_SPEECH_ENGINE_ROOT"] = str(Path(args.speech_engine_root).expanduser().resolve())
    env["ALEX_BP_ACOUSTIC_RECIPE_ROOT"] = str(Path(args.bp_acoustic_recipe_root).expanduser().resolve())
    env["ALEX_SPEECH_RECIPE"] = args.speech_recipe
    env[legacy_engine_key("I_ROOT")] = env["ALEX_SPEECH_ENGINE_ROOT"]
    env[legacy_engine_key("I_BR_ROOT")] = env["ALEX_BP_ACOUSTIC_RECIPE_ROOT"]
    env[legacy_engine_key("I_RECIPE")] = env["ALEX_SPEECH_RECIPE"]
    java_home = env.get("JAVA_HOME")
    if java_home:
        java_bin = Path(java_home) / "bin"
        if java_bin.is_dir():
            env["PATH"] = f"{java_bin}{os.pathsep}{env.get('PATH', '')}"
    else:
        openjdk_bin = Path("/opt/homebrew/opt/openjdk/bin")
        if openjdk_bin.is_dir():
            env["PATH"] = f"{openjdk_bin}{os.pathsep}{env.get('PATH', '')}"

    total_written = 0
    total_empty = 0
    total_failed = 0
    deferred_pairs: list[Pair] = []
    deferred_attempts: dict[str, int] = {}
    initial_deferred_streak = 0
    with log_path.open("a", encoding="utf-8") as log, ledger_path.open("a", encoding="utf-8") as ledger:
        write_jsonl(ledger, {"event": "run_started", **summary, "started_at": datetime.now(timezone.utc).isoformat()})
        egs_dir = prepare_egs(args, env, log)
        if args.prebuild_lang:
            prepare_global_lang(args, env, egs_dir, pairs, ledger, log)
        for idx, pair_chunk in enumerate(planned_chunks, start=1):
            written, empty, failed, deferred, systemic_deferred = align_chunk(
                args=args,
                env=env,
                egs_dir=egs_dir,
                pairs=pair_chunk,
                chunk_index=f"{idx:06d}",
                ledger=ledger,
                log=log,
            )
            total_written += written
            total_empty += empty
            total_failed += failed
            retained_deferred = keep_or_quarantine_deferred_pairs(
                args, deferred_attempts, deferred, chunk=f"{idx:06d}", ledger=ledger
            )
            deferred_pairs.extend(retained_deferred)
            if written == 0 and retained_deferred and systemic_deferred and total_written == 0:
                initial_deferred_streak += 1
                if initial_deferred_streak >= args.max_initial_deferred_chunks:
                    write_jsonl(
                        ledger,
                        {
                            "event": "aborted_systemic_chunk_failure",
                            "reason": "primary chunks deferred before any TextGrid was written",
                            "deferred_total": len(deferred_pairs),
                            "chunks_done": idx,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    raise SystemExit("first primary chunks deferred before any TextGrid was written; inspect log before continuing")
            elif written > 0:
                initial_deferred_streak = 0
            write_jsonl(
                ledger,
                {
                    "event": "progress",
                    "chunks_done": idx,
                    "chunks_total": len(planned_chunks),
                    "written_total": total_written,
                    "empty_total": total_empty,
                    "failed_total": total_failed,
                    "deferred_total": len(deferred_pairs),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        for round_index, size in enumerate(retry_sizes(args.chunk_size, args.retry_chunk_sizes), start=1):
            if not deferred_pairs:
                break
            current_retry = deferred_pairs
            deferred_pairs = []
            retry_chunks = chunks(current_retry, size)
            write_jsonl(
                ledger,
                {
                    "event": "quarantine_round_started",
                    "round": round_index,
                    "chunk_size": size,
                    "pairs": len(current_retry),
                    "chunks": len(retry_chunks),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            for retry_idx, pair_chunk in enumerate(retry_chunks, start=1):
                written, empty, failed, deferred, _systemic_deferred = align_chunk(
                    args=args,
                    env=env,
                    egs_dir=egs_dir,
                    pairs=pair_chunk,
                    chunk_index=f"retry{round_index:02d}_{retry_idx:06d}",
                    ledger=ledger,
                    log=log,
                )
                total_written += written
                total_empty += empty
                total_failed += failed
                chunk_name = f"retry{round_index:02d}_{retry_idx:06d}"
                deferred_pairs.extend(
                    keep_or_quarantine_deferred_pairs(args, deferred_attempts, deferred, chunk=chunk_name, ledger=ledger)
                )
                write_jsonl(
                    ledger,
                    {
                        "event": "quarantine_progress",
                        "round": round_index,
                        "chunks_done": retry_idx,
                        "chunks_total": len(retry_chunks),
                        "written_total": total_written,
                        "empty_total": total_empty,
                        "failed_total": total_failed,
                        "deferred_total": len(deferred_pairs),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            write_jsonl(
                ledger,
                {
                    "event": "quarantine_round_completed",
                    "round": round_index,
                    "remaining_deferred": len(deferred_pairs),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        if deferred_pairs:
            quarantine_failed_pairs(args, deferred_pairs, chunk="quarantine_exhausted", reason="retry_exhausted", ledger=ledger)
            deferred_pairs = []
        result = {
            "event": "run_completed",
            "run_id": run_id,
            "written_total": total_written,
            "empty_total": total_empty,
            "failed_total": total_failed,
            "deferred_remaining_total": len(deferred_pairs),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        write_jsonl(ledger, result)

    for latest, path in ((latest_ledger, ledger_path), (latest_log, log_path)):
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(path.name)
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
