from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Tools" / "normalize_wavs.py"


def test_normalizer_moves_original_and_writes_mono_16khz(tmp_path: Path) -> None:
    wav = tmp_path / "sample.wav"
    data = np.column_stack(
        [
            np.sin(np.linspace(0, 1, 800, dtype=np.float32)),
            np.cos(np.linspace(0, 1, 800, dtype=np.float32)),
        ]
    )
    sf.write(wav, data, 8000)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", str(wav)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["results"][0]["status"] == "converted"
    assert (tmp_path / "original_wav" / "sample.wav").exists()
    info = sf.info(wav)
    assert info.samplerate == 16000
    assert info.channels == 1


def test_normalizer_leaves_compliant_wav_untouched(tmp_path: Path) -> None:
    wav = tmp_path / "ok.wav"
    sf.write(wav, np.zeros(320, dtype=np.float32), 16000)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", str(wav)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["results"][0]["status"] == "skipped"
    assert not (tmp_path / "original_wav").exists()


def test_normalizer_handles_nested_batch(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    first = tmp_path / "one.wav"
    second = nested / "two.wav"
    sf.write(first, np.zeros((200, 2), dtype=np.float32), 44100)
    sf.write(second, np.zeros(200, dtype=np.float32), 22050)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", str(first), str(second)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "original_wav" / "one.wav").exists()
    assert (nested / "original_wav" / "two.wav").exists()
    assert sf.info(first).samplerate == 16000
    assert sf.info(second).samplerate == 16000
