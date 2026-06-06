#!/usr/bin/env python3
"""Recursively clean TextGrid interval labels in place."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from textgrid import TextGrid


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "local"))

from ctm2tg import clean_textgrid_mark  # noqa: E402


def clean_file(path: Path, dry_run: bool) -> bool:
    textgrid = TextGrid.fromFile(str(path))
    changed = False

    for tier in textgrid.tiers:
        for interval in tier:
            cleaned = clean_textgrid_mark(interval.mark)
            if cleaned != interval.mark:
                interval.mark = cleaned
                changed = True

    if changed and not dry_run:
        textgrid.write(str(path))
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lowercase and remove punctuation from every interval label in "
            "TextGrid files."
        )
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=str(SCRIPT_DIR / "demo"),
        help="Folder to scan recursively. Default: aligner/demo.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report files that would change without writing them.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        print(f"error: folder does not exist: {root}", file=sys.stderr)
        return 1

    changed = 0
    total = 0
    for path in sorted(root.rglob("*.TextGrid")):
        total += 1
        if clean_file(path, dry_run=args.dry_run):
            changed += 1
            print(f"cleaned: {path}")

    action = "would clean" if args.dry_run else "cleaned"
    print(f"{action} {changed} of {total} TextGrid file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
