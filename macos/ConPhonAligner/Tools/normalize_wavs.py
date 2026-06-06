#!/usr/bin/env python3
"""GUI-local audio normalizer for ALEX.

This helper is intentionally separate from the repository aligner runtime. It
converts readable audio into same-folder mono 16 kHz PCM WAV before alignment
or BioEar extraction. Non-compliant WAVs are moved into ``original_wav`` and
replaced. Non-WAV files are preserved and get a sibling ``<stem>.wav``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from math import gcd
from pathlib import Path
from typing import Any

try:
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
except Exception as exc:  # noqa: BLE001 - emit a clean GUI-facing message below.
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None


TARGET_SAMPLE_RATE = 16_000


@dataclass
class Result:
    path: str
    status: str
    output_path: str | None = None
    source_sample_rate: int | None = None
    source_channels: int | None = None
    backup_path: str | None = None
    error: str | None = None


def normalize_wav(path: Path) -> Result:
    if _IMPORT_ERROR is not None:
        return Result(
            str(path),
            "failed",
            None,
            error=(
                "WAV normalization is unavailable. Install Python packages "
                f"'soundfile', 'scipy', and 'numpy'. Details: {_IMPORT_ERROR}"
            ),
        )

    try:
        target = path if path.suffix.lower() in {".wav", ".wave"} else path.with_suffix(".wav")
        if target.exists() and target != path:
            try:
                target_info = sf.info(target)
                if int(target_info.channels) == 1 and int(target_info.samplerate) == TARGET_SAMPLE_RATE:
                    return Result(str(path), "skipped_existing_wav", str(target), int(target_info.samplerate), int(target_info.channels))
            except Exception:
                pass

        info = audio_info(path)
        channels = int(info.channels)
        sample_rate = int(info.samplerate)
        if path == target and channels == 1 and sample_rate == TARGET_SAMPLE_RATE:
            return Result(str(path), "skipped", str(target), sample_rate, channels)

        data, read_sr = read_audio(path)
        mono = data[:, 0] if data.shape[1] == 1 else data.mean(axis=1)
        if int(read_sr) != TARGET_SAMPLE_RATE:
            divisor = gcd(int(read_sr), TARGET_SAMPLE_RATE)
            mono = resample_poly(
                mono,
                TARGET_SAMPLE_RATE // divisor,
                int(read_sr) // divisor,
            ).astype(np.float32)

        backup: Path | None = None
        if path == target:
            backup = move_original(path)
        elif target.exists():
            backup = move_existing_target(target)
        sf.write(target, mono, TARGET_SAMPLE_RATE, subtype="PCM_16")
        return Result(str(path), "converted", str(target), sample_rate, channels, str(backup) if backup else None)
    except Exception as exc:  # noqa: BLE001 - GUI tool must report every file.
        return Result(str(path), "failed", error=str(exc))


def audio_info(path: Path) -> Any:
    try:
        return sf.info(path)
    except Exception:
        converted = afconvert_to_temp_wav(path)
        try:
            return sf.info(converted)
        finally:
            converted.unlink(missing_ok=True)


def read_audio(path: Path) -> tuple[np.ndarray, int]:
    try:
        return sf.read(path, dtype="float32", always_2d=True)
    except Exception:
        converted = afconvert_to_temp_wav(path)
        try:
            return sf.read(converted, dtype="float32", always_2d=True)
        finally:
            converted.unlink(missing_ok=True)


def afconvert_to_temp_wav(path: Path) -> Path:
    afconvert = Path("/usr/bin/afconvert")
    if not afconvert.exists():
        raise RuntimeError(f"Cannot read {path}; libsndfile failed and /usr/bin/afconvert is unavailable.")
    tmp = Path(tempfile.NamedTemporaryFile(prefix="alex_audio_", suffix=".wav", delete=False).name)
    completed = subprocess.run(
        [str(afconvert), "-f", "WAVE", "-d", "LEI16", str(path), str(tmp)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Cannot decode audio with libsndfile or afconvert: {completed.stderr.strip()}")
    return tmp


def move_original(path: Path) -> Path:
    backup_dir = path.parent / "original_wav"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / path.name
    if target.exists():
        stem = path.stem
        suffix = path.suffix
        index = 1
        while True:
            candidate = backup_dir / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                target = candidate
                break
            index += 1
    shutil.move(str(path), str(target))
    return target


def move_existing_target(path: Path) -> Path:
    backup_dir = path.parent / "original_wav"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / path.name
    if target.exists():
        stem = path.stem
        suffix = path.suffix
        index = 1
        while True:
            candidate = backup_dir / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                target = candidate
                break
            index += 1
    shutil.move(str(path), str(target))
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize readable audio files to same-folder mono 16 kHz WAV for ALEX.")
    parser.add_argument("wav", nargs="+", type=Path, help="Audio files to inspect and normalize.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = [normalize_wav(path.expanduser().resolve()) for path in args.wav]
    payload: dict[str, Any] = {
        "ok": all(item.status != "failed" for item in results),
        "target_sample_rate": TARGET_SAMPLE_RATE,
        "results": [asdict(item) for item in results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for item in results:
            print(f"{item.status}: {item.path}")
            if item.backup_path:
                print(f"  backup: {item.backup_path}")
            if item.error:
                print(f"  error: {item.error}", file=sys.stderr)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
