from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SCRIPT = ROOT / "Tools" / "run_numbered_corpus_cli.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_numbered_corpus_cli", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_pair(folder: Path, stem: str, *, textgrid: bool) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.wav").write_bytes(b"RIFF....WAVE")
    (folder / f"{stem}.txt").write_text("texto\n", encoding="utf-8")
    if textgrid:
        (folder / f"{stem}.TextGrid").write_text("TextGrid\n", encoding="utf-8")


def test_scan_numbered_folders_and_missing_textgrid(tmp_path: Path) -> None:
    mod = load_module()
    root = tmp_path / "filtered_audio"
    write_pair(root / "2", "b", textgrid=False)
    write_pair(root / "1", "a", textgrid=True)

    folders = mod.selected_folders(root, start=None, end=None, limit=None)
    payload = mod.scan_payload(root, folders)

    assert [item.number for item in folders] == [1, 2]
    assert payload["folder_count"] == 2
    assert payload["pair_count"] == 2
    assert payload["triple_count"] == 1
    assert payload["textgrid_missing_count"] == 1
    assert payload["bioear_done_count"] == 0


def test_state_dir_uses_filtered_sibling_not_filtered_audio(tmp_path: Path) -> None:
    mod = load_module()
    dataset = tmp_path / "CORAA"
    root = dataset / "filtered_audio"
    filtered = dataset / "filtered"
    root.mkdir(parents=True)
    filtered.mkdir()

    state = mod.state_dir(root)

    assert state == filtered / "alex_numbered_cli"
    assert state.exists()
    assert not (root / ".alex_numbered_cli").exists()


def test_extract_invokes_bioear_and_resumes_from_valid_hdf5(tmp_path: Path) -> None:
    fake_backend = _fake_brucezilany(tmp_path)
    root = tmp_path / "filtered_audio"
    folder = root / "1"
    _write_valid_triple(folder, "sample")

    first = _run_numbered(
        fake_backend,
        "extract",
        "--input",
        str(root),
        "--limit",
        "1",
        "--python",
        sys.executable,
    )

    output = folder / "sample_bioear.h5"
    assert first.returncode == 0, first.stderr
    assert output.exists()
    with h5py.File(output, "r") as h5:
        assert h5.attrs["schema"] == "conphon.bioear.hdf5.v1"
        assert h5.attrs["backend_module"] == "brucezilany"
        assert h5.attrs["extraction_profile"] == "balanced"
        assert "periphery/rate_neurogram_1ms_hz_per_fiber" in h5
        assert "labels/frame_phone_id" in h5

    mod = load_module()
    folders = mod.selected_folders(root, start=None, end=None, limit=None)
    payload = mod.scan_payload(root, folders)
    assert payload["bioear_done_count"] == 1
    assert payload["bioear_pending_count"] == 0

    second = _run_numbered(
        fake_backend,
        "extract",
        "--input",
        str(root),
        "--limit",
        "1",
        "--python",
        sys.executable,
    )

    assert second.returncode == 0, second.stderr
    assert "skipped_existing" in second.stdout
    assert not (folder / "resultados").exists()
    assert not list(root.rglob("*.npy"))
    assert not list(root.rglob("*_mfcc_manifest.tsv"))


def _run_numbered(fake_backend: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CONPHON_BACKEND_ROOT"] = str(REPO)
    env["PYTHONPATH"] = os.pathsep.join([str(fake_backend), str(REPO / "src"), str(REPO), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _fake_brucezilany(tmp_path: Path) -> Path:
    root = tmp_path / "fake_backend"
    pkg = root / "brucezilany"
    pkg.mkdir(parents=True)
    (pkg / "stimulus.py").write_text(
        """
class Stimulus:
    def __init__(self, pressure, sample_rate, duration):
        self.pressure = pressure
        self.sample_rate = sample_rate
        self.duration = duration
""",
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text(
        """
import numpy as np

HUMAN_SHERA = "human_shera"
RANDOM = "random"
ACTUAL = "actual"
SOFTPLUS = "softplus"
__version__ = "fake-test"

def set_seed(seed):
    np.random.seed(seed)

def inner_hair_cell(stimulus, cf, n_rep, cohc, cihc, species):
    return np.zeros(len(stimulus.pressure), dtype=np.float32)

def map_to_synapse(ihc_output, spontaneous_firing_rate, characteristic_frequency, time_resolution, mapping_function):
    return np.asarray(ihc_output, dtype=np.float32)

class SynapseOutput:
    def __init__(self, n):
        self.psth = np.zeros(n, dtype=np.float32)
        self.synaptic_output = np.zeros(n, dtype=np.float32)
        self.redocking_time = np.zeros(n, dtype=np.float32)
        self.mean_firing_rate = [0.0]
        self.spike_times = []

def synapse(amplitude_ihc, cf, n_rep, n_timesteps, time_resolution, noise, pla_impl, spontaneous_firing_rate, calculate_stats):
    return SynapseOutput(n_timesteps)

APPROXIMATED = "approximated"
ACTUAL = "actual"
__version__ = "0.0.4+fastbioear"

class FastRateResult:
    def __init__(self, n_frames, n_cf, n_fiber_types):
        self.spike_counts = np.zeros((n_frames, n_cf, n_fiber_types), dtype=np.uint32)
        self.rate_neurogram = np.ones((n_frames, n_cf, n_fiber_types), dtype=np.float32)
        self.ihc_receptor_potential = np.zeros((n_cf, n_frames * 100), dtype=np.float32)
        self.synapse_drive = np.ones((n_cf, n_fiber_types, n_frames * 100), dtype=np.float32)
        self.n_samples = n_frames * 100

def fast_rate_neurogram(sound_wave, cfs, spontaneous_rates, fibers_per_type, bin_width, n_rep, species, noise_type, power_law, mapping_function, seed_base, save_ihc, save_synapse_drive, n_threads):
    n_frames = max(1, int(np.ceil(float(sound_wave.duration) / float(bin_width))))
    return FastRateResult(n_frames, len(cfs), len(spontaneous_rates))
""",
        encoding="utf-8",
    )
    return root


def _write_valid_triple(folder: Path, stem: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    _write_wav(folder / f"{stem}.wav")
    (folder / f"{stem}.txt").write_text("apa\n", encoding="utf-8")
    (folder / f"{stem}.TextGrid").write_text(
        _textgrid(["fonemas", "pal_orto", "sil_fon", "frase_orto"]),
        encoding="utf-8",
    )


def _write_wav(path: Path) -> None:
    sample_rate = 16_000
    t = np.linspace(0, 0.004, int(sample_rate * 0.004), endpoint=False)
    wave = 0.1 * np.sin(2 * np.pi * 220 * t)
    sf.write(path, wave.astype(np.float32), sample_rate)


def _textgrid(tier_names: list[str]) -> str:
    labels = {
        "fonemas": "a",
        "pal_orto": "apa",
        "sil_fon": "a-pa",
        "frase_orto": "apa",
    }
    items = []
    for index, name in enumerate(tier_names, start=1):
        items.append(
            f"""    item [{index}]:
        class = "IntervalTier"
        name = "{name}"
        xmin = 0
        xmax = 0.004
        intervals: size = 1
        intervals [1]:
            xmin = 0
            xmax = 0.004
            text = "{labels[name]}"
"""
        )
    return f"""File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 0.004
tiers? <exists>
size = {len(tier_names)}
item []:
{''.join(items)}"""
