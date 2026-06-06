#!/usr/bin/env python3
"""Scan and rename TextGrid layer names for ALEX BioEar extraction."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


NAME_RE = re.compile(r'(name\s*=\s*")([^"]+)(")')
CANONICAL = {
    "phonemes": "phonemes",
    "words": "words",
    "syllables": "syllables",
    "utterance": "utterance",
}


@dataclass
class ApplyResult:
    path: str
    status: str
    backup_path: str | None = None
    renamed_count: int = 0
    error: str | None = None


def textgrid_paths(root: Path):
    skipped = {"original_textgrid_layers", "original_wav", "data", "dist", ".build", "__pycache__"}
    for path in root.rglob("*.TextGrid"):
        if any(part in skipped for part in path.parts):
            continue
        yield path
    for path in root.rglob("*.textgrid"):
        if any(part in skipped for part in path.parts):
            continue
        yield path


def tier_names(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [match.group(2) for match in NAME_RE.finditer(text)]


def scan(root: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    textgrid_count = 0
    seen: set[Path] = set()
    for path in textgrid_paths(root):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        textgrid_count += 1
        for name in tier_names(path):
            counts[name] += 1
            examples.setdefault(name, str(path))
    return {
        "ok": True,
        "root": str(root),
        "textgrid_count": textgrid_count,
        "layer_names": [
            {"name": name, "count": count, "example": examples.get(name)}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
        ],
    }


def backup_path_for(path: Path, root: Path) -> Path:
    backup_root = root / "original_textgrid_layers"
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = Path(path.name)
    target = backup_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        return target
    index = 1
    while True:
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def apply_mapping(root: Path, mapping: dict[str, str]) -> dict[str, Any]:
    normalized_mapping = {
        source: CANONICAL[target]
        for source, target in mapping.items()
        if source and target in CANONICAL and source != CANONICAL[target]
    }
    results: list[ApplyResult] = []
    changed = 0
    for path in textgrid_paths(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            renamed_count = 0

            def replace(match: re.Match[str]) -> str:
                nonlocal renamed_count
                old = match.group(2)
                new = normalized_mapping.get(old)
                if new is None:
                    return match.group(0)
                renamed_count += 1
                return f"{match.group(1)}{new}{match.group(3)}"

            updated = NAME_RE.sub(replace, text)
            if updated == text:
                results.append(ApplyResult(str(path), "unchanged"))
                continue
            backup = backup_path_for(path, root)
            shutil.copy2(path, backup)
            path.write_text(updated, encoding="utf-8")
            changed += 1
            results.append(ApplyResult(str(path), "renamed", str(backup), renamed_count))
        except Exception as exc:  # noqa: BLE001
            results.append(ApplyResult(str(path), "failed", error=str(exc)))
    failed = [item for item in results if item.status == "failed"]
    return {
        "ok": not failed,
        "root": str(root),
        "changed_count": changed,
        "failed_count": len(failed),
        "mapping": normalized_mapping,
        "results": [asdict(item) for item in results],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan or standardize TextGrid layer names for ALEX.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--phone", default="")
    parser.add_argument("--word", default="")
    parser.add_argument("--syllable", default="")
    parser.add_argument("--sentence", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(payload)


def main() -> int:
    args = parse_args()
    root = args.input.expanduser().resolve()
    if not root.is_dir():
        emit({"ok": False, "error": f"input folder does not exist: {root}"}, args.json)
        return 2
    if args.scan:
        emit(scan(root), args.json)
        return 0
    mapping = {
        args.phone: "phonemes",
        args.word: "words",
        args.syllable: "syllables",
        args.sentence: "utterance",
    }
    payload = apply_mapping(root, mapping)
    emit(payload, args.json)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
