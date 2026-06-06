from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SCRIPT = ROOT / "Tools" / "extract_bioear.py"
APPEND_SCRIPT = ROOT / "Tools" / "append_bioear_aux.py"


def test_doctor_accepts_brucezilany_as_only_backend(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    completed = _run_raw(tmp_path, "doctor", "--json", fake_backend=fake)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["backend"] == "brucezilany"
    assert payload["runtime_backend_policy"] == "required_fastbioear_backend_only"


def test_run_writes_valid_bioear_h5_with_layer_order_and_alex_sentence_preference(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    _write_valid_triple(tmp_path, "sample", alex_five_tiers=True)

    payload = _run_json(tmp_path, "run", "--input", str(tmp_path), "--limit", "1", "--quiet", "--json", fake_backend=fake)

    output = tmp_path / "sample_bioear.h5"
    assert payload["ok"] is True
    assert output.exists()
    with h5py.File(output, "r") as h5:
        assert sorted(h5.keys()) == ["labels", "periphery"]
        assert h5.attrs["schema"] == "conphon.bioear.hdf5.v1"
        assert h5.attrs["backend_module"] == "brucezilany"
        assert h5.attrs["extraction_profile"] == "balanced"
        assert "periphery/ihc_receptor_potential" not in h5
        assert "periphery/spike_count_neurogram_1ms" in h5
        assert h5["periphery/characteristic_frequency_hz"].shape == (64,)
        assert "labels/frame_phone_id" in h5
        assert "labels/intervals/sentence" in h5
        assert int(h5["labels/frame_phone_id"][0]) == 0
        resolution = json.loads(h5["labels"].attrs["tier_resolution_json"])
        assert resolution["selected_tiers"]["phone"]["name"] == "fonemas-ipa"
        assert resolution["selected_tiers"]["word"]["name"] == "grafemas"
        assert resolution["selected_tiers"]["syllable"]["name"] == "silabas-fonemas-ipa"
        assert resolution["selected_tiers"]["sentence"]["name"] == "frase-grafemas"


def test_three_tier_textgrid_synthesizes_sentence_from_word_tier(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    _write_wav(tmp_path / "three.wav")
    (tmp_path / "three.txt").write_text("apa\n", encoding="utf-8")
    (tmp_path / "three.TextGrid").write_text(_textgrid(["fonemas", "pal_orto", "sil_fon"]), encoding="utf-8")

    payload = _run_json(tmp_path, "run", "--input", str(tmp_path), "--limit", "1", "--quiet", "--json", fake_backend=fake)

    assert payload["ok"] is True
    with h5py.File(tmp_path / "three_bioear.h5", "r") as h5:
        resolution = json.loads(h5["labels"].attrs["tier_resolution_json"])
        assert resolution["policy"] == "three_tier_known_name_sentence_from_word_tier"
        assert resolution["selected_tiers"]["sentence"]["name"] == "pal_orto:aggregate_sentence"
        assert resolution["selected_tiers"]["sentence"]["name_status"] == "synthetic_sentence_from_word_tier"


def test_pair_command_writes_single_output(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    _write_valid_triple(tmp_path, "sample", alex_five_tiers=False)
    out = tmp_path / "custom_pair.h5"

    payload = _run_json(
        tmp_path,
        "pair",
        "--wav",
        str(tmp_path / "sample.wav"),
        "--textgrid",
        str(tmp_path / "sample.TextGrid"),
        "--out",
        str(out),
        "--quiet",
        "--json",
        fake_backend=fake,
    )

    assert payload["ok"] is True
    assert payload["status"] == "created"
    assert out.exists()
    with h5py.File(out, "r") as h5:
        assert h5.attrs["backend_module"] == "brucezilany"
        assert h5.attrs["extraction_profile"] == "balanced"
        assert h5.attrs["bioear_storage_profile"] == "compact_fast_rate_control_neurogram"
        assert "periphery/rate_neurogram_1ms_hz_per_fiber" in h5


def test_append_aux_sidecar_adds_balanced_ihc_synapse_and_redocking(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    _write_valid_triple(tmp_path, "sample", alex_five_tiers=False)

    _run_json(tmp_path, "run", "--input", str(tmp_path), "--quiet", "--json", fake_backend=fake)
    payload = _run_append_json(
        tmp_path,
        "--sidecar-root",
        str(tmp_path),
        "--jobs",
        "1",
        "--threads-per-file",
        "1",
        "--quiet",
        "--json",
        fake_backend=fake,
    )

    assert payload["ok"] is True
    assert payload["created_full_aux"] == 1
    with h5py.File(tmp_path / "sample_bioear.h5", "r") as h5:
        n_frames = h5["periphery/rate_neurogram_1ms_hz_per_fiber"].shape[0]
        assert h5.attrs["extraction_profile"] == "balanced"
        assert h5.attrs["bioear_auxiliary_storage_profile"] == "compact_1ms_ihc_synapse_redocking"
        assert h5.attrs["checkpoint0_phonological_substrate_ready"] == np.bool_(True)
        assert h5["periphery/ihc_receptor_potential"].shape == (n_frames, 64)
        assert h5["periphery/synapse_drive"].shape == (n_frames, 64, 3)
        assert h5["periphery/redocking_time_mean"].shape == (n_frames, 64, 3)


def test_valid_existing_h5_is_skipped_without_replace(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    _write_valid_triple(tmp_path, "sample", alex_five_tiers=False)

    first = _run_json(tmp_path, "run", "--input", str(tmp_path), "--quiet", "--json", fake_backend=fake)
    second = _run_json(tmp_path, "run", "--input", str(tmp_path), "--quiet", "--json", fake_backend=fake)

    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert second["skipped_valid_count"] == 1


def test_missing_required_layer_fails_loudly_before_model_run(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    _write_wav(tmp_path / "bad.wav")
    (tmp_path / "bad.txt").write_text("apa\n", encoding="utf-8")
    (tmp_path / "bad.TextGrid").write_text(_textgrid(["fonemas", "grafemas"]), encoding="utf-8")

    payload = _run_json(tmp_path, "run", "--input", str(tmp_path), "--quiet", "--json", fake_backend=fake, check=False)

    assert payload["ok"] is False
    assert payload["failure_count"] == 1
    assert "requires four non-empty interval tiers" in payload["failures"][0]["error"]


def test_non_16khz_wav_fails_loudly(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    _write_valid_triple(tmp_path, "bad_rate", sample_rate=22_050, alex_five_tiers=False)

    payload = _run_json(tmp_path, "run", "--input", str(tmp_path), "--quiet", "--json", fake_backend=fake, check=False)

    assert payload["ok"] is False
    assert "requires exactly 16 kHz" in payload["failures"][0]["error"]


def test_build_data_creates_only_bioear_corpus(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    root = tmp_path / "filtered_audio"
    folder = root / "7"
    folder.mkdir(parents=True)
    _write_valid_triple(folder, "sample", alex_five_tiers=False)
    output_root = tmp_path / "data" / "corpus"

    payload = _run_json(tmp_path, "build-data", "--input", str(root), "--output", str(output_root), "--quiet", "--json", fake_backend=fake)

    canonical = output_root / "bioear" / "records" / "7_bioear.h5"
    manifest_path = output_root / "bioear" / "bioear_manifest.json"

    assert payload["ok"] is True
    assert canonical.exists()
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = manifest["records"][0]

    assert manifest["schema"] == "conphon.bioear.reproducibility_manifest.v1"
    assert manifest["runtime_backend"] == "brucezilany"
    assert isinstance(manifest["brucezilany_version"], str)
    assert manifest["brucezilany_version"]
    assert manifest["extractor_constants"]["source_fs_hz"] == 16_000
    assert manifest["extractor_constants"]["model_fs_hz"] == 100_000
    assert manifest["forbidden_non_bioear_output_policy"] == {
        "forbidden_acoustic_frequent_frames": "not_created",
        "forbidden_engineered_feature_parquet": "not_created",
        "forbidden_latent_chunks": "not_created",
        "forbidden_npy_sidecars": "not_created",
        "forbidden_phonetic_detail_outputs": "not_created",
    }
    assert manifest["command_provenance"][1] == "build-data"
    assert manifest["record_count"] == 1
    assert record["number"] == 7
    assert record["hashes"]["wav_sha256"] == _sha256(folder / "sample.wav")
    assert record["hashes"]["txt_sha256"] == _sha256(folder / "sample.txt")
    assert record["hashes"]["textgrid_sha256"] == _sha256(folder / "sample.TextGrid")
    assert record["hashes"]["canonical_h5_sha256"] == _sha256(canonical)
    assert record["hashes"]["hdf5_sha256"] == _sha256(canonical)
    assert record["validation"]["ok"] is True

    assert not (output_root / "mfcc").exists()
    assert not (output_root / "_latent_chunk_states").exists()
    assert not (output_root / "_acoustic_frequent_frames").exists()
    assert not list(tmp_path.rglob("*.npy"))
    assert not list(tmp_path.rglob("*mfcc*.parquet"))
    assert not list(tmp_path.rglob("*_mfcc_manifest.tsv"))
    assert not list(tmp_path.rglob("*phonetic*"))
    assert not (folder / "latent_chunk_states").exists()
    assert not (folder / "acoustic_frequent_frames").exists()
    assert not (folder / "resultados").exists()


def test_build_data_requires_txt_for_reproducibility_manifest(tmp_path: Path) -> None:
    fake = _fake_brucezilany(tmp_path)
    root = tmp_path / "filtered_audio"
    folder = root / "7"
    folder.mkdir(parents=True)
    _write_wav(folder / "sample.wav")
    (folder / "sample.TextGrid").write_text(_textgrid(["fonemas", "pal_orto", "sil_fon", "frase_orto"]), encoding="utf-8")
    output_root = tmp_path / "data" / "corpus"

    payload = _run_json(
        tmp_path,
        "build-data",
        "--input",
        str(root),
        "--output",
        str(output_root),
        "--quiet",
        "--json",
        fake_backend=fake,
        check=False,
    )

    assert payload["ok"] is False
    assert payload["record_count"] == 0
    assert payload["failure_count"] == 1
    assert "requires source TXT provenance" in payload["failures"][0]["error"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_json(tmp_path: Path, *args: str, fake_backend: Path, check: bool = True) -> dict:
    completed = _run_raw(tmp_path, *args, fake_backend=fake_backend)
    if check:
        assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _run_raw(tmp_path: Path, *args: str, fake_backend: Path) -> subprocess.CompletedProcess[str]:
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


def _run_append_json(tmp_path: Path, *args: str, fake_backend: Path, check: bool = True) -> dict:
    completed = _run_append_raw(tmp_path, *args, fake_backend=fake_backend)
    if check:
        assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _run_append_raw(tmp_path: Path, *args: str, fake_backend: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CONPHON_BACKEND_ROOT"] = str(REPO)
    env["PYTHONPATH"] = os.pathsep.join([str(fake_backend), str(REPO / "src"), str(REPO), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, str(APPEND_SCRIPT), *args],
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


def _write_valid_triple(folder: Path, stem: str, *, sample_rate: int = 16_000, alex_five_tiers: bool) -> None:
    _write_wav(folder / f"{stem}.wav", sample_rate=sample_rate)
    (folder / f"{stem}.txt").write_text("apa\n", encoding="utf-8")
    names = ["fonemas-ipa", "grafemas", "silabas-fonemas-ipa", "frase-fonemas-ipa", "frase-grafemas"] if alex_five_tiers else ["fonemas", "pal_orto", "sil_fon", "frase_orto"]
    (folder / f"{stem}.TextGrid").write_text(_textgrid(names), encoding="utf-8")


def _write_wav(path: Path, *, sample_rate: int = 16_000) -> None:
    t = np.linspace(0, 0.004, int(sample_rate * 0.004), endpoint=False)
    wave = 0.1 * np.sin(2 * np.pi * 220 * t)
    sf.write(path, wave.astype(np.float32), sample_rate)


def _textgrid(tier_names: list[str]) -> str:
    labels = {
        "fonemas": "a",
        "fonemas-ipa": "a",
        "grafemas": "apa",
        "pal_orto": "apa",
        "sil_fon": "a-pa",
        "silabas-fonemas-ipa": "a-pa",
        "frase_fon": "a p a",
        "frase-fonemas-ipa": "a p a",
        "frase_orto": "apa",
        "frase-grafemas": "apa",
    }
    items = []
    for index, name in enumerate(tier_names, start=1):
        label = labels.get(name, name)
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
            text = "{label}"
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
