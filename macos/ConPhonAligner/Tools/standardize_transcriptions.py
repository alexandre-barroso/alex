#!/usr/bin/env python3
"""Standardize ALEX same-stem transcript files for G2P/TextGrid alignment.

The downloaded metadata preserves the original orthographic text.  The aligner,
however, expects a conservative word stream: lowercase words, no punctuation as
word characters, and no opaque garbage tokens.  This script
rewrites the same-stem ``.txt`` files used by the aligner and records the exact
before/after text in a sibling manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_DIRNAME = "alex_numbered_cli"
MANIFEST_CSV = "alex_transcription_standardization_manifest.csv"
MANIFEST_JSON = "alex_transcription_standardization_manifest.json"
TOOLS_ROOT = Path(__file__).resolve().parent
ALEX_ROOT = TOOLS_ROOT.parent
DEFAULT_BACKEND_ROOT = ALEX_ROOT
if not (DEFAULT_BACKEND_ROOT / "src" / "conphon").exists():
    sibling_conphon = ALEX_ROOT.parent / "conphon"
    if (sibling_conphon / "src" / "conphon").exists():
        DEFAULT_BACKEND_ROOT = sibling_conphon
BACKEND_ROOT = Path(os.environ.get("CONPHON_BACKEND_ROOT", DEFAULT_BACKEND_ROOT)).expanduser().resolve()
CANONICAL_STANDARDIZATION_ROOT = BACKEND_ROOT / "data" / "metadata" / "transcription_standardization"
VOWELS = set("aeiouáàâãéêíóôõúü")
TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*(?:\s*%)?")
MAX_ALIGNER_TOKEN_CHARS = 48
LONG_LOW_DIVERSITY_TOKEN_CHARS = 32
LOW_DIVERSITY_RATIO = 0.18
ABBREVIATIONS = {
    "sr": "senhor",
    "sra": "senhora",
    "srta": "senhorita",
    "dr": "doutor",
    "dra": "doutora",
    "prof": "professor",
    "profa": "professora",
    "tv": "tevê",
    "fm": "éfe eme",
}

UNITS = {
    0: "zero",
    1: "um",
    2: "dois",
    3: "três",
    4: "quatro",
    5: "cinco",
    6: "seis",
    7: "sete",
    8: "oito",
    9: "nove",
    10: "dez",
    11: "onze",
    12: "doze",
    13: "treze",
    14: "quatorze",
    15: "quinze",
    16: "dezesseis",
    17: "dezessete",
    18: "dezoito",
    19: "dezenove",
}
TENS = {
    20: "vinte",
    30: "trinta",
    40: "quarenta",
    50: "cinquenta",
    60: "sessenta",
    70: "setenta",
    80: "oitenta",
    90: "noventa",
}
HUNDREDS = {
    100: "cem",
    200: "duzentos",
    300: "trezentos",
    400: "quatrocentos",
    500: "quinhentos",
    600: "seiscentos",
    700: "setecentos",
    800: "oitocentos",
    900: "novecentos",
}


@dataclass(frozen=True)
class Standardization:
    normalized: str
    dropped_tokens: tuple[str, ...]
    changed: bool


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def output_root(input_root: Path, override: Path | None = None) -> Path:
    out = override.expanduser().resolve() if override is not None else CANONICAL_STANDARDIZATION_ROOT
    out.mkdir(parents=True, exist_ok=True)
    return out


def numeric_folders(root: Path, *, start: int | None, end: int | None, limit: int | None) -> list[Path]:
    folders = sorted(
        (item for item in root.iterdir() if item.is_dir() and item.name.isdigit()),
        key=lambda item: int(item.name),
    )
    if start is not None:
        folders = [item for item in folders if int(item.name) >= start]
    if end is not None:
        folders = [item for item in folders if int(item.name) <= end]
    if limit is not None:
        folders = folders[: max(0, int(limit))]
    return folders


def original_text_by_number(root: Path) -> dict[int, str]:
    metadata = root.parent / "filtered" / "filtered_audio_numbering_manifest.csv"
    if not metadata.exists():
        return {}
    result: dict[int, str] = {}
    with metadata.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                number = int(str(row.get("number", "")).strip())
            except ValueError:
                continue
            result[number] = str(row.get("text") or "")
    return result


def number_to_words(n: int) -> str:
    if n < 20:
        return UNITS[n]
    if n < 100:
        ten = (n // 10) * 10
        rest = n % 10
        return TENS[ten] if rest == 0 else f"{TENS[ten]} e {UNITS[rest]}"
    if n < 1000:
        if n == 100:
            return HUNDREDS[100]
        hundred = (n // 100) * 100
        rest = n % 100
        head = "cento" if hundred == 100 else HUNDREDS[hundred]
        return head if rest == 0 else f"{head} e {number_to_words(rest)}"
    if n < 1_000_000:
        thousands = n // 1000
        rest = n % 1000
        head = "mil" if thousands == 1 else f"{number_to_words(thousands)} mil"
        if rest == 0:
            return head
        connector = " e " if rest < 100 else " "
        return f"{head}{connector}{number_to_words(rest)}"
    millions = n // 1_000_000
    rest = n % 1_000_000
    head = "um milhão" if millions == 1 else f"{number_to_words(millions)} milhões"
    if rest == 0:
        return head
    return f"{head} {number_to_words(rest)}"


def number_token_to_words(raw: str) -> str:
    token = raw.strip()
    percent = token.endswith("%")
    token = token.rstrip("%").strip()
    if not token:
        return ""
    separators = [ch for ch in token if ch in ",."]
    if separators:
        pieces = re.split(r"[,.]", token)
        if len(pieces) > 1 and all(piece.isdigit() for piece in pieces):
            thousands_like = all(len(piece) == 3 for piece in pieces[1:])
            if thousands_like:
                words = number_to_words(int("".join(pieces)))
            else:
                integer = number_to_words(int(pieces[0])) if pieces[0] else "zero"
                decimal = " ".join(number_to_words(int(ch)) for ch in "".join(pieces[1:]) if ch.isdigit())
                words = f"{integer} vírgula {decimal}".strip()
        else:
            words = " ".join(number_to_words(int(ch)) for ch in token if ch.isdigit())
    else:
        words = number_to_words(int(token))
    return f"{words} por cento" if percent else words


def replace_numbers(text: str) -> str:
    return NUMBER_RE.sub(lambda match: " " + number_token_to_words(match.group(0)) + " ", text)


def base_letters(token: str) -> str:
    decomposed = unicodedata.normalize("NFD", token)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def is_alignable_token(token: str) -> bool:
    if not any(ch in VOWELS for ch in token):
        return False
    letters = base_letters(token)
    if len(letters) > MAX_ALIGNER_TOKEN_CHARS:
        return False
    if len(letters) >= LONG_LOW_DIVERSITY_TOKEN_CHARS:
        diversity = len(set(letters)) / max(1, len(letters))
        if diversity <= LOW_DIVERSITY_RATIO:
            return False
    return True


def standardize_text(text: str) -> Standardization:
    original = text
    text = text.replace("\u00a0", " ").replace("\x13", " ").replace("½", " ")
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = replace_numbers(text)
    chars: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        if ch.isalpha() or category.startswith("M"):
            chars.append(ch)
        else:
            chars.append(" ")
    rough = unicodedata.normalize("NFC", "".join(chars))
    kept: list[str] = []
    dropped: list[str] = []
    for match in TOKEN_RE.finditer(rough):
        token = match.group(0)
        if token in ABBREVIATIONS:
            kept.extend(ABBREVIATIONS[token].split())
            continue
        if is_alignable_token(token):
            kept.append(token)
        else:
            dropped.append(token)
    normalized = re.sub(r"\s+", " ", " ".join(kept)).strip()
    return Standardization(normalized=normalized, dropped_tokens=tuple(dropped), changed=normalized != original.strip())


def same_stem_txt(folder: Path) -> tuple[Path | None, list[str]]:
    wavs = sorted(item for item in folder.iterdir() if item.is_file() and item.suffix.lower() == ".wav")
    txts = sorted(item for item in folder.iterdir() if item.is_file() and item.suffix.lower() == ".txt")
    issues: list[str] = []
    if len(wavs) != 1:
        issues.append(f"expected_one_wav_found_{len(wavs)}")
    if len(txts) != 1:
        issues.append(f"expected_one_txt_found_{len(txts)}")
    if len(wavs) == 1 and len(txts) == 1 and wavs[0].stem != txts[0].stem:
        issues.append("wav_txt_stem_mismatch")
    return (txts[0] if len(txts) == 1 else None), issues


def standardize_root(
    root: Path,
    *,
    output_root_override: Path | None = None,
    start: int | None = None,
    end: int | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    remove_textgrid_on_change: bool = False,
    quarantine_empty: bool = False,
) -> dict[str, Any]:
    originals = original_text_by_number(root)
    out = output_root(root, output_root_override)
    folders = numeric_folders(root, start=start, end=end, limit=limit)
    rows: list[dict[str, Any]] = []
    changed_count = 0
    empty_count = 0
    issue_count = 0
    removed_textgrid_count = 0
    quarantined_count = 0
    quarantine_root = out / "alignment_excluded_empty_transcripts"
    if quarantine_empty and not dry_run:
        quarantine_root.mkdir(parents=True, exist_ok=True)

    for folder in folders:
        number = int(folder.name)
        txt, issues = same_stem_txt(folder)
        if txt is None:
            issue_count += 1
            rows.append({
                "number": number,
                "txt_path": "",
                "original_text": originals.get(number, ""),
                "current_text": "",
                "normalized_text": "",
                "changed": False,
                "empty_after_normalization": True,
                "dropped_tokens": "",
                "issues": ";".join(issues),
                "current_sha256": "",
                "normalized_sha256": "",
            })
            continue
        current = txt.read_text(encoding="utf-8", errors="replace").strip()
        result = standardize_text(current)
        changed_count += int(result.changed)
        empty_after = not result.normalized
        empty_count += int(empty_after)
        issue_count += int(bool(issues))
        textgrid = txt.with_suffix(".TextGrid")
        removed_textgrid = False
        if result.changed and textgrid.exists() and remove_textgrid_on_change and not dry_run:
            textgrid.unlink()
            removed_textgrid = True
            removed_textgrid_count += 1
        if result.changed and not dry_run:
            txt.write_text(result.normalized + "\n", encoding="utf-8")
        quarantined = False
        quarantine_path = ""
        if empty_after and quarantine_empty:
            quarantine_path = str(quarantine_root / folder.name)
            quarantined = True
            if not dry_run:
                destination = quarantine_root / folder.name
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.move(str(folder), str(destination))
                quarantined_count += 1
        rows.append({
            "number": number,
            "txt_path": str(txt),
            "original_text": originals.get(number, current),
            "current_text": current,
            "normalized_text": result.normalized,
            "changed": result.changed,
            "empty_after_normalization": not result.normalized,
            "dropped_tokens": " ".join(result.dropped_tokens),
            "issues": ";".join(issues),
            "removed_textgrid": removed_textgrid,
            "quarantined": quarantined,
            "quarantine_path": quarantine_path,
            "current_sha256": sha256_text(current),
            "normalized_sha256": sha256_text(result.normalized),
        })

    manifest_csv = out / MANIFEST_CSV
    fields = [
        "number",
        "txt_path",
        "original_text",
        "current_text",
        "normalized_text",
        "changed",
        "empty_after_normalization",
        "dropped_tokens",
        "issues",
        "removed_textgrid",
        "quarantined",
        "quarantine_path",
        "current_sha256",
        "normalized_sha256",
    ]
    with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "schema": "conphon.alex.transcription_standardization.v1",
        "ok": empty_count == 0 or quarantine_empty,
        "created_at_utc": utc_now(),
        "input_root": str(root),
        "dry_run": dry_run,
        "selected_folder_count": len(folders),
        "changed_count": changed_count,
        "empty_after_normalization_count": empty_count,
        "issue_count": issue_count,
        "removed_textgrid_count": removed_textgrid_count,
        "quarantined_empty_count": quarantined_count if not dry_run else empty_count if quarantine_empty else 0,
        "quarantine_root": str(quarantine_root) if quarantine_empty else None,
        "manifest_csv": str(manifest_csv),
        "normalization": {
            "case": "lowercase",
            "numbers": "integer/thousand/decimal tokens verbalized in pt-BR where possible",
            "punctuation": "replaced by spaces",
            "opaque_tokens": "tokens without Portuguese vowels, overlong tokens, and long low-diversity tokens dropped",
            "original_text_preserved_in_manifest": True,
        },
    }
    manifest_json = out / MANIFEST_JSON
    manifest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**payload, "manifest_json": str(manifest_json)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standardize numbered ALEX .txt transcripts for G2P/TextGrid alignment.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--remove-textgrid-on-change", action="store_true")
    parser.add_argument("--quarantine-empty", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.input.expanduser().resolve()
    try:
        if not root.is_dir():
            raise RuntimeError(f"input root does not exist: {root}")
        payload = standardize_root(
            root,
            output_root_override=args.output_root,
            start=args.start,
            end=args.end,
            limit=args.limit,
            dry_run=args.dry_run,
            remove_textgrid_on_change=args.remove_textgrid_on_change,
            quarantine_empty=args.quarantine_empty,
        )
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": str(exc), "input_root": str(root)}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
