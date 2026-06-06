from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import sys
import traceback
import threading
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, Future, ProcessPoolExecutor, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import h5py
import numpy as np
import soundfile as sf
from scipy import signal


BIOEAR_SCHEMA = "conphon.bioear.hdf5.v1"
MANIFEST_SCHEMA = "conphon.bioear.reproducibility_manifest.v1"
QUALITY_REPORT_SCHEMA = "conphon.bioear.quality_report.v1"
RECORD_INDEX_SCHEMA = "conphon.bioear.record_index.v1"
INTERVAL_INDEX_SCHEMA = "conphon.bioear.interval_index.v1"

BIOEAR_MANIFEST_NAME = "bioear_manifest.json"
BIOEAR_QUALITY_REPORT_NAME = "bioear_quality_report.json"
BIOEAR_RECORD_INDEX_NAME = "record_index.parquet"
BIOEAR_INTERVAL_INDEX_NAME = "interval_index.parquet"
BIOEAR_RECORDS_DIRNAME = "records"

SOURCE_FS = 16_000
MODEL_FS = 100_000
P_REF_PA = 20e-6
TARGET_DB_SPL = 65.0
LEAD_SILENCE_S = 0.050
TRAIL_SILENCE_S = 0.050
N_CF = 80
LOW_CF_HZ = 125.0
HIGH_CF_HZ_16K_SAFE = 7600.0
BIN_S = 0.001
FRAME_HOP_BASE_ATOL_S = 1.0e-6
FRAME_HOP_FLOAT32_MAX_ATOL_S = 5.0e-4
RANDOM_SEED_BASE = 13_579
_GRACEFUL_STOP_REQUESTED = threading.Event()


def request_graceful_stop() -> None:
    _GRACEFUL_STOP_REQUESTED.set()


def clear_graceful_stop() -> None:
    _GRACEFUL_STOP_REQUESTED.clear()


def graceful_stop_requested() -> bool:
    return _GRACEFUL_STOP_REQUESTED.is_set()

FIBER_TYPES: tuple[tuple[str, float, int], ...] = (
    ("hsr", 100.0, 12),
    ("msr", 10.0, 4),
    ("lsr", 1.0, 4),
)
BIOEAR_PROFILE_CONFIGS: dict[str, dict[str, Any]] = {
    "fast": {
        "n_cf": 48,
        "fiber_types": (("hsr", 100.0, 1), ("msr", 10.0, 1), ("lsr", 1.0, 1)),
        "power_law": "APPROXIMATED",
    },
    "balanced": {
        "n_cf": 64,
        "fiber_types": (("hsr", 100.0, 6), ("msr", 10.0, 2), ("lsr", 1.0, 2)),
        "power_law": "APPROXIMATED",
    },
    "context-lite": {
        "n_cf": 80,
        "fiber_types": (("hsr", 100.0, 12), ("msr", 10.0, 4), ("lsr", 1.0, 4)),
        "power_law": "ACTUAL",
    },
}

LEVELS = ("phone", "syllable", "word", "sentence")
ORDER_LEVELS = ("phone", "word", "syllable", "sentence")

KNOWN_TIER_NAMES: dict[str, set[str]] = {
    "phone": {"fonemas", "fonemas-ipa", "phone", "phones", "phoneme", "phonemes"},
    "word": {"pal_orto", "grafemas", "word", "words", "ortografia", "orthography", "hanzi", "hanzis"},
    "syllable": {"sil_fon", "silabas-fonemas", "silabas-fonemas-ipa", "syllable", "syllables", "syl", "syll", "sylls"},
    "sentence": {
        "frase_orto",
        "frase-grafemas",
        "frase_fon",
        "frase-fonemas",
        "frase-fonemas-ipa",
        "sentence",
        "sentences",
        "utterance",
        "utterances",
    },
}
ORTHOGRAPHIC_SENTENCE_NAMES = {"frase_orto", "frase-grafemas", "sentence", "sentences", "utterance", "utterances"}
PHONETIC_SENTENCE_NAMES = {"frase_fon", "frase-fonemas", "frase-fonemas-ipa"}
MANDARIN_THREE_TIER_POLICY = "mandarin_three_layer_hanzi_pinyin_phone"
MANDARIN_HANZI_TIER_NAMES = {"hanzi", "hanzis", "hanzi_words", "characters", "chars", "words", "汉字", "漢字"}
MANDARIN_PINYIN_TIER_NAMES = {"pinyin", "pinyins", "pinying", "pinyings", "syllable", "syllables"}
MANDARIN_PHONE_TIER_NAMES = {"phone", "phones", "phoneme", "phonemes"}

REQUIRED_DATASETS = (
    "periphery/characteristic_frequency_hz",
    "periphery/spike_count_neurogram_1ms",
    "periphery/rate_neurogram_1ms_hz_per_fiber",
    "periphery/frame_model_time_s",
    "periphery/frame_original_time_s",
    "labels/frame_phone_id",
    "labels/frame_syllable_id",
    "labels/frame_word_id",
    "labels/frame_sentence_id",
    "labels/intervals/phone",
    "labels/intervals/syllable",
    "labels/intervals/word",
    "labels/intervals/sentence",
    "labels/summaries/phone/mean_rate_hz_per_fiber",
    "labels/summaries/phone/spike_counts",
    "labels/summaries/syllable/mean_rate_hz_per_fiber",
    "labels/summaries/syllable/spike_counts",
    "labels/summaries/word/mean_rate_hz_per_fiber",
    "labels/summaries/word/spike_counts",
    "labels/summaries/sentence/mean_rate_hz_per_fiber",
    "labels/summaries/sentence/spike_counts",
)

OPTIONAL_AUXILIARY_DATASETS = (
    "audio/source_dimensionless_wav_16k",
    "audio/source_pressure_pa_100k_unpadded",
    "audio/model_pressure_pa_100k_padded",
    "periphery/ihc_receptor_potential_1ms",
    "periphery/synapse_drive_1ms",
    "periphery/synaptic_output_mean",
    "periphery/redocking_time_1ms",
    "periphery/psth_rate_highres_hz_per_fiber",
    "periphery/spike_events",
)

FORBIDDEN_NON_BIOEAR_OUTPUT_POLICY = {
    "forbidden_engineered_feature_parquet": "not_created",
    "forbidden_latent_chunks": "not_created",
    "forbidden_acoustic_frequent_frames": "not_created",
    "forbidden_npy_sidecars": "not_created",
    "forbidden_phonetic_detail_outputs": "not_created",
}

OFFICIAL_BACKEND_MODULE = "brucezilany"
OFFICIAL_BRUCEZILANY_VERSION = "0.0.4+fastbioear"
VALID_BACKEND_MODULES = {OFFICIAL_BACKEND_MODULE}
EXTRACTION_PROFILES = tuple(BIOEAR_PROFILE_CONFIGS)
CANONICAL_EXTRACTION_PROFILE = "balanced"
AUTO_EXTRACTION_PROFILE = "auto"
FAST_BIOEAR_THREADS_PER_FILE_ENV = "CONPHON_BIOEAR_THREADS_PER_FILE"


class BioEarError(RuntimeError):
    """Raised when the biological extractor contract is violated."""


@dataclass(frozen=True)
class Interval:
    start: float
    end: float
    label: str


@dataclass(frozen=True)
class BioEarPair:
    wav: Path
    textgrid: Path
    txt: Path | None
    output: Path
    number: int | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def profile_config(profile: str) -> dict[str, Any]:
    if profile not in BIOEAR_PROFILE_CONFIGS:
        raise BioEarError(f"unknown bioear extraction profile {profile!r}; expected one of {EXTRACTION_PROFILES}")
    return BIOEAR_PROFILE_CONFIGS[profile]


def profile_fiber_counts(profile: str) -> dict[str, int]:
    config = profile_config(profile)
    return {name: int(count) for name, _spont, count in config["fiber_types"]}


def profile_fiber_names(profile: str) -> tuple[str, ...]:
    config = profile_config(profile)
    return tuple(str(name) for name, _spont, _count in config["fiber_types"])


def profile_cf_count(profile: str) -> int:
    return int(profile_config(profile)["n_cf"])


def profile_from_cf_count(cf_count: int) -> str | None:
    for profile in EXTRACTION_PROFILES:
        if profile_cf_count(profile) == int(cf_count):
            return profile
    return None


def detect_homogeneous_sidecar_profile(root: str | Path, *, limit: int | None = None) -> dict[str, Any]:
    """Detect a numbered corpus BioEar profile from existing valid sidecars.

    This is intentionally CF-count driven so compact fast/balanced/context-lite
    files can be routed without depending on optional profile attributes.
    """
    pairs = find_pairs(Path(root), limit=limit)
    counts: dict[str, int] = {}
    invalid_count = 0
    missing_count = 0
    examples: list[dict[str, str]] = []
    for pair in pairs:
        if not pair.output.exists():
            missing_count += 1
            continue
        validation = validate_bioear_h5(pair.output)
        if not validation.get("ok", False):
            invalid_count += 1
            continue
        profile = str(validation.get("extraction_profile") or validation.get("bioear_mode") or "")
        if not profile and validation.get("cf_count"):
            profile = profile_from_cf_count(int(validation["cf_count"])) or ""
        if profile:
            counts[profile] = counts.get(profile, 0) + 1
            if len(examples) < 3:
                examples.append({"path": str(pair.output), "profile": profile, "cf_count": str(validation.get("cf_count", ""))})
    profiles = sorted(counts)
    return {
        "ok": len(profiles) == 1,
        "schema": "conphon.bioear.profile_detection.v1",
        "root": str(Path(root)),
        "profile": profiles[0] if len(profiles) == 1 else None,
        "profile_counts": counts,
        "valid_sidecar_count": sum(counts.values()),
        "missing_sidecar_count": missing_count,
        "invalid_sidecar_count": invalid_count,
        "examples": examples,
        "errors": [] if len(profiles) == 1 else ["no_valid_sidecars" if not profiles else f"mixed_profiles:{profiles}"],
    }


def constants_payload(
    *,
    profile: str = CANONICAL_EXTRACTION_PROFILE,
    n_cf: int | None = None,
    fiber_types: Sequence[tuple[str, float, int]] | None = None,
    power_law: str | None = None,
) -> dict[str, Any]:
    config = profile_config(profile)
    resolved_n_cf = int(n_cf if n_cf is not None else config["n_cf"])
    resolved_fiber_types = tuple(fiber_types if fiber_types is not None else config["fiber_types"])
    resolved_power_law = str(power_law if power_law is not None else config["power_law"])
    return {
        "source_fs_hz": SOURCE_FS,
        "model_fs_hz": MODEL_FS,
        "target_db_spl": TARGET_DB_SPL,
        "lead_silence_s": LEAD_SILENCE_S,
        "trail_silence_s": TRAIL_SILENCE_S,
        "n_cf": resolved_n_cf,
        "low_cf_hz": LOW_CF_HZ,
        "high_cf_hz": HIGH_CF_HZ_16K_SAFE,
        "bin_s": BIN_S,
        "fiber_types": [
            {"name": name, "spontaneous_rate_hz": spont, "fibers_per_cf": count}
            for name, spont, count in resolved_fiber_types
        ],
        "power_law": resolved_power_law,
        "profile": profile,
        "random_seed_base": RANDOM_SEED_BASE,
    }


def brucezilany_version() -> str | None:
    try:
        return importlib.metadata.version("brucezilany")
    except importlib.metadata.PackageNotFoundError:
        return None


def brucezilany_runtime_version() -> str | None:
    version = brucezilany_version()
    if version is not None:
        return version
    try:
        bz, _stimulus = import_brucezilany()
    except BioEarError:
        return None
    return getattr(bz, "__version__", None)


def import_brucezilany():
    try:
        import brucezilany as bz  # type: ignore[import-not-found]
        from brucezilany import stimulus  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise BioEarError(
            "the optimized brucezilany fastbioear backend is required for canonical BioEar extraction. "
            "Install the patched brucezilany==0.0.4+fastbioear build before extracting."
        ) from exc

    required = [
        "inner_hair_cell",
        "map_to_synapse",
        "synapse",
        "fast_rate_neurogram",
        "set_seed",
        "HUMAN_SHERA",
        "RANDOM",
        "APPROXIMATED",
        "ACTUAL",
        "SOFTPLUS",
    ]
    missing = [name for name in required if not hasattr(bz, name)]
    if missing:
        raise BioEarError(f"brucezilany import succeeded, but required symbols are missing: {missing}")
    if not hasattr(stimulus, "Stimulus"):
        raise BioEarError("brucezilany.stimulus.Stimulus is required but was not found.")
    version = brucezilany_version()
    if version != OFFICIAL_BRUCEZILANY_VERSION:
        raise BioEarError(
            f"brucezilany=={OFFICIAL_BRUCEZILANY_VERSION} is required for canonical optimized extraction; "
            f"found {version or 'unknown'}."
        )
    return bz, stimulus


def doctor_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "conphon.bioear.doctor.v1",
        "ok": False,
        "backend": "brucezilany",
        "runtime_backend_policy": "required_fastbioear_backend_only",
        "brucezilany_version": brucezilany_version(),
        "dependencies": {
            "h5py": importlib.metadata.version("h5py"),
            "soundfile": importlib.metadata.version("soundfile"),
            "textgrid_reader": _optional_version("TextGrid") or _optional_version("textgrid"),
            "scipy": importlib.metadata.version("scipy"),
        },
    }
    try:
        import_brucezilany()
    except BioEarError as exc:
        payload["error"] = str(exc)
        return payload
    payload["ok"] = True
    return payload


def _optional_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))) + 1e-30)


def dbspl_to_pa_rms(db_spl: float) -> float:
    return P_REF_PA * (10.0 ** (db_spl / 20.0))


def load_mono_16k_wav(path: Path) -> tuple[np.ndarray, int]:
    audio, fs = sf.read(str(path), always_2d=True, dtype="float64")
    if int(fs) != SOURCE_FS:
        raise BioEarError(f"bioear requires exactly 16 kHz WAV input; got {fs} Hz for {path}.")
    mono = audio.mean(axis=1).astype(np.float64)
    mono = mono - np.mean(mono)
    if mono.size == 0:
        raise BioEarError(f"input WAV contains no samples: {path}")
    if np.max(np.abs(mono)) < 1e-12:
        raise BioEarError(f"input WAV is silent or numerically zero: {path}")
    return mono, int(fs)


def calibrate_dimensionless_wav_to_pressure_pa(x: np.ndarray) -> np.ndarray:
    return (x / rms(x) * dbspl_to_pa_rms(TARGET_DB_SPL)).astype(np.float64)


def resample_16k_to_100k(x: np.ndarray) -> np.ndarray:
    return signal.resample_poly(x, up=25, down=4, window=("kaiser", 8.6)).astype(np.float64)


def pad_model_pressure(x_100k_pa: np.ndarray) -> np.ndarray:
    lead = int(round(LEAD_SILENCE_S * MODEL_FS))
    trail = int(round(TRAIL_SILENCE_S * MODEL_FS))
    return np.concatenate(
        [
            np.zeros(lead, dtype=np.float64),
            x_100k_pa.astype(np.float64),
            np.zeros(trail, dtype=np.float64),
        ]
    )


def greenwood_frequency_from_place(x: np.ndarray) -> np.ndarray:
    return 165.4 * ((10.0 ** (2.1 * x)) - 0.88)


def greenwood_place_from_frequency(f_hz: np.ndarray) -> np.ndarray:
    return np.log10((f_hz / 165.4) + 0.88) / 2.1


def greenwood_cf_space(n_cf: int = N_CF) -> np.ndarray:
    low_x = float(greenwood_place_from_frequency(np.asarray(LOW_CF_HZ)))
    high_x = float(greenwood_place_from_frequency(np.asarray(HIGH_CF_HZ_16K_SAFE)))
    places = np.linspace(low_x, high_x, int(n_cf))
    return greenwood_frequency_from_place(places).astype(np.float64)


def make_bz_stimulus(stimulus_module: Any, pressure_pa_100k_padded: np.ndarray) -> Any:
    duration_s = (pressure_pa_100k_padded.size + 1) / MODEL_FS
    return stimulus_module.Stimulus(pressure_pa_100k_padded.astype(float).tolist(), MODEL_FS, float(duration_s))


def ensure_len_1d(values: Iterable[float], n: int, dtype: Any = np.float32) -> np.ndarray:
    arr = np.asarray(list(values), dtype=dtype).reshape(-1)
    if arr.size == n:
        return arr
    if arr.size > n:
        return arr[:n]
    out = np.zeros(n, dtype=dtype)
    out[: arr.size] = arr
    return out


def normalize_spike_times_seconds(
    spike_times: Iterable[float],
    *,
    total_duration_s: float,
    n_samples: int,
    fs: int,
) -> np.ndarray:
    st = np.asarray(list(spike_times), dtype=np.float64).reshape(-1)
    if st.size == 0:
        return st.astype(np.float32)
    if np.max(st) > total_duration_s * 1.5 and np.max(st) <= n_samples + 1:
        st = st / float(fs)
    st = st[(st >= 0.0) & (st < total_duration_s)]
    return st.astype(np.float32)


def create_event_dtype() -> np.dtype:
    return np.dtype(
        [
            ("time_s", "<f4"),
            ("sample_index", "<u4"),
            ("cf_index", "<u2"),
            ("fiber_type", "u1"),
            ("fiber_index", "<u2"),
        ]
    )


def make_spike_event_records(
    spike_times_s: np.ndarray,
    *,
    cf_index: int,
    fiber_type_index: int,
    fiber_index: int,
    n_samples: int,
) -> np.ndarray:
    dtype = create_event_dtype()
    if spike_times_s.size == 0:
        return np.zeros(0, dtype=dtype)
    sample_index = np.minimum(
        np.floor(spike_times_s.astype(np.float64) * MODEL_FS).astype(np.uint32),
        np.uint32(n_samples - 1),
    )
    records = np.zeros(spike_times_s.size, dtype=dtype)
    records["time_s"] = spike_times_s.astype(np.float32)
    records["sample_index"] = sample_index
    records["cf_index"] = np.uint16(cf_index)
    records["fiber_type"] = np.uint8(fiber_type_index)
    records["fiber_index"] = np.uint16(fiber_index)
    return records


def make_spike_event_records_for_fibers(
    spike_times_s: np.ndarray,
    fiber_indices: np.ndarray,
    *,
    cf_index: int,
    fiber_type_index: int,
    n_samples: int,
) -> np.ndarray:
    dtype = create_event_dtype()
    if spike_times_s.size == 0:
        return np.zeros(0, dtype=dtype)
    sample_index = np.minimum(
        np.floor(spike_times_s.astype(np.float64) * MODEL_FS).astype(np.uint32),
        np.uint32(n_samples - 1),
    )
    records = np.zeros(spike_times_s.size, dtype=dtype)
    records["time_s"] = spike_times_s.astype(np.float32)
    records["sample_index"] = sample_index
    records["cf_index"] = np.uint16(cf_index)
    records["fiber_type"] = np.uint8(fiber_type_index)
    records["fiber_index"] = np.minimum(fiber_indices.astype(np.uint32), np.uint32(np.iinfo(np.uint16).max)).astype(np.uint16)
    return records


def ensure_repetition_time(values: Iterable[float], *, n_rep: int, n_samples: int, dtype: Any = np.float32) -> np.ndarray:
    arr = np.asarray(list(values), dtype=dtype).reshape(-1)
    target = int(n_rep) * int(n_samples)
    if arr.size == target:
        return arr.reshape(int(n_rep), int(n_samples))
    if arr.size == n_samples:
        return np.repeat(arr.reshape(1, int(n_samples)), int(n_rep), axis=0)
    out = np.zeros(target, dtype=dtype)
    out[: min(arr.size, target)] = arr[:target]
    return out.reshape(int(n_rep), int(n_samples))


def ensure_psth_counts(values: Iterable[float], *, n_rep: int, n_samples: int) -> np.ndarray:
    arr = np.asarray(list(values), dtype=np.float64).reshape(-1)
    target = int(n_rep) * int(n_samples)
    if arr.size == n_samples:
        return arr
    if arr.size == target:
        return arr.reshape(int(n_rep), int(n_samples)).sum(axis=0)
    out = np.zeros(int(n_samples), dtype=np.float64)
    out[: min(arr.size, int(n_samples))] = arr[: int(n_samples)]
    return out


def mean_samples_to_1ms(values: np.ndarray, *, n_frames: int) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float32).reshape(-1)
    samples_per_frame = int(round(MODEL_FS * BIN_S))
    full_frames = min(int(n_frames), arr.size // samples_per_frame)
    out = np.zeros(int(n_frames), dtype=np.float32)
    if full_frames:
        out[:full_frames] = np.mean(arr[: full_frames * samples_per_frame].reshape(full_frames, samples_per_frame), axis=1)
    if full_frames < int(n_frames):
        tail = arr[full_frames * samples_per_frame :]
        if tail.size:
            out[full_frames] = np.mean(tail, dtype=np.float64)
    return out


def sum_samples_to_1ms(values: np.ndarray, *, n_frames: int) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    samples_per_frame = int(round(MODEL_FS * BIN_S))
    full_frames = min(int(n_frames), arr.size // samples_per_frame)
    out = np.zeros(int(n_frames), dtype=np.float64)
    if full_frames:
        out[:full_frames] = np.sum(arr[: full_frames * samples_per_frame].reshape(full_frames, samples_per_frame), axis=1)
    if full_frames < int(n_frames):
        tail = arr[full_frames * samples_per_frame :]
        if tail.size:
            out[full_frames] = np.sum(tail, dtype=np.float64)
    return out


def normalize_repeated_spike_times_seconds(
    spike_times: Iterable[float],
    *,
    total_duration_s: float,
    n_samples: int,
    fs: int,
    n_rep: int,
) -> tuple[np.ndarray, np.ndarray]:
    raw = np.asarray(list(spike_times), dtype=np.float64).reshape(-1)
    if raw.size == 0:
        return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.uint16)
    max_value = float(np.max(raw))
    duration = max(float(total_duration_s), 1.0 / float(fs))
    if max_value > duration * 1.5 and max_value <= duration * float(n_rep) + duration * 0.5:
        rep = np.floor(raw / duration).astype(np.int64)
        times = raw - rep.astype(np.float64) * duration
    elif max_value > float(n_samples) * 1.5 and max_value <= float(n_samples * n_rep + 1):
        rep = np.floor(raw / float(n_samples)).astype(np.int64)
        times = (raw - rep.astype(np.float64) * float(n_samples)) / float(fs)
    elif max_value > duration * 1.5 and max_value <= float(n_samples * n_rep + 1):
        sample_index = np.floor(raw).astype(np.int64)
        rep = sample_index // int(n_samples)
        times = (sample_index % int(n_samples)).astype(np.float64) / float(fs)
    else:
        rep = np.zeros(raw.shape, dtype=np.int64)
        times = raw
    keep = (rep >= 0) & (rep < int(n_rep)) & (times >= 0.0) & (times < duration)
    return times[keep].astype(np.float32), rep[keep].astype(np.uint16)


def append_events(ds: h5py.Dataset, records: np.ndarray) -> None:
    if records.size == 0:
        return
    append_start = ds.shape[0]
    ds.resize((append_start + records.size,))
    ds[append_start : append_start + records.size] = records


def h5_create_compressed(
    group: h5py.Group,
    name: str,
    *,
    shape: tuple[int, ...],
    dtype: Any,
    chunks: tuple[int, ...] | None = None,
) -> h5py.Dataset:
    return group.create_dataset(
        name,
        shape=shape,
        dtype=dtype,
        chunks=chunks,
        compression="lzf",
        shuffle=True,
    )


def h5_write_fast(group: h5py.Group, name: str, data: np.ndarray, *, chunks: bool | tuple[int, ...] = True) -> h5py.Dataset:
    return group.create_dataset(name, data=data, chunks=chunks, compression="lzf", shuffle=True)


def entry_to_interval(entry: Any) -> Interval:
    if hasattr(entry, "start") and hasattr(entry, "end") and hasattr(entry, "label"):
        start = float(entry.start)
        end = float(entry.end)
        label = str(entry.label)
    else:
        start = float(entry[0])
        end = float(entry[1])
        label = str(entry[2])
    label = label.strip() or "<BLANK>"
    return Interval(start=start, end=end, label=label)


def read_textgrid_interval_tiers(textgrid_path: Path) -> tuple[list[tuple[str, list[Interval]]], list[str]]:
    try:
        from textgrid import TextGrid
    except ImportError as exc:
        raise BioEarError("A TextGrid reader is required to read alignment labels.") from exc

    tg = TextGrid.fromFile(str(textgrid_path))
    tier_names = [str(getattr(tier, "name", "")) for tier in getattr(tg, "tiers", [])]
    interval_tiers: list[tuple[str, list[Interval]]] = []
    for tier, name in zip(getattr(tg, "tiers", []), tier_names):
        raw_intervals = getattr(tier, "intervals", None)
        if raw_intervals is None:
            continue
        intervals: list[Interval] = []
        for entry in raw_intervals:
            start = float(getattr(entry, "minTime", getattr(entry, "start", 0.0)))
            end = float(getattr(entry, "maxTime", getattr(entry, "end", 0.0)))
            label = str(getattr(entry, "mark", getattr(entry, "label", ""))).strip() or "<BLANK>"
            if end > start and math.isfinite(start) and math.isfinite(end):
                intervals.append(Interval(start=start, end=end, label=label))
        if any(iv.label != "<BLANK>" for iv in intervals):
            interval_tiers.append((name, intervals))
    return interval_tiers, tier_names


def resolve_textgrid_tiers(textgrid_path: Path) -> tuple[dict[str, list[Interval]], dict[str, Any]]:
    interval_tiers, all_tier_names = read_textgrid_interval_tiers(textgrid_path)
    mandarin_resolved = _resolve_mandarin_three_tier_textgrid(textgrid_path, interval_tiers, all_tier_names)
    if mandarin_resolved is not None:
        return mandarin_resolved
    sentence_fallback_resolved = _resolve_three_tier_textgrid_with_sentence_fallback(
        textgrid_path,
        interval_tiers,
        all_tier_names,
    )
    if sentence_fallback_resolved is not None:
        return sentence_fallback_resolved
    if len(interval_tiers) < 4:
        raise BioEarError(
            "bioear requires four non-empty interval tiers by layer order, or three phone/word/syllable tiers so ALEX can synthesize one sentence interval from the word tier: "
            "ConPhonAligner Portuguese/English layer order is 1 phone, 2 word, 3 syllable, 4 sentence; three-tier fallback is 1 phone, 2 word, 3 syllable, sentence synthesized from words; "
            "Mandarin accepts exactly three non-empty interval tiers by layer order: "
            "1 hanzis->word and syllable, 2 pinyings->aggregate sentence, 3 phones->phone. "
            "language-specific named tiers are checked only after layer order. "
            f"Found {len(interval_tiers)} non-empty interval tier(s) in {textgrid_path}: "
            f"{[name for name, _ in interval_tiers]}"
        )

    selected: dict[str, tuple[str, list[Interval], int]] = {}
    name_resolved = _resolve_textgrid_tiers_by_known_names(interval_tiers)
    if name_resolved is not None:
        selected = name_resolved
        resolution_policy = "known_tier_name_primary"
        expected_layer_order = ["name-mapped: phone/phones, word/words, syllable/syllables, sentence/utterance(s)"]
    else:
        for order_index, level in enumerate(ORDER_LEVELS):
            name, intervals = interval_tiers[order_index]
            selected[level] = (name, intervals, order_index + 1)
        resolution_policy = "layer_order_primary_name_audit_secondary"
        expected_layer_order = ["phone", "word", "syllable", "sentence"]

    current_sentence_name = selected["sentence"][0].lower()
    if current_sentence_name in PHONETIC_SENTENCE_NAMES:
        for order_index, (name, intervals) in enumerate(interval_tiers[4:], start=5):
            if name.lower() in ORTHOGRAPHIC_SENTENCE_NAMES:
                selected["sentence"] = (name, intervals, order_index)
                break

    intervals_by_level = {level: selected[level][1] for level in LEVELS}
    selected_tiers = {
        level: {
            "name": selected[level][0],
            "layer_index_1_based": selected[level][2],
            "name_status": _tier_name_status(level, selected[level][0]),
            "non_empty_interval_count": sum(iv.label != "<BLANK>" for iv in selected[level][1]),
            "interval_count": len(selected[level][1]),
        }
        for level in LEVELS
    }
    resolution = {
        "policy": resolution_policy,
        "expected_layer_order": expected_layer_order,
        "english_tier_policy": "English TextGrids are name-mapped as words->word, phones->phone, utterances->sentence, syllables->syllable.",
        "sentence_policy": "if a phonetic sentence tier is selected and a later orthographic sentence tier exists, use the orthographic sentence tier",
        "all_tier_names": all_tier_names,
        "non_empty_interval_tiers": [
            {"layer_index_1_based": idx + 1, "name": name, "interval_count": len(intervals)}
            for idx, (name, intervals) in enumerate(interval_tiers)
        ],
        "selected_tiers": selected_tiers,
    }
    return intervals_by_level, resolution


def _resolve_three_tier_textgrid_with_sentence_fallback(
    textgrid_path: Path,
    interval_tiers: Sequence[tuple[str, list[Interval]]],
    all_tier_names: Sequence[str],
) -> tuple[dict[str, list[Interval]], dict[str, Any]] | None:
    if len(interval_tiers) != 3:
        return None

    selected = _resolve_three_tiers_by_known_names(interval_tiers)
    if selected is None:
        for order_index, level in enumerate(("phone", "word", "syllable")):
            name, intervals = interval_tiers[order_index]
            selected = selected or {}
            selected[level] = (name, intervals, order_index + 1, "three_tier_layer_order_trusted")
        resolution_policy = "three_tier_layer_order_sentence_from_word_tier"
        expected_layer_order = ["phone", "word", "syllable", "sentence synthesized from word tier"]
    else:
        resolution_policy = "three_tier_known_name_sentence_from_word_tier"
        expected_layer_order = ["name-mapped: phone/phones, word/words, syllable/syllables; sentence synthesized from word tier"]

    word_name, word_intervals, word_layer, _status = selected["word"]
    sentence_intervals = [_aggregate_intervals_as_sentence(word_intervals)]
    selected["sentence"] = (
        f"{word_name}:aggregate_sentence",
        sentence_intervals,
        word_layer,
        "synthetic_sentence_from_word_tier",
    )

    intervals_by_level = {level: selected[level][1] for level in LEVELS}
    selected_tiers = {
        level: {
            "name": selected[level][0],
            "layer_index_1_based": selected[level][2],
            "name_status": selected[level][3],
            "non_empty_interval_count": sum(iv.label != "<BLANK>" for iv in selected[level][1]),
            "interval_count": len(selected[level][1]),
        }
        for level in LEVELS
    }
    resolution = {
        "policy": resolution_policy,
        "expected_layer_order": expected_layer_order,
        "english_tier_policy": "English TextGrids are name-mapped as words->word, phones->phone, utterances->sentence, syllables->syllable; if sentence/utterance is absent, ALEX synthesizes one sentence from the word tier.",
        "sentence_policy": "sentence tier absent; ALEX synthesizes a single sentence interval spanning the word tier, including silences between words, with a label formed by joining nonblank word labels",
        "all_tier_names": list(all_tier_names),
        "non_empty_interval_tiers": [
            {"layer_index_1_based": idx + 1, "name": name, "interval_count": len(intervals)}
            for idx, (name, intervals) in enumerate(interval_tiers)
        ],
        "selected_tiers": selected_tiers,
    }
    return intervals_by_level, resolution


def _resolve_mandarin_three_tier_textgrid(
    textgrid_path: Path,
    interval_tiers: Sequence[tuple[str, list[Interval]]],
    all_tier_names: Sequence[str],
) -> tuple[dict[str, list[Interval]], dict[str, Any]] | None:
    if len(interval_tiers) != 3:
        return None
    normalized_names = [_normalize_tier_name(name) for name, _intervals in interval_tiers]
    names_match = (
        normalized_names[0] in MANDARIN_HANZI_TIER_NAMES
        and normalized_names[1] in MANDARIN_PINYIN_TIER_NAMES
        and normalized_names[2] in MANDARIN_PHONE_TIER_NAMES
    )
    path_declares_mandarin = "mandarin" in str(textgrid_path).lower() or "corpus_chinese" in str(textgrid_path).lower()
    if not (names_match or path_declares_mandarin):
        return None

    hanzi_name, hanzi_intervals = interval_tiers[0]
    pinyin_name, pinyin_intervals = interval_tiers[1]
    phone_name, phone_intervals = interval_tiers[2]
    sentence_intervals = [_aggregate_intervals_as_sentence(pinyin_intervals)]
    selected: dict[str, tuple[str, list[Interval], int, str]] = {
        "phone": (phone_name, phone_intervals, 3, "mandarin_layer_3_phones"),
        "syllable": (hanzi_name, hanzi_intervals, 1, "mandarin_layer_1_hanzi_internal_syllable"),
        "word": (hanzi_name, hanzi_intervals, 1, "mandarin_layer_1_hanzi_words"),
        "sentence": (f"{pinyin_name}:aggregate_sentence", sentence_intervals, 2, "mandarin_layer_2_pinyin_aggregate_sentence"),
    }
    intervals_by_level = {level: selected[level][1] for level in LEVELS}
    selected_tiers = {
        level: {
            "name": selected[level][0],
            "layer_index_1_based": selected[level][2],
            "name_status": selected[level][3],
            "non_empty_interval_count": sum(iv.label != "<BLANK>" for iv in selected[level][1]),
            "interval_count": len(selected[level][1]),
        }
        for level in LEVELS
    }
    resolution = {
        "policy": MANDARIN_THREE_TIER_POLICY,
        "expected_layer_order": [
            "Mandarin layer 1 hanzis -> word",
            "Mandarin layer 1 hanzis -> internal syllable intervals",
            "Mandarin layer 2 pinyings -> one aggregate sentence interval",
            "Mandarin layer 3 phones -> phone",
        ],
        "english_tier_policy": "English TextGrids are name-mapped as words->word, phones->phone, utterances->sentence, syllables->syllable.",
        "mandarin_tier_policy": "Mandarin TextGrids are layer-mapped as hanzis->word and internal syllable, pinyings->aggregate sentence, phones->phone.",
        "sentence_policy": "Mandarin sentence label is the whitespace-joined nonblank pinyin tier over the full pinyin time span.",
        "all_tier_names": list(all_tier_names),
        "non_empty_interval_tiers": [
            {"layer_index_1_based": idx + 1, "name": name, "interval_count": len(intervals)}
            for idx, (name, intervals) in enumerate(interval_tiers)
        ],
        "selected_tiers": selected_tiers,
    }
    return intervals_by_level, resolution


def _normalize_tier_name(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def _aggregate_intervals_as_sentence(intervals: Sequence[Interval]) -> Interval:
    source = list(intervals)
    if not source:
        return Interval(start=0.0, end=0.0, label="<BLANK>")
    nonempty = [iv for iv in intervals if iv.label != "<BLANK>"]
    start = min(iv.start for iv in source)
    end = max(iv.end for iv in source)
    labels = [iv.label.strip() for iv in nonempty if iv.label.strip()]
    return Interval(start=start, end=end, label=" ".join(labels) if labels else "<BLANK>")


def _resolve_textgrid_tiers_by_known_names(
    interval_tiers: Sequence[tuple[str, list[Interval]]],
) -> dict[str, tuple[str, list[Interval], int]] | None:
    selected: dict[str, tuple[str, list[Interval], int]] = {}
    ambiguous: set[str] = set()
    for order_index, (name, intervals) in enumerate(interval_tiers, start=1):
        lowered = name.lower().strip()
        matched = [level for level, names in KNOWN_TIER_NAMES.items() if lowered in names]
        if len(matched) != 1:
            continue
        level = matched[0]
        if level in selected:
            ambiguous.add(level)
            continue
        selected[level] = (name, intervals, order_index)
    if ambiguous:
        return None
    if all(level in selected for level in LEVELS):
        return selected
    return None


def _resolve_three_tiers_by_known_names(
    interval_tiers: Sequence[tuple[str, list[Interval]]],
) -> dict[str, tuple[str, list[Interval], int, str]] | None:
    selected: dict[str, tuple[str, list[Interval], int, str]] = {}
    for order_index, (name, intervals) in enumerate(interval_tiers, start=1):
        lowered = name.lower().strip()
        matched = [level for level in ("phone", "word", "syllable") if lowered in KNOWN_TIER_NAMES[level]]
        if len(matched) != 1:
            continue
        level = matched[0]
        if level in selected:
            return None
        selected[level] = (name, intervals, order_index, "known_textgrid_tier_name")
    if all(level in selected for level in ("phone", "word", "syllable")):
        return selected
    return None


def _tier_name_status(level: str, name: str) -> str:
    lowered = name.lower()
    if lowered in KNOWN_TIER_NAMES[level]:
        return "known_textgrid_tier_name"
    known_other = {item for other_level, names in KNOWN_TIER_NAMES.items() if other_level != level for item in names}
    if lowered in known_other:
        return "known_name_for_different_layer_order_trusted"
    return "unknown_name_layer_order_trusted"


def label_inventory(intervals: Sequence[Interval]) -> list[str]:
    labels = ["<PAD>", "<BLANK>"]
    seen = set(labels)
    for iv in intervals:
        label = iv.label.strip() or "<BLANK>"
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def frame_label_ids_for_intervals(
    intervals: Sequence[Interval],
    frame_original_time_s: np.ndarray,
    original_duration_s: float,
    inventory: Sequence[str],
) -> np.ndarray:
    label_to_id = {label: idx for idx, label in enumerate(inventory)}
    pad_id = label_to_id["<PAD>"]
    blank_id = label_to_id["<BLANK>"]
    ids = np.full(frame_original_time_s.shape[0], blank_id, dtype=np.int32)
    sorted_intervals = sorted(intervals, key=lambda iv: (iv.start, iv.end))
    j = 0
    for i, t in enumerate(frame_original_time_s):
        if t < 0.0 or t >= original_duration_s:
            ids[i] = pad_id
            continue
        while j < len(sorted_intervals) and sorted_intervals[j].end <= t:
            j += 1
        if j < len(sorted_intervals) and sorted_intervals[j].start <= t < sorted_intervals[j].end:
            ids[i] = label_to_id.get(sorted_intervals[j].label, blank_id)
        else:
            ids[i] = blank_id
    return ids


def find_enclosing_interval_index(intervals: Sequence[Interval], t: float) -> int:
    for idx, iv in enumerate(intervals):
        if iv.start <= t < iv.end:
            return idx
    return -1


def interval_table_dtype() -> np.dtype:
    return np.dtype(
        [
            ("start_s", "<f8"),
            ("end_s", "<f8"),
            ("start_model_s", "<f8"),
            ("end_model_s", "<f8"),
            ("start_frame", "<i4"),
            ("end_frame_exclusive", "<i4"),
            ("label_id", "<i4"),
            ("parent_phone", "<i4"),
            ("parent_syllable", "<i4"),
            ("parent_word", "<i4"),
            ("parent_sentence", "<i4"),
        ]
    )


def make_interval_table(
    level: str,
    intervals_by_level: dict[str, list[Interval]],
    inventories_by_level: dict[str, list[str]],
    n_frames: int,
) -> np.ndarray:
    intervals = intervals_by_level[level]
    label_to_id = {label: idx for idx, label in enumerate(inventories_by_level[level])}
    blank_id = label_to_id.get("<BLANK>", 1)
    out = np.zeros(len(intervals), dtype=interval_table_dtype())
    for idx, iv in enumerate(intervals):
        mid = 0.5 * (iv.start + iv.end)
        start_model = iv.start + LEAD_SILENCE_S
        end_model = iv.end + LEAD_SILENCE_S
        start_frame = int(np.clip(int(np.floor(start_model / BIN_S)), 0, n_frames))
        end_frame = int(np.clip(int(np.ceil(end_model / BIN_S)), 0, n_frames))
        out[idx]["start_s"] = iv.start
        out[idx]["end_s"] = iv.end
        out[idx]["start_model_s"] = start_model
        out[idx]["end_model_s"] = end_model
        out[idx]["start_frame"] = start_frame
        out[idx]["end_frame_exclusive"] = end_frame
        out[idx]["label_id"] = label_to_id.get(iv.label, blank_id)
        out[idx]["parent_phone"] = idx if level == "phone" else find_enclosing_interval_index(intervals_by_level["phone"], mid)
        out[idx]["parent_syllable"] = idx if level == "syllable" else find_enclosing_interval_index(intervals_by_level["syllable"], mid)
        out[idx]["parent_word"] = idx if level == "word" else find_enclosing_interval_index(intervals_by_level["word"], mid)
        out[idx]["parent_sentence"] = idx if level == "sentence" else find_enclosing_interval_index(intervals_by_level["sentence"], mid)
    return out


def write_textgrid_alignment(
    h5: h5py.File,
    *,
    textgrid_path: Path,
    original_duration_s: float,
    frame_original_time_s: np.ndarray,
    rate_neurogram_1ms: np.ndarray,
    spike_count_neurogram_1ms: np.ndarray,
) -> None:
    intervals_by_level, resolution = resolve_textgrid_tiers(textgrid_path)
    labels_group = h5.create_group("labels")
    labels_group.attrs["textgrid_path"] = str(textgrid_path.resolve())
    labels_group.attrs["note"] = "TextGrid labels are supervision/alignment only; they are never passed into brucezilany."
    labels_group.attrs["tier_resolution_json"] = json.dumps(resolution, ensure_ascii=False, sort_keys=True)

    inventories_by_level = {level: label_inventory(intervals_by_level[level]) for level in LEVELS}
    labels_group.attrs["label_inventories_json"] = json.dumps(inventories_by_level, ensure_ascii=False, sort_keys=True)

    n_frames = frame_original_time_s.shape[0]
    for level in LEVELS:
        ids = frame_label_ids_for_intervals(
            intervals_by_level[level],
            frame_original_time_s=frame_original_time_s,
            original_duration_s=original_duration_s,
            inventory=inventories_by_level[level],
        )
        labels_group.create_dataset(f"frame_{level}_id", data=ids, compression="gzip", shuffle=True)

    intervals_group = labels_group.create_group("intervals")
    summaries_group = labels_group.create_group("summaries")
    for level in LEVELS:
        table = make_interval_table(level, intervals_by_level, inventories_by_level, n_frames)
        ds = intervals_group.create_dataset(level, data=table, compression="gzip", shuffle=True)
        ds.attrs["labels_json"] = json.dumps(inventories_by_level[level], ensure_ascii=False)

        intervals = intervals_by_level[level]
        mean_rate = np.zeros(
            (len(intervals), rate_neurogram_1ms.shape[1], rate_neurogram_1ms.shape[2]),
            dtype=np.float32,
        )
        spike_counts = np.zeros(
            (len(intervals), spike_count_neurogram_1ms.shape[1], spike_count_neurogram_1ms.shape[2]),
            dtype=np.uint32,
        )
        for idx in range(len(intervals)):
            start_frame = int(table[idx]["start_frame"])
            end_frame = int(table[idx]["end_frame_exclusive"])
            if end_frame <= start_frame:
                continue
            mean_rate[idx] = np.mean(rate_neurogram_1ms[start_frame:end_frame], axis=0)
            spike_counts[idx] = np.sum(spike_count_neurogram_1ms[start_frame:end_frame], axis=0)
        level_group = summaries_group.create_group(level)
        h5_write_fast(level_group, "mean_rate_hz_per_fiber", mean_rate)
        h5_write_fast(level_group, "spike_counts", spike_counts)


def extract_biological_ear(
    wav_path: str | Path,
    textgrid_path: str | Path,
    out_path: str | Path | None = None,
    *,
    replace: bool = False,
    progress: bool = True,
    profile: str = CANONICAL_EXTRACTION_PROFILE,
    language_tag: str = "cust",
) -> dict[str, Any]:
    if profile not in EXTRACTION_PROFILES:
        raise BioEarError(f"unknown bioear extraction profile {profile!r}; expected one of {EXTRACTION_PROFILES}")
    normalized_language_tag = normalize_language_tag(language_tag)
    config = profile_config(profile)
    n_cf = int(config["n_cf"])
    fiber_types = tuple(config["fiber_types"])
    power_law_name = str(config["power_law"])
    wav = Path(wav_path)
    textgrid = Path(textgrid_path)
    out = Path(out_path) if out_path is not None else wav.with_name(f"{wav.stem}_bioear.h5")
    if out.exists() and not replace:
        validation = validate_bioear_h5(out)
        if validation["ok"]:
            if validation.get("extraction_profile") != profile:
                raise BioEarError(
                    f"Existing output {out} is {validation.get('extraction_profile')!r}, "
                    f"but this run requires homogeneous profile {profile!r}. Use --replace-confirmed to rebuild it."
                )
            return {"ok": True, "status": "skipped_existing_valid", "output": str(out), "validation": validation, "language_tag": normalized_language_tag}
        raise BioEarError(f"Existing output is invalid and --replace-confirmed was not used: {out}")
    if not textgrid.exists():
        raise BioEarError(f"TextGrid not found: {textgrid}")
    resolve_textgrid_tiers(textgrid)

    wav_dimless_16k, source_fs = load_mono_16k_wav(wav)
    wav_100k = resample_16k_to_100k(wav_dimless_16k)
    pressure_100k_pa = calibrate_dimensionless_wav_to_pressure_pa(wav_100k)
    pressure_100k_pa_padded = pad_model_pressure(pressure_100k_pa)

    bz, stimulus_module = import_brucezilany()

    original_duration_s = wav_dimless_16k.size / float(source_fs)
    model_duration_s = pressure_100k_pa_padded.size / float(MODEL_FS)

    cfs = greenwood_cf_space(n_cf)
    threads_per_file = max(1, int(os.environ.get(FAST_BIOEAR_THREADS_PER_FILE_ENV, "1")))
    stim = make_bz_stimulus(stimulus_module, pressure_100k_pa_padded)
    result = bz.fast_rate_neurogram(
        sound_wave=stim,
        cfs=cfs.astype(float).tolist(),
        spontaneous_rates=[float(spont) for _name, spont, _count in fiber_types],
        fibers_per_type=[int(count) for _name, _spont, count in fiber_types],
        bin_width=BIN_S,
        n_rep=1,
        species=bz.HUMAN_SHERA,
        noise_type=bz.RANDOM,
        power_law=getattr(bz, power_law_name),
        mapping_function=bz.SOFTPLUS,
        seed_base=RANDOM_SEED_BASE,
        save_ihc=False,
        save_synapse_drive=False,
        n_threads=threads_per_file,
    )
    spike_count_neurogram_1ms = np.asarray(result.spike_counts, dtype=np.uint32)
    rate_neurogram_1ms = np.asarray(result.rate_neurogram, dtype=np.float32)
    n_frames = int(rate_neurogram_1ms.shape[0])
    frame_model_time_s = (np.arange(n_frames, dtype=np.float64) + 0.5) * BIN_S
    frame_original_time_s = frame_model_time_s - LEAD_SILENCE_S

    tmp_out = out.with_name(out.name + ".tmp")
    if tmp_out.exists():
        tmp_out.unlink()

    wrote_tmp = False
    try:
        with h5py.File(tmp_out, "w") as h5:
            h5.attrs["schema"] = BIOEAR_SCHEMA
            h5.attrs["created_at_utc"] = utc_now()
            h5.attrs["backend_module"] = OFFICIAL_BACKEND_MODULE
            h5.attrs["backend_version"] = brucezilany_version() or getattr(bz, "__version__", "unknown")
            h5.attrs["extraction_profile"] = profile
            h5.attrs["language_tag"] = normalized_language_tag
            h5.attrs["language_tag_policy"] = "user supplied four-character corpus/language stem; extraction remains language-agnostic once TextGrid tiers are identified"
            h5.attrs["bioear_mode"] = profile
            h5.attrs["brucezilany_power_law"] = power_law_name
            h5.attrs["bioear_storage_profile"] = "compact_fast_rate_control_neurogram"
            h5.attrs["original_duration_s"] = float(original_duration_s)
            h5.attrs["model_duration_s"] = float(model_duration_s)
            h5.attrs["fast_result_n_samples"] = int(getattr(result, "n_samples", pressure_100k_pa_padded.size))
            h5.attrs["fast_threads_per_file"] = int(threads_per_file)
            h5.attrs["source_wav"] = str(wav.resolve())
            h5.attrs["source_textgrid"] = str(textgrid.resolve())
            h5.attrs["source_sample_rate_hz"] = SOURCE_FS
            h5.attrs["model_sample_rate_hz"] = MODEL_FS
            h5.attrs["target_db_spl"] = TARGET_DB_SPL
            h5.attrs["lead_silence_s"] = LEAD_SILENCE_S
            h5.attrs["trail_silence_s"] = TRAIL_SILENCE_S
            h5.attrs["bin_s"] = BIN_S
            h5.attrs["cf_low_hz"] = LOW_CF_HZ
            h5.attrs["cf_high_hz"] = HIGH_CF_HZ_16K_SAFE
            h5.attrs["n_cf"] = int(n_cf)
            h5.attrs["fibers_per_type_json"] = json.dumps({name: count for name, _spont, count in fiber_types}, sort_keys=True)
            h5.attrs["spontaneous_rates_hz_json"] = json.dumps({name: spont for name, spont, _count in fiber_types}, sort_keys=True)
            h5.attrs["power_law"] = power_law_name
            h5.attrs["extractor_constants_json"] = json.dumps(
                constants_payload(profile=profile, n_cf=n_cf, fiber_types=fiber_types, power_law=power_law_name),
                sort_keys=True,
            )
            h5.attrs["biological_order"] = "pressure_pa -> auditory periphery -> IHC -> synapse -> ANF spikes -> neurograms"
            h5.attrs["label_policy"] = "TextGrid labels are stored only under /labels and never passed into /periphery extraction."
            h5.attrs["fiber_batching"] = "brucezilany_fastbioear_cpp_per_fiber_seeded_batch"
            h5.attrs["compression_policy"] = "lossless_lzf_for_fast_large_corpus_extraction"
            h5.attrs["upstream_implementation_policy"] = (
                "Uses optimized jacobdenobel/brucezilany==0.0.4+fastbioear API: "
                f"fast_rate_neurogram with upstream PowerLaw.{power_law_name}, {n_cf} Greenwood CFs, "
                f"and {profile} HSR/MSR/LSR fiber counts. Compact rate-control mode stores the 1 ms "
                "ANF count/rate neurogram and labels; rich IHC/synapse/redocking arrays must be appended "
                "before certifying learner evidence."
            )

            periphery_group = h5.create_group("periphery")
            periphery_group.attrs["fiber_type_names_json"] = json.dumps([name for name, _, _ in fiber_types])
            periphery_group.attrs["fiber_type_spontaneous_rate_hz_json"] = json.dumps([spont for _, spont, _ in fiber_types])
            periphery_group.attrs["fibers_per_cf_by_type_json"] = json.dumps([count for _, _, count in fiber_types])
            periphery_group.attrs["rich_periphery_arrays"] = "absent_until_rich_bioear_auxiliary_append"
            periphery_group.attrs["rich_periphery_training_policy"] = "request_evidence_before_certifying_learner_training"
            periphery_group.create_dataset("characteristic_frequency_hz", data=cfs.astype(np.float32))
            h5_write_fast(periphery_group, "spike_count_neurogram_1ms", spike_count_neurogram_1ms)
            h5_write_fast(periphery_group, "rate_neurogram_1ms_hz_per_fiber", rate_neurogram_1ms)
            periphery_group.create_dataset("frame_model_time_s", data=frame_model_time_s.astype(np.float32))
            periphery_group.create_dataset("frame_original_time_s", data=frame_original_time_s.astype(np.float32))
            write_textgrid_alignment(
                h5,
                textgrid_path=textgrid,
                original_duration_s=original_duration_s,
                frame_original_time_s=frame_original_time_s,
                rate_neurogram_1ms=rate_neurogram_1ms,
                spike_count_neurogram_1ms=spike_count_neurogram_1ms,
            )
        wrote_tmp = True
    finally:
        if not wrote_tmp and tmp_out.exists():
            tmp_out.unlink()

    os.replace(tmp_out, out)
    validation = validate_bioear_h5(out)
    if not validation["ok"]:
        raise BioEarError(f"bioear wrote an invalid HDF5: {validation}")
    return {"ok": True, "status": "created", "output": str(out), "validation": validation, "profile": profile, "language_tag": normalized_language_tag}


def validate_bioear_h5(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "path": str(p), "error": "missing_file"}
    try:
        with h5py.File(p, "r") as h5:
            missing = [name for name in REQUIRED_DATASETS if name not in h5]
            top_level = sorted(h5.keys())
            errors: list[str] = []
            fast_optimized = _is_fast_bioear_h5(h5)
            extraction_profile, extraction_profile_source = _h5_extraction_profile_with_source(h5)
            profile_declared = extraction_profile_source.startswith("attr:")
            if extraction_profile not in EXTRACTION_PROFILES:
                errors.append(f"unsupported_extraction_profile:{extraction_profile or '<missing>'}")
            if h5.attrs.get("schema") != BIOEAR_SCHEMA and not fast_optimized:
                errors.append("schema_mismatch")
            backend_module = str(h5.attrs.get("backend_module", OFFICIAL_BACKEND_MODULE if fast_optimized else ""))
            if backend_module not in VALID_BACKEND_MODULES:
                errors.append(f"unsupported_backend:{backend_module}")
            if not {"labels", "periphery"}.issubset(set(top_level)) or any(name not in {"audio", "labels", "metadata", "periphery"} for name in top_level):
                errors.append(f"unexpected_top_level_groups:{top_level}")
            if missing:
                errors.append(f"missing_datasets:{missing}")
            label_leaks = _label_like_paths_inside_evidence_groups(h5)
            if label_leaks:
                errors.append(f"labels_inside_evidence_groups:{label_leaks[:10]}")
            frame_count = 0
            cf_count = 0
            fiber_type_count = 0
            frame_hop_s = None
            constants = _h5_constants_payload(h5)
            declared_cf_count = _h5_expected_cf_count(h5, constants)
            expected_cf_count = profile_cf_count(extraction_profile) if extraction_profile in EXTRACTION_PROFILES else declared_cf_count
            expected_fiber_type_count = len(profile_fiber_names(extraction_profile)) if extraction_profile in EXTRACTION_PROFILES else len(FIBER_TYPES)
            declared_fiber_counts = _h5_declared_fiber_counts(h5, constants)
            if extraction_profile in EXTRACTION_PROFILES:
                expected_fiber_counts = profile_fiber_counts(extraction_profile)
                if profile_declared and declared_cf_count != expected_cf_count:
                    errors.append(f"profile_cf_count_mismatch:{extraction_profile}:{declared_cf_count}!={expected_cf_count}")
                if profile_declared and declared_fiber_counts and declared_fiber_counts != expected_fiber_counts:
                    errors.append(f"profile_fiber_count_mismatch:{extraction_profile}:{declared_fiber_counts}!={expected_fiber_counts}")
                if not profile_declared:
                    declared_fiber_counts = expected_fiber_counts
            source_fs_hz = int(constants.get("source_fs_hz", SOURCE_FS))
            model_fs_hz = int(constants.get("model_fs_hz", MODEL_FS))
            if int(constants.get("source_fs_hz", SOURCE_FS)) != SOURCE_FS:
                errors.append("source_sample_rate_mismatch")
            if int(constants.get("model_fs_hz", MODEL_FS)) != MODEL_FS:
                errors.append("model_sample_rate_mismatch")
            if float(constants.get("bin_s", BIN_S)) != BIN_S:
                errors.append("bin_size_mismatch")
            if "periphery/characteristic_frequency_hz" in h5:
                cf = np.asarray(h5["periphery/characteristic_frequency_hz"], dtype=np.float64)
                cf_count = int(cf.size)
                if cf.shape != (expected_cf_count,):
                    errors.append("cf_shape_mismatch")
                if cf.size and not np.all(np.diff(cf) > 0.0):
                    errors.append("cf_not_strictly_increasing")
                if not np.all(np.isfinite(cf)):
                    errors.append("cf_contains_nonfinite")
            if "periphery/rate_neurogram_1ms_hz_per_fiber" in h5:
                rate = h5["periphery/rate_neurogram_1ms_hz_per_fiber"]
                if rate.ndim != 3 or rate.shape[1:] != (expected_cf_count, expected_fiber_type_count):
                    errors.append("rate_neurogram_shape_mismatch")
                frame_count = int(rate.shape[0]) if rate.ndim >= 1 else 0
                fiber_type_count = int(rate.shape[2]) if rate.ndim == 3 else 0
                if not _dataset_sample_is_finite(rate):
                    errors.append("rate_neurogram_contains_nonfinite")
            if "periphery/spike_count_neurogram_1ms" in h5:
                spike_count = h5["periphery/spike_count_neurogram_1ms"]
                if spike_count.ndim != 3 or spike_count.shape[1:] != (expected_cf_count, expected_fiber_type_count):
                    errors.append("spike_count_shape_mismatch")
                if "periphery/rate_neurogram_1ms_hz_per_fiber" in h5 and spike_count.shape != h5["periphery/rate_neurogram_1ms_hz_per_fiber"].shape:
                    errors.append("spike_count_rate_shape_mismatch")
                if not _dataset_sample_is_finite(spike_count):
                    errors.append("spike_count_contains_nonfinite")
            if "periphery/frame_model_time_s" in h5:
                frame_model_time_raw = np.asarray(h5["periphery/frame_model_time_s"])
                frame_model_time = frame_model_time_raw.astype(np.float64, copy=False)
                if frame_count and frame_model_time.shape != (frame_count,):
                    errors.append("frame_model_time_shape_mismatch")
                if frame_model_time.size > 1:
                    diffs = np.diff(frame_model_time)
                    frame_hop_s = float(np.median(diffs))
                    if not np.all(diffs > 0.0):
                        errors.append("frame_model_time_not_strictly_increasing")
                    frame_hop_atol_s = _frame_hop_atol_s(frame_model_time_raw)
                    if not _frame_time_grid_close_to_1ms(frame_model_time_raw):
                        errors.append("frame_hop_not_1ms")
                if not np.all(np.isfinite(frame_model_time)):
                    errors.append("frame_model_time_contains_nonfinite")
            if "periphery/frame_original_time_s" in h5:
                frame_original_time = np.asarray(h5["periphery/frame_original_time_s"], dtype=np.float64)
                if frame_count and frame_original_time.shape != (frame_count,):
                    errors.append("frame_original_time_shape_mismatch")
                if frame_original_time.size > 1 and not np.all(np.diff(frame_original_time) > 0.0):
                    errors.append("frame_original_time_not_strictly_increasing")
                if not np.all(np.isfinite(frame_original_time)):
                    errors.append("frame_original_time_contains_nonfinite")
            for name in (
                "periphery/ihc_receptor_potential_1ms",
                "periphery/synapse_drive_1ms",
                "periphery/synaptic_output_mean",
                "periphery/redocking_time_1ms",
                "periphery/psth_rate_highres_hz_per_fiber",
            ):
                if name in h5 and not _dataset_sample_is_finite(h5[name]):
                    errors.append(f"nonfinite_dataset:{name}")
            if "periphery/spike_count_neurogram_1ms" in h5 and "labels/frame_phone_id" in h5:
                n_frames = h5["periphery/spike_count_neurogram_1ms"].shape[0]
                for level in LEVELS:
                    if h5[f"labels/frame_{level}_id"].shape[0] != n_frames:
                        errors.append(f"frame_label_length_mismatch:{level}")
            interval_counts = _h5_interval_counts(h5) if not missing else {}
            return {
                "ok": not errors,
                "path": str(p),
                "schema": h5.attrs.get("schema"),
                "backend_module": backend_module,
                "extraction_profile": extraction_profile,
                "bioear_mode": extraction_profile,
                "extraction_profile_source": extraction_profile_source,
                "errors": errors,
                "frame_count": frame_count,
                "cf_count": cf_count,
                "fiber_type_count": fiber_type_count,
                "declared_cf_count": declared_cf_count,
                "expected_cf_count": expected_cf_count,
                "fibers_per_type": declared_fiber_counts,
                "frame_hop_s": frame_hop_s,
                "frame_hop_tolerance_s": _frame_hop_atol_s(frame_model_time_raw) if "frame_model_time_raw" in locals() and frame_model_time_raw.size > 1 else None,
                "source_fs_hz": source_fs_hz,
                "model_fs_hz": model_fs_hz,
                "interval_counts": interval_counts,
            }
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "path": str(p), "error": str(exc)}


def _frame_hop_atol_s(frame_model_time: np.ndarray) -> float:
    """Tolerance for stored frame timestamps, not for the frame grid itself.

    Frame identity is index-based and the target hop is exactly 1 ms. Older
    balanced files store ``frame_model_time_s`` as float32; once timestamps pass
    roughly 16 s, adjacent representable float32 values can make an exact 1 ms
    grid appear to jitter by a little over 1 microsecond. Accept that storage
    quantization while still rejecting real hop mistakes such as 2 ms frames.
    """
    if frame_model_time.size == 0:
        return FRAME_HOP_BASE_ATOL_S
    if np.issubdtype(frame_model_time.dtype, np.floating) and frame_model_time.dtype.itemsize <= np.dtype(np.float32).itemsize:
        max_abs_time = float(np.nanmax(np.abs(frame_model_time.astype(np.float64)))) if frame_model_time.size else BIN_S
        spacing = float(np.spacing(np.float32(max(max_abs_time, BIN_S))))
        return max(FRAME_HOP_BASE_ATOL_S, min(FRAME_HOP_FLOAT32_MAX_ATOL_S, 2.0 * spacing))
    return FRAME_HOP_BASE_ATOL_S


def _frame_time_grid_close_to_1ms(frame_model_time: np.ndarray) -> bool:
    raw = np.asarray(frame_model_time)
    if raw.size <= 1:
        return True
    values = raw.astype(np.float64, copy=False)
    expected = values[0] + np.arange(values.size, dtype=np.float64) * BIN_S
    return bool(np.allclose(values, expected, rtol=0.0, atol=_frame_hop_atol_s(raw)))


def _h5_constants_payload(h5: h5py.File) -> dict[str, Any]:
    raw = h5.attrs.get("extractor_constants_json")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                return _normalize_h5_constants_payload(payload)
        except json.JSONDecodeError:
            pass
    return _normalize_h5_constants_payload({
        "source_fs_hz": int(h5.attrs.get("source_sample_rate_hz", h5.attrs.get("source_fs_hz", SOURCE_FS))),
        "model_fs_hz": int(h5.attrs.get("model_sample_rate_hz", h5.attrs.get("model_fs_hz", MODEL_FS))),
        "target_db_spl": float(h5.attrs.get("target_db_spl", TARGET_DB_SPL)),
        "lead_silence_s": float(h5.attrs.get("lead_silence_s", LEAD_SILENCE_S)),
        "trail_silence_s": float(h5.attrs.get("trail_silence_s", TRAIL_SILENCE_S)),
        "n_cf": int(h5.attrs.get("n_cf", N_CF)),
        "low_cf_hz": float(h5.attrs.get("cf_low_hz", LOW_CF_HZ)),
        "high_cf_hz": float(h5.attrs.get("cf_high_hz", HIGH_CF_HZ_16K_SAFE)),
        "bin_s": float(h5.attrs.get("bin_s", BIN_S)),
        "fiber_types": [
            {"name": name, "spontaneous_rate_hz": spont, "fibers_per_cf": count}
            for name, spont, count in FIBER_TYPES
        ],
        "random_seed_base": RANDOM_SEED_BASE,
    })


def _normalize_h5_constants_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if "source_fs_hz" not in out and "source_sample_rate_hz" in out:
        out["source_fs_hz"] = out["source_sample_rate_hz"]
    if "model_fs_hz" not in out and "model_sample_rate_hz" in out:
        out["model_fs_hz"] = out["model_sample_rate_hz"]
    if "low_cf_hz" not in out and "cf_low_hz" in out:
        out["low_cf_hz"] = out["cf_low_hz"]
    if "high_cf_hz" not in out and "cf_high_hz" in out:
        out["high_cf_hz"] = out["cf_high_hz"]
    return out


def _h5_extraction_profile(h5: h5py.File) -> str:
    return _h5_extraction_profile_with_source(h5)[0]


def _h5_extraction_profile_with_source(h5: h5py.File) -> tuple[str, str]:
    for attr in ("extraction_profile", "bioear_mode"):
        value = str(h5.attrs.get(attr, ""))
        if value in EXTRACTION_PROFILES:
            return value, f"attr:{attr}"
    if "periphery/characteristic_frequency_hz" in h5:
        inferred = profile_from_cf_count(int(h5["periphery/characteristic_frequency_hz"].shape[0]))
        if inferred is not None:
            return inferred, "cf_count"
    for attr in ("n_cf", "cf_count"):
        try:
            inferred = profile_from_cf_count(int(h5.attrs.get(attr)))
        except (TypeError, ValueError):
            inferred = None
        if inferred is not None:
            return inferred, f"attr:{attr}"
    constants = _h5_constants_payload(h5)
    try:
        inferred = profile_from_cf_count(int(constants.get("n_cf")))
    except (TypeError, ValueError):
        inferred = None
    if inferred is not None:
        return inferred, "constants:n_cf"
    return "", "missing"


def _h5_declared_fiber_counts(h5: h5py.File, constants: dict[str, Any]) -> dict[str, int]:
    attr_payload = _json_attr(h5, "fibers_per_type_json")
    if isinstance(attr_payload, dict):
        out = _int_dict(attr_payload)
        if out:
            return out
    const_payload = constants.get("fibers_per_type")
    if isinstance(const_payload, dict):
        out = _int_dict(const_payload)
        if out:
            return out
    fiber_types = constants.get("fiber_types")
    if isinstance(fiber_types, list):
        out: dict[str, int] = {}
        for item in fiber_types:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if not name:
                continue
            try:
                out[name] = int(item.get("fibers_per_cf"))
            except (TypeError, ValueError):
                continue
        if out:
            return out
    return {}


def _json_attr(h5: h5py.File, name: str) -> Any:
    raw = h5.attrs.get(name)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw


def _int_dict(values: dict[Any, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in values.items():
        try:
            out[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _is_fast_bioear_h5(h5: h5py.File) -> bool:
    extractor = str(h5.attrs.get("extractor", ""))
    profile = _h5_extraction_profile(h5)
    return extractor == "fast_bioear_batch.py" or profile in set(EXTRACTION_PROFILES)


def _h5_expected_cf_count(h5: h5py.File, constants: dict[str, Any]) -> int:
    if "n_cf" in constants:
        return int(constants["n_cf"])
    if "n_cf" in h5.attrs:
        return int(h5.attrs["n_cf"])
    if "periphery/characteristic_frequency_hz" in h5:
        return int(h5["periphery/characteristic_frequency_hz"].shape[0])
    return N_CF


def _label_like_paths_inside_evidence_groups(h5: h5py.File) -> list[str]:
    forbidden = {"label", "labels", "phone", "phoneme", "syllable", "word", "sentence", "textgrid"}
    found: list[str] = []
    for root_name in ("audio", "periphery"):
        if root_name not in h5:
            continue
        root = h5[root_name]

        def visitor(name: str, obj: h5py.Dataset | h5py.Group) -> None:
            parts = {part.lower() for part in Path(name).parts}
            if any(token in part for part in parts for token in forbidden):
                found.append(f"{root_name}/{name}")
            for attr_name in obj.attrs.keys():
                attr = str(attr_name).lower()
                if any(token in attr for token in forbidden):
                    found.append(f"{root_name}/{name}@{attr_name}")

        root.visititems(visitor)
    return found


def _dataset_sample_is_finite(dataset: h5py.Dataset, *, sample_size: int = 2048) -> bool:
    if dataset.size == 0:
        return True
    try:
        if dataset.size <= sample_size:
            values = np.asarray(dataset[...])
        else:
            head = _dataset_edge_sample(dataset, first=True, sample_size=sample_size // 2)
            tail = _dataset_edge_sample(dataset, first=False, sample_size=sample_size // 2)
            values = np.concatenate([np.ravel(head), np.ravel(tail)])
        if values.dtype.fields:
            return True
        return bool(np.all(np.isfinite(values)))
    except (OSError, TypeError, ValueError):
        return False


_BIOEAR_REPORTED_FAILURES = (
    BioEarError,
    BrokenExecutor,
    ImportError,
    OSError,
    RuntimeError,
    KeyError,
    TypeError,
    ValueError,
    json.JSONDecodeError,
)


def _dataset_edge_sample(dataset: h5py.Dataset, *, first: bool, sample_size: int) -> np.ndarray:
    shape = tuple(int(dim) for dim in dataset.shape)
    if not shape:
        return np.asarray(dataset[()])
    slices: list[slice] = []
    remaining = max(1, int(sample_size))
    for axis, dim in enumerate(shape):
        if dim <= 0:
            slices.append(slice(0, 0))
            continue
        if axis == len(shape) - 1:
            take = min(dim, remaining)
        else:
            take = min(dim, max(1, int(round(remaining ** (1.0 / max(len(shape) - axis, 1))))))
            remaining = max(1, remaining // max(take, 1))
        if first:
            slices.append(slice(0, take))
        else:
            slices.append(slice(max(dim - take, 0), dim))
    return np.asarray(dataset[tuple(slices)])


def _h5_interval_counts(h5: h5py.File) -> dict[str, int]:
    out: dict[str, int] = {}
    for level in LEVELS:
        name = f"labels/intervals/{level}"
        if name in h5:
            out[level] = int(h5[name].shape[0])
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _bioear_pair_sort_key(pair: BioEarPair) -> tuple[int, int, str, str]:
    return (
        0 if pair.number is not None else 1,
        int(pair.number) if pair.number is not None else 0,
        str(pair.wav.parent),
        pair.wav.name,
    )


def _pairs_from_files(files: Iterable[Path]) -> list[BioEarPair]:
    by_key: dict[tuple[str, str], dict[str, Path]] = {}
    for path in files:
        suffix = path.suffix.lower()
        if suffix not in {".wav", ".txt", ".textgrid"}:
            continue
        stem = path.stem
        if stem.endswith("_bioear"):
            continue
        key = (str(path.parent.resolve()), stem)
        slot = by_key.setdefault(key, {})
        if suffix == ".textgrid":
            slot["textgrid"] = path
        else:
            slot[suffix.lstrip(".")] = path
    pairs: list[BioEarPair] = []
    for (_folder, stem), slot in sorted(by_key.items()):
        wav = slot.get("wav")
        textgrid = slot.get("textgrid")
        if wav is None or textgrid is None:
            continue
        number = int(wav.parent.name) if wav.parent.name.isdigit() else None
        pairs.append(BioEarPair(wav=wav, textgrid=textgrid, txt=slot.get("txt"), output=wav.with_name(f"{stem}_bioear.h5"), number=number))
    return sorted(pairs, key=_bioear_pair_sort_key)


def _numeric_child_dirs(root: Path) -> list[Path]:
    return sorted((path for path in root.iterdir() if path.is_dir() and path.name.isdigit()), key=lambda path: int(path.name))


def find_pairs(
    root: Path,
    *,
    start: int | None = None,
    end: int | None = None,
    limit: int | None = None,
) -> list[BioEarPair]:
    pairs: list[BioEarPair] = []
    numeric_dirs = _numeric_child_dirs(root)
    if numeric_dirs:
        max_pairs = None if limit is None else max(0, int(limit))
        for folder in numeric_dirs:
            number = int(folder.name)
            if start is not None and number < start:
                continue
            if end is not None and number > end:
                continue
            pairs.extend(_pairs_from_files(path for path in folder.iterdir() if path.is_file()))
            if max_pairs is not None and len(pairs) >= max_pairs:
                return pairs[:max_pairs]
        return pairs

    files = [p for p in root.rglob("*") if p.is_file() and not _is_skipped_path(p)]
    pairs = _pairs_from_files(files)
    return _select_pairs(pairs, start=start, end=end, limit=limit)


def _is_skipped_path(path: Path) -> bool:
    skipped = {"data", "results", ".build", "dist", "__pycache__"}
    return any(part in skipped for part in path.parts)


def normalize_language_tag(raw: str | None) -> str:
    text = "".join(ch for ch in str(raw or "cust").lower() if ch.isalnum())
    if not text:
        text = "cust"
    return (text[:4]).ljust(4, "_")


def _extract_pair_worker(payload: tuple[str, str, str, bool, str, str]) -> dict[str, Any]:
    wav, textgrid, output, replace, profile, language_tag = payload
    try:
        result = extract_biological_ear(
            Path(wav),
            Path(textgrid),
            Path(output),
            replace=replace,
            progress=False,
            profile=profile,
            language_tag=language_tag,
        )
        return {"ok": True, "output": output, "status": result.get("status"), "profile": result.get("profile", profile), "language_tag": result.get("language_tag", language_tag)}
    except _BIOEAR_REPORTED_FAILURES as exc:
        return {
            "ok": False,
            "wav": wav,
            "textgrid": textgrid,
            "output": output,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=8),
        }


def run_folder(
    root: Path,
    *,
    replace: bool = False,
    limit: int | None = None,
    start: int | None = None,
    end: int | None = None,
    progress: bool = True,
    profile: str = CANONICAL_EXTRACTION_PROFILE,
    jobs: int = 1,
    language_tag: str = "cust",
) -> dict[str, Any]:
    if profile not in EXTRACTION_PROFILES:
        raise BioEarError(f"unknown bioear extraction profile {profile!r}; expected one of {EXTRACTION_PROFILES}")
    clear_graceful_stop()
    pairs = find_pairs(root, start=start, end=end, limit=limit)
    pair_count = len(pairs)
    created = 0
    skipped = 0
    failures: list[dict[str, Any]] = []
    outputs: list[str] = []
    completed = 0
    interrupted = False
    jobs = max(1, int(jobs))

    scheduled_pairs: list[BioEarPair] = []
    if replace:
        scheduled_pairs = pairs
    else:
        for pair in pairs:
            if pair.output.exists():
                validation = validate_bioear_h5(pair.output)
                if validation.get("ok") and validation.get("extraction_profile") == profile:
                    skipped += 1
                    outputs.append(str(pair.output))
                    continue
            scheduled_pairs.append(pair)
    prefiltered_skipped = skipped
    if progress and prefiltered_skipped:
        print(
            f"[bioear] prefiltered {prefiltered_skipped}/{pair_count} existing valid outputs; "
            f"scheduling {len(scheduled_pairs)} pending profile={profile}",
            file=sys.stderr,
            flush=True,
        )

    def record_result(pair: BioEarPair, payload: dict[str, Any]) -> None:
        nonlocal created, skipped
        if payload.get("ok"):
            if payload.get("status") == "created":
                created += 1
            else:
                skipped += 1
            outputs.append(str(pair.output))
        else:
            failures.append(
                {
                    "wav": str(pair.wav),
                    "textgrid": str(pair.textgrid),
                    "output": str(pair.output),
                    "error": str(payload.get("error", "unknown extraction failure")),
                }
            )

    if jobs == 1 or len(scheduled_pairs) <= 1:
        for index, pair in enumerate(scheduled_pairs, start=1):
            if graceful_stop_requested():
                interrupted = True
                break
            if progress and (index == 1 or index % 250 == 0 or index == len(scheduled_pairs)):
                print(
                    f"[bioear] extracting {index}/{len(scheduled_pairs)} pending "
                    f"profile={profile} skipped_existing={skipped}",
                    file=sys.stderr,
                    flush=True,
                )
            try:
                payload = extract_biological_ear(pair.wav, pair.textgrid, pair.output, replace=replace, progress=progress, profile=profile, language_tag=language_tag)
            except KeyboardInterrupt:
                request_graceful_stop()
                interrupted = True
                print("[bioear] graceful stop requested; finishing current file before stopping submissions.", file=sys.stderr, flush=True)
                break
            except _BIOEAR_REPORTED_FAILURES as exc:
                payload = {"ok": False, "error": str(exc)}
            record_result(pair, payload)
            completed += 1
    else:
        with ProcessPoolExecutor(max_workers=jobs) as executor:
            pair_iter = iter(scheduled_pairs)
            future_to_pair: dict[Future[dict[str, Any]], BioEarPair] = {}

            def submit_until_full() -> None:
                if graceful_stop_requested():
                    return
                while len(future_to_pair) < jobs:
                    try:
                        next_pair = next(pair_iter)
                    except StopIteration:
                        return
                    task = (str(next_pair.wav), str(next_pair.textgrid), str(next_pair.output), replace, profile, language_tag)
                    future_to_pair[executor.submit(_extract_pair_worker, task)] = next_pair

            submit_until_full()
            while future_to_pair:
                try:
                    done, _pending = wait(future_to_pair, timeout=0.5, return_when=FIRST_COMPLETED)
                except KeyboardInterrupt:
                    request_graceful_stop()
                    interrupted = True
                    print("[bioear] graceful stop requested; waiting for active worker files to finish.", file=sys.stderr, flush=True)
                    continue
                if not done:
                    continue
                for future in done:
                    pair = future_to_pair.pop(future)
                    try:
                        payload = future.result()
                    except _BIOEAR_REPORTED_FAILURES as exc:
                        payload = {"ok": False, "error": str(exc)}
                    record_result(pair, payload)
                    completed += 1
                    if progress and (completed == 1 or completed % 250 == 0 or completed == len(scheduled_pairs) or graceful_stop_requested()):
                        print(
                            f"[bioear] completed {completed}/{len(scheduled_pairs)} pending "
                            f"created={created} skipped={skipped} failures={len(failures)} jobs={jobs} profile={profile}",
                            file=sys.stderr,
                            flush=True,
                        )
                if graceful_stop_requested():
                    interrupted = True
                    continue
                submit_until_full()
    output_sample = outputs[:1000]
    return {
        "schema": "conphon.bioear.extract_summary.v1",
        "ok": not failures and not interrupted,
        "root": str(root),
        "pair_count": pair_count,
        "scheduled_count": len(scheduled_pairs),
        "prefiltered_skip_count": prefiltered_skipped,
        "profile": profile,
        "language_tag": normalize_language_tag(language_tag),
        "jobs": jobs,
        "completed_count": completed + prefiltered_skipped,
        "created_count": created,
        "skipped_valid_count": skipped,
        "failure_count": len(failures),
        "interrupted": interrupted or graceful_stop_requested(),
        "pending_after_interrupt": max(0, len(scheduled_pairs) - completed) if (interrupted or graceful_stop_requested()) else 0,
        "failures": failures,
        "outputs": output_sample,
        "outputs_truncated": len(outputs) > len(output_sample),
    }


def _clonefile_copy(source: Path, dest: Path) -> None:
    import ctypes
    import ctypes.util

    libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
    clonefile = libc.clonefile
    clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    clonefile.restype = ctypes.c_int
    rc = clonefile(os.fsencode(str(source)), os.fsencode(str(dest)), 0)
    if rc != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), str(dest))
    shutil.copystat(source, dest, follow_symlinks=True)


def _relative_symlink(source: Path, dest: Path) -> None:
    target = os.path.relpath(source.resolve(), start=dest.parent.resolve())
    dest.symlink_to(target)


def _canonical_record_symlink_matches(source: Path, dest: Path) -> bool:
    return dest.is_symlink() and dest.resolve(strict=False) == source.resolve(strict=False)


def _install_canonical_record_file(source: Path, dest: Path, *, copy_mode: str) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_name(dest.name + ".tmp")
    if tmp_dest.exists() or tmp_dest.is_symlink():
        tmp_dest.unlink()
    installed = False
    try:
        if copy_mode == "symlink":
            _relative_symlink(source, tmp_dest)
            method = "symlink"
        elif copy_mode in {"auto", "clone"}:
            try:
                _clonefile_copy(source, tmp_dest)
                method = "clonefile"
            except (OSError, RuntimeError, AttributeError):
                if copy_mode == "clone":
                    raise
                shutil.copy2(source, tmp_dest)
                method = "copy2"
        else:
            shutil.copy2(source, tmp_dest)
            method = "copy2"
        os.replace(tmp_dest, dest)
        installed = True
        return method
    finally:
        if not installed and (tmp_dest.exists() or tmp_dest.is_symlink()):
            tmp_dest.unlink()


def _build_canonical_record_task(task: tuple[int, str, str, str | None, str, str, int, str, str, bool, str, bool]) -> dict[str, Any]:
    (
        order_index,
        wav_s,
        textgrid_s,
        txt_s,
        sidecar_s,
        dest_s,
        number,
        record_id,
        profile,
        replace,
        copy_mode,
        progress,
    ) = task
    wav = Path(wav_s)
    textgrid = Path(textgrid_s)
    txt = Path(txt_s) if txt_s else None
    sidecar = Path(sidecar_s)
    dest = Path(dest_s)
    try:
        joined_paths = " ".join(str(path).lower() for path in (wav, textgrid, sidecar, dest))
        textgrid_native_scope = any(token in joined_paths for token in ("mandarin", "corpus_mandarin", "english", "corpus_english"))
        if not textgrid_native_scope and (txt is None or not txt.exists()):
            raise BioEarError(f"canonical BioEar record {record_id} requires source TXT provenance beside the measured WAV/TextGrid pair")
        sidecar_validation = validate_bioear_h5(sidecar)
        if sidecar_validation.get("ok") and sidecar_validation.get("extraction_profile") != profile:
            sidecar_validation = {"ok": False, "error": f"sidecar_profile_mismatch:{sidecar_validation.get('extraction_profile')}!={profile}"}
        if not sidecar_validation["ok"]:
            extract_biological_ear(wav, textgrid, sidecar, replace=True, progress=progress, profile=profile)
            sidecar_validation = validate_bioear_h5(sidecar)
            if not sidecar_validation["ok"]:
                raise BioEarError(f"sidecar HDF5 validation failed after extraction: {sidecar}: {sidecar_validation}")
        copy_method = "existing"
        validation: dict[str, Any]
        needs_install = replace or not dest.exists()
        if dest.exists() and not replace:
            validation = validate_bioear_h5(dest)
            if not validation["ok"]:
                needs_install = True
                copy_method = "repaired_invalid"
            elif validation.get("extraction_profile") != profile:
                needs_install = True
                copy_method = "repaired_profile_mismatch"
            elif copy_mode == "symlink":
                if _canonical_record_symlink_matches(sidecar, dest):
                    copy_method = "symlink"
                else:
                    needs_install = True
                    copy_method = "repaired_link_standard"
        if needs_install:
            repair_prefix = copy_method if copy_method.startswith("repaired_") else ""
            copy_method = _install_canonical_record_file(sidecar, dest, copy_mode=copy_mode)
            if repair_prefix:
                copy_method = f"{repair_prefix}:{copy_method}"
            if dest.stat().st_size != sidecar.stat().st_size:
                raise BioEarError(f"canonical HDF5 size mismatch after install: {sidecar} -> {dest}")
            validation = validate_bioear_h5(dest)
            if not validation["ok"]:
                raise BioEarError(f"canonical HDF5 validation failed after install: {dest}: {validation}")
        if validation.get("extraction_profile") != profile:
            raise BioEarError(
                f"canonical HDF5 profile mismatch: {validation.get('extraction_profile')!r} != {profile!r}: {dest}"
            )
        h5_summary, interval_index_rows = _bioear_h5_summary_and_interval_index_rows(dest, record_id=record_id, number=int(number))
        sidecar_h5_sha256 = sha256_file(sidecar)
        canonical_h5_sha256 = sidecar_h5_sha256 if copy_method != "existing" else sha256_file(dest)
        txt_sha256 = sha256_file(txt) if txt is not None else None
        hashes = {
            "wav_sha256": sha256_file(wav),
            "txt_sha256": txt_sha256,
            "textgrid_sha256": sha256_file(textgrid),
            "sidecar_h5_sha256": sidecar_h5_sha256,
            "canonical_h5_sha256": canonical_h5_sha256,
            "hdf5_sha256": canonical_h5_sha256,
        }
        record = {
            "record_id": record_id,
            "number": number,
            "source_wav": str(wav),
            "source_txt": str(txt) if txt is not None else None,
            "source_textgrid": str(textgrid),
            "sidecar_h5": str(sidecar),
            "canonical_h5": str(dest),
            "hashes": hashes,
            "validation": validation,
            "summary": h5_summary,
            "canonical_copy_method": copy_method,
        }
        record_index_row = {
            "record_id": record_id,
            "number": int(number),
            "canonical_h5": str(dest),
            "source_wav": str(wav),
            "source_txt": str(txt) if txt is not None else None,
            "source_textgrid": str(textgrid),
            "wav_sha256": hashes["wav_sha256"],
            "txt_sha256": hashes["txt_sha256"],
            "textgrid_sha256": hashes["textgrid_sha256"],
            "hdf5_sha256": hashes["hdf5_sha256"],
            "validation_ok": bool(validation["ok"]),
            "extraction_profile": str(validation.get("extraction_profile", profile)),
            "bioear_mode": str(validation.get("bioear_mode", validation.get("extraction_profile", profile))),
            "frame_count": int(validation.get("frame_count", 0) or 0),
            "cf_count": int(validation.get("cf_count", 0) or 0),
            "fiber_type_count": int(validation.get("fiber_type_count", 0) or 0),
            "fibers_per_type_json": json.dumps(validation.get("fibers_per_type", {}), sort_keys=True),
            "source_fs_hz": int(validation.get("source_fs_hz", SOURCE_FS) or SOURCE_FS),
            "model_fs_hz": int(validation.get("model_fs_hz", MODEL_FS) or MODEL_FS),
            "frame_hop_s": float(validation.get("frame_hop_s", BIN_S) or BIN_S),
            "original_duration_s": float(h5_summary.get("original_duration_s", 0.0) or 0.0),
            "model_duration_s": float(h5_summary.get("model_duration_s", 0.0) or 0.0),
            "phone_interval_count": int((validation.get("interval_counts") or {}).get("phone", 0)),
            "syllable_interval_count": int((validation.get("interval_counts") or {}).get("syllable", 0)),
            "word_interval_count": int((validation.get("interval_counts") or {}).get("word", 0)),
            "sentence_interval_count": int((validation.get("interval_counts") or {}).get("sentence", 0)),
        }
        return {
            "ok": True,
            "order_index": order_index,
            "record": record,
            "record_index_row": record_index_row,
            "interval_index_rows": interval_index_rows,
            "copy_method": copy_method,
        }
    except _BIOEAR_REPORTED_FAILURES as exc:
        return {"ok": False, "order_index": order_index, "failure": {"wav": str(wav), "textgrid": str(textgrid), "error": str(exc)}}


def _emit_progress_bar(label: str, completed: int, total: int, *, extra: str = "", width: int = 34) -> None:
    total = max(1, int(total))
    completed = max(0, min(int(completed), total))
    filled = int(round(width * completed / total))
    bar = "#" * filled + "-" * (width - filled)
    percent = completed * 100.0 / total
    suffix = f" {extra}" if extra else ""
    print(f"\r{label} [{bar}] {completed}/{total} {percent:5.1f}%{suffix}", file=sys.stderr, end="", flush=True)
    if completed >= total:
        print(file=sys.stderr, flush=True)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    written = False
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        written = True
    finally:
        if not written and tmp.exists():
            tmp.unlink()


def _write_parquet_atomic(path: Path, frame: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    written = False
    try:
        frame.to_parquet(tmp, index=False)
        os.replace(tmp, path)
        written = True
    finally:
        if not written and tmp.exists():
            tmp.unlink()


def _cleanup_stale_bundle_tmp_files(bioear_root: Path, records_root: Path) -> int:
    removed = 0
    for folder in (bioear_root, records_root):
        if not folder.exists():
            continue
        for tmp in sorted(folder.glob("*.tmp")):
            if tmp.is_file():
                tmp.unlink()
                removed += 1
    return removed


def build_canonical_corpus(
    root: Path,
    *,
    output_root: Path,
    replace: bool = False,
    limit: int | None = None,
    start: int | None = None,
    end: int | None = None,
    progress: bool = True,
    command_provenance: Sequence[str] | None = None,
    profile: str = CANONICAL_EXTRACTION_PROFILE,
    jobs: int = 1,
    copy_mode: str = "auto",
) -> dict[str, Any]:
    import pandas as pd

    clear_graceful_stop()
    pairs = find_pairs(root, start=start, end=end, limit=limit)
    if profile == AUTO_EXTRACTION_PROFILE:
        detected = detect_homogeneous_sidecar_profile(root, limit=limit)
        if detected.get("profile") in EXTRACTION_PROFILES:
            profile = str(detected["profile"])
        elif any(pair.output.exists() for pair in pairs):
            raise BioEarError(f"could not autodetect a homogeneous BioEar profile: {detected}")
        else:
            profile = CANONICAL_EXTRACTION_PROFILE
    if profile not in EXTRACTION_PROFILES:
        raise BioEarError(f"unknown bioear extraction profile {profile!r}; expected one of {EXTRACTION_PROFILES} or 'auto'")
    bioear_root = output_root / "bioear"
    records_root = bioear_root / BIOEAR_RECORDS_DIRNAME
    bioear_root.mkdir(parents=True, exist_ok=True)
    records_root.mkdir(parents=True, exist_ok=True)
    stale_tmp_removed = _cleanup_stale_bundle_tmp_files(bioear_root, records_root)
    if replace:
        _remove_noncanonical_bioear_outputs(bioear_root)
    records: list[dict[str, Any]] = []
    record_index_rows: list[dict[str, Any]] = []
    interval_index_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    copy_methods: dict[str, int] = {}
    task_rows: list[tuple[int, str, str, str | None, str, str, int, str, str, bool, str, bool]] = []
    for index, pair in enumerate(pairs, start=1):
        number = pair.number if pair.number is not None else index
        record_id = str(number)
        dest = records_root / f"{record_id}_bioear.h5"
        task_rows.append(
            (
                index,
                str(pair.wav),
                str(pair.textgrid),
                str(pair.txt) if pair.txt else None,
                str(pair.output),
                str(dest),
                int(number),
                record_id,
                profile,
                replace,
                copy_mode,
                progress,
            )
        )

    jobs = max(1, int(jobs or 1))
    copy_mode = copy_mode if copy_mode in {"auto", "clone", "copy", "symlink"} else "auto"
    results: list[dict[str, Any]] = []
    completed_tasks = 0
    interrupted = False
    if progress:
        _emit_progress_bar("[bioear] bundle records", 0, len(task_rows), extra=f"jobs={jobs} copy_mode={copy_mode}")
    if jobs == 1 or len(task_rows) <= 1:
        for index, task in enumerate(task_rows, start=1):
            if graceful_stop_requested():
                interrupted = True
                break
            try:
                results.append(_build_canonical_record_task(task))
            except KeyboardInterrupt:
                request_graceful_stop()
                interrupted = True
                print("\n[bioear] graceful bundle stop requested; no new records will be started.", file=sys.stderr, flush=True)
                break
            completed_tasks = index
            if progress:
                _emit_progress_bar("[bioear] bundle records", index, len(task_rows), extra=f"jobs=1 copy_mode={copy_mode}")
    else:
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            task_iter = iter(task_rows)
            future_to_task: dict[Future[dict[str, Any]], tuple[int, str, str, str | None, str, str, int, str, str, bool, str, bool]] = {}

            def submit_until_full() -> None:
                if graceful_stop_requested():
                    return
                while len(future_to_task) < jobs:
                    try:
                        task = next(task_iter)
                    except StopIteration:
                        return
                    future_to_task[executor.submit(_build_canonical_record_task, task)] = task

            submit_until_full()
            while future_to_task:
                try:
                    done, _pending = wait(future_to_task, timeout=0.5, return_when=FIRST_COMPLETED)
                except KeyboardInterrupt:
                    request_graceful_stop()
                    interrupted = True
                    print("\n[bioear] graceful bundle stop requested; waiting for active record tasks to finish.", file=sys.stderr, flush=True)
                    continue
                if not done:
                    continue
                for future in done:
                    future_to_task.pop(future)
                    try:
                        results.append(future.result())
                    except _BIOEAR_REPORTED_FAILURES as exc:
                        results.append({"ok": False, "order_index": 0, "failure": {"error": str(exc)}})
                    completed_tasks += 1
                    if progress:
                        _emit_progress_bar("[bioear] bundle records", completed_tasks, len(task_rows), extra=f"jobs={jobs} copy_mode={copy_mode}")
                if graceful_stop_requested():
                    interrupted = True
                    continue
                submit_until_full()
    if progress and (interrupted or graceful_stop_requested()) and completed_tasks < len(task_rows):
        print(
            f"\n[bioear] bundle stopped after {completed_tasks}/{len(task_rows)} record tasks; rerun build-data to resume.",
            file=sys.stderr,
            flush=True,
        )

    for result in sorted(results, key=lambda item: int(item.get("order_index", 0))):
        if not result.get("ok"):
            failures.append(result.get("failure", {"error": "unknown build-data worker failure"}))
            continue
        record = result["record"]
        records.append(record)
        record_index_rows.append(result["record_index_row"])
        interval_index_rows.extend(result["interval_index_rows"])
        method = str(result.get("copy_method", "unknown"))
        copy_methods[method] = copy_methods.get(method, 0) + 1

    record_index_path = bioear_root / BIOEAR_RECORD_INDEX_NAME
    interval_index_path = bioear_root / BIOEAR_INTERVAL_INDEX_NAME
    quality_report_path = bioear_root / BIOEAR_QUALITY_REPORT_NAME
    manifest_path = bioear_root / BIOEAR_MANIFEST_NAME

    if interrupted or graceful_stop_requested():
        interrupted_payload = {
            "schema": "conphon.bioear.build_interrupted.v1",
            "ok": False,
            "interrupted": True,
            "created_at_utc": utc_now(),
            "input_root": str(root),
            "output_root": str(bioear_root),
            "record_count_completed_this_run": len(records),
            "task_count_completed": completed_tasks,
            "task_count_total": len(task_rows),
            "task_count_pending": max(0, len(task_rows) - completed_tasks),
            "failure_count": len(failures),
            "failures": failures,
            "copy_methods": copy_methods,
            "stale_tmp_removed": stale_tmp_removed,
            "resume_instruction": "rerun the same build-data command; valid canonical records are skipped and invalid records are repaired.",
        }
        _write_json_atomic(bioear_root / "bioear_build_interrupted.json", interrupted_payload)
        return interrupted_payload

    if progress:
        print("[bioear] writing bundle indexes", file=sys.stderr, flush=True)
    _write_parquet_atomic(record_index_path, pd.DataFrame(record_index_rows, columns=_record_index_columns()))
    _write_parquet_atomic(interval_index_path, pd.DataFrame(interval_index_rows, columns=_interval_index_columns()))

    interval_counts_total = {
        level: int(sum((record.get("validation", {}).get("interval_counts") or {}).get(level, 0) for record in records))
        for level in LEVELS
    }
    total_original_duration_s = float(sum(float(record.get("summary", {}).get("original_duration_s", 0.0) or 0.0) for record in records))
    total_model_duration_s = float(sum(float(record.get("summary", {}).get("model_duration_s", 0.0) or 0.0) for record in records))
    total_frame_count = int(sum(int(record.get("validation", {}).get("frame_count", 0) or 0) for record in records))
    cf_counts = sorted({int(record["validation"].get("cf_count", 0) or 0) for record in records if record.get("validation")})
    fiber_type_counts = sorted({int(record["validation"].get("fiber_type_count", 0) or 0) for record in records if record.get("validation")})
    extraction_profiles = sorted({str(record["validation"].get("extraction_profile", profile)) for record in records if record.get("validation")})
    homogeneity_errors: list[str] = []
    if len(extraction_profiles) != 1 or (extraction_profiles and extraction_profiles[0] != profile):
        homogeneity_errors.append(f"mixed_or_wrong_extraction_profiles:{extraction_profiles}:required={profile}")
    if len(cf_counts) != 1 or (cf_counts and cf_counts[0] != profile_cf_count(profile)):
        homogeneity_errors.append(f"mixed_or_wrong_cf_counts:{cf_counts}:required={profile_cf_count(profile)}")
    if len(fiber_type_counts) != 1 or (fiber_type_counts and fiber_type_counts[0] != len(profile_fiber_names(profile))):
        homogeneity_errors.append(f"mixed_or_wrong_fiber_type_counts:{fiber_type_counts}:required={len(profile_fiber_names(profile))}")
    forbidden_absence = _bioear_forbidden_output_absence_report(bioear_root)
    quality_report = {
        "schema": QUALITY_REPORT_SCHEMA,
        "ok": bool(not failures and not homogeneity_errors and records and all(record["validation"]["ok"] for record in records) and forbidden_absence["ok"]),
        "created_at_utc": utc_now(),
        "record_count": len(records),
        "failure_count": len(failures),
        "homogeneous_mode_ok": not homogeneity_errors,
        "homogeneity_errors": homogeneity_errors,
        "extraction_profile": profile,
        "bioear_mode": profile,
        "valid_hdf5_count": sum(bool(record["validation"]["ok"]) for record in records),
        "interval_counts": interval_counts_total,
        "total_original_duration_s": total_original_duration_s,
        "total_original_duration_hours": total_original_duration_s / 3600.0,
        "total_model_duration_s": total_model_duration_s,
        "total_model_duration_hours": total_model_duration_s / 3600.0,
        "total_frame_count": total_frame_count,
        "source_fs_hz": SOURCE_FS,
        "model_fs_hz": MODEL_FS,
        "frame_hop_s": BIN_S,
        "cf_count": cf_counts[0] if len(cf_counts) == 1 else None,
        "cf_counts": cf_counts,
        "fiber_type_count": fiber_type_counts[0] if len(fiber_type_counts) == 1 else None,
        "fiber_type_counts": fiber_type_counts,
        "extraction_profiles": extraction_profiles,
        "fiber_types": list(profile_fiber_names(profile)),
        "fibers_per_type": profile_fiber_counts(profile),
        "build_jobs": jobs,
        "canonical_copy_mode": copy_mode,
        "canonical_copy_methods": copy_methods,
        "stale_tmp_removed": stale_tmp_removed,
        "forbidden_non_bioear_output_absence": forbidden_absence,
        "failures": failures,
    }
    _write_json_atomic(quality_report_path, quality_report)

    index_hashes = {
        "record_index_sha256": sha256_file(record_index_path),
        "interval_index_sha256": sha256_file(interval_index_path),
        "quality_report_sha256": sha256_file(quality_report_path),
    }
    corpus_name_hint = " ".join(str(path).lower() for path in (root, output_root))
    if "corpus_english_40" in corpus_name_hint or "english_40_raw_dataset" in corpus_name_hint:
        language_id = "english"
    elif "corpus_mandarin" in corpus_name_hint or "mandarin_40_raw_dataset" in corpus_name_hint or "mandarin_80_raw_dataset" in corpus_name_hint:
        language_id = "mandarin"
    else:
        language_id = "portuguese"
    corpus_id_root = output_root.name if output_root.name.startswith("corpus_") else root.name
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "ok": bool(quality_report["ok"]),
        "created_at_utc": utc_now(),
        "corpus_id": f"{corpus_id_root}_full_detail",
        "language_id": language_id,
        "input_root": str(root),
        "output_root": str(bioear_root),
        "base_dir": str(bioear_root),
        "records_dir": str(records_root),
        "h5_dir": str(records_root),
        "record_index": str(record_index_path),
        "interval_index": str(interval_index_path),
        "quality_report_json": str(quality_report_path),
        "runtime_backend": OFFICIAL_BACKEND_MODULE,
        "extraction_profile": profile,
        "brucezilany_version": brucezilany_runtime_version(),
        "extractor_constants": constants_payload(profile=profile),
        "build_jobs": jobs,
        "canonical_copy_mode": copy_mode,
        "canonical_copy_methods": copy_methods,
        "stale_tmp_removed": stale_tmp_removed,
        "forbidden_non_bioear_output_policy": FORBIDDEN_NON_BIOEAR_OUTPUT_POLICY,
        "command_provenance": list(command_provenance or sys.argv),
        "record_count": len(records),
        "total_original_duration_s": total_original_duration_s,
        "total_original_duration_hours": total_original_duration_s / 3600.0,
        "total_model_duration_s": total_model_duration_s,
        "total_model_duration_hours": total_model_duration_s / 3600.0,
        "total_frame_count": total_frame_count,
        "failure_count": len(failures),
        "hashes": index_hashes,
        "records": records,
        "failures": failures,
    }
    _write_json_atomic(manifest_path, manifest)
    return {
        **manifest,
        "manifest_json": str(manifest_path),
        "quality_report_json": str(quality_report_path),
        "record_index": str(record_index_path),
        "interval_index": str(interval_index_path),
    }


def _record_index_columns() -> list[str]:
    return [
        "record_id",
        "number",
        "canonical_h5",
        "source_wav",
        "source_txt",
        "source_textgrid",
        "wav_sha256",
        "txt_sha256",
        "textgrid_sha256",
        "hdf5_sha256",
        "validation_ok",
        "extraction_profile",
        "bioear_mode",
        "frame_count",
        "cf_count",
        "fiber_type_count",
        "fibers_per_type_json",
        "source_fs_hz",
        "model_fs_hz",
        "frame_hop_s",
        "original_duration_s",
        "model_duration_s",
        "phone_interval_count",
        "syllable_interval_count",
        "word_interval_count",
        "sentence_interval_count",
    ]


def _interval_index_columns() -> list[str]:
    return [
        "record_id",
        "number",
        "canonical_h5",
        "level",
        "interval_index",
        "start_s",
        "end_s",
        "start_model_s",
        "end_model_s",
        "start_frame",
        "end_frame_exclusive",
        "label_id",
        "label",
        "parent_phone",
        "parent_syllable",
        "parent_word",
        "parent_sentence",
    ]


def _bioear_h5_summary(path: Path) -> dict[str, Any]:
    with h5py.File(path, "r") as h5:
        source_samples = int(h5["audio/source_dimensionless_wav_16k"].shape[0]) if "audio/source_dimensionless_wav_16k" in h5 else 0
        model_samples = int(h5["audio/model_pressure_pa_100k_padded"].shape[0]) if "audio/model_pressure_pa_100k_padded" in h5 else 0
        original_duration_s = float(h5.attrs.get("original_duration_s", 0.0) or 0.0)
        model_duration_s = float(h5.attrs.get("model_duration_s", 0.0) or 0.0)
        return {
            "original_duration_s": original_duration_s or (source_samples / float(SOURCE_FS) if source_samples else 0.0),
            "model_duration_s": model_duration_s or (model_samples / float(MODEL_FS) if model_samples else 0.0),
            "extraction_profile": str(h5.attrs.get("extraction_profile", "")),
            "cf_count": int(h5["periphery/characteristic_frequency_hz"].shape[0]) if "periphery/characteristic_frequency_hz" in h5 else 0,
            "top_level_groups": sorted(h5.keys()),
            "interval_counts": _h5_interval_counts(h5),
        }


def _bioear_h5_summary_and_interval_index_rows(path: Path, *, record_id: str, number: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    with h5py.File(path, "r") as h5:
        source_samples = int(h5["audio/source_dimensionless_wav_16k"].shape[0]) if "audio/source_dimensionless_wav_16k" in h5 else 0
        model_samples = int(h5["audio/model_pressure_pa_100k_padded"].shape[0]) if "audio/model_pressure_pa_100k_padded" in h5 else 0
        original_duration_s = float(h5.attrs.get("original_duration_s", 0.0) or 0.0)
        model_duration_s = float(h5.attrs.get("model_duration_s", 0.0) or 0.0)
        summary = {
            "original_duration_s": original_duration_s or (source_samples / float(SOURCE_FS) if source_samples else 0.0),
            "model_duration_s": model_duration_s or (model_samples / float(MODEL_FS) if model_samples else 0.0),
            "extraction_profile": str(h5.attrs.get("extraction_profile", "")),
            "cf_count": int(h5["periphery/characteristic_frequency_hz"].shape[0]) if "periphery/characteristic_frequency_hz" in h5 else 0,
            "top_level_groups": sorted(h5.keys()),
            "interval_counts": _h5_interval_counts(h5),
        }
        for level in LEVELS:
            ds_name = f"labels/intervals/{level}"
            if ds_name not in h5:
                continue
            ds = h5[ds_name]
            labels = _labels_from_interval_dataset(ds)
            table = ds[...]
            for idx, row in enumerate(table):
                label_id = int(row["label_id"]) if "label_id" in table.dtype.names else -1
                label = labels[label_id] if 0 <= label_id < len(labels) else ""
                rows.append(
                    {
                        "record_id": record_id,
                        "number": int(number),
                        "canonical_h5": str(path),
                        "level": level,
                        "interval_index": int(idx),
                        "start_s": float(row["start_s"]),
                        "end_s": float(row["end_s"]),
                        "start_model_s": float(row["start_model_s"]),
                        "end_model_s": float(row["end_model_s"]),
                        "start_frame": int(row["start_frame"]),
                        "end_frame_exclusive": int(row["end_frame_exclusive"]),
                        "label_id": label_id,
                        "label": label,
                        "parent_phone": int(row["parent_phone"]),
                        "parent_syllable": int(row["parent_syllable"]),
                        "parent_word": int(row["parent_word"]),
                        "parent_sentence": int(row["parent_sentence"]),
                    }
                )
    return summary, rows


def _bioear_interval_index_rows(path: Path, *, record_id: str, number: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with h5py.File(path, "r") as h5:
        for level in LEVELS:
            ds_name = f"labels/intervals/{level}"
            if ds_name not in h5:
                continue
            ds = h5[ds_name]
            labels = _labels_from_interval_dataset(ds)
            table = ds[...]
            for idx, row in enumerate(table):
                label_id = int(row["label_id"]) if "label_id" in table.dtype.names else -1
                label = labels[label_id] if 0 <= label_id < len(labels) else ""
                rows.append(
                    {
                        "record_id": record_id,
                        "number": int(number),
                        "canonical_h5": str(path),
                        "level": level,
                        "interval_index": int(idx),
                        "start_s": float(row["start_s"]),
                        "end_s": float(row["end_s"]),
                        "start_model_s": float(row["start_model_s"]),
                        "end_model_s": float(row["end_model_s"]),
                        "start_frame": int(row["start_frame"]),
                        "end_frame_exclusive": int(row["end_frame_exclusive"]),
                        "label_id": label_id,
                        "label": label,
                        "parent_phone": int(row["parent_phone"]),
                        "parent_syllable": int(row["parent_syllable"]),
                        "parent_word": int(row["parent_word"]),
                        "parent_sentence": int(row["parent_sentence"]),
                    }
                )
    return rows


def _labels_from_interval_dataset(dataset: h5py.Dataset) -> list[str]:
    raw = dataset.attrs.get("labels_json", "[]")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except json.JSONDecodeError:
        payload = []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload]


def _bioear_forbidden_output_absence_report(bioear_root: Path) -> dict[str, Any]:
    checks = {
        "forbidden_loose_root_h5": sorted(str(path) for path in bioear_root.glob("*.h5") if path.parent == bioear_root),
        "forbidden_manifest_jsonl": sorted(str(path) for path in bioear_root.glob("manifest.jsonl")),
        "forbidden_noncanonical_reproducibility_manifest": sorted(str(path) for path in bioear_root.glob("conphon_bioear_reproducibility_manifest.json")),
        "forbidden_engineered_feature_dirs": sorted(str(path) for path in bioear_root.rglob("engineered_feature") if path.is_dir()),
        "forbidden_latent_chunk_dirs": sorted(str(path) for path in bioear_root.rglob("*latent_chunk*")),
        "forbidden_acoustic_frequent_frame_dirs": sorted(str(path) for path in bioear_root.rglob("*acoustic_frequent_frame*")),
        "forbidden_npy_sidecars": sorted(str(path) for path in bioear_root.rglob("*.npy")),
        "forbidden_engineered_feature_manifest_tsv": sorted(str(path) for path in bioear_root.rglob("*_engineered_feature_manifest.tsv")),
        "forbidden_phonetic_detail_outputs": sorted(str(path) for path in bioear_root.rglob("*phonetic*")),
    }
    unexpected = {key: value for key, value in checks.items() if value}
    return {
        "ok": not unexpected,
        "scope": str(bioear_root),
        "unexpected": unexpected,
        "policy": FORBIDDEN_NON_BIOEAR_OUTPUT_POLICY,
    }


def _remove_noncanonical_bioear_outputs(bioear_root: Path) -> None:
    for path in bioear_root.glob("*.h5"):
        if path.is_file():
            path.unlink()
    for name in ("manifest.jsonl", "conphon_bioear_reproducibility_manifest.json"):
        path = bioear_root / name
        if path.exists() and path.is_file():
            path.unlink()
    root_manifest = bioear_root.parent / "conphon_bioear_reproducibility_manifest.json"
    if root_manifest.exists() and root_manifest.is_file():
        root_manifest.unlink()


def _select_pairs(
    pairs: Sequence[BioEarPair],
    *,
    start: int | None = None,
    end: int | None = None,
    limit: int | None = None,
) -> list[BioEarPair]:
    selected = list(pairs)
    if start is not None:
        selected = [pair for pair in selected if pair.number is None or pair.number >= start]
    if end is not None:
        selected = [pair for pair in selected if pair.number is None or pair.number <= end]
    if limit is not None:
        selected = selected[: max(0, int(limit))]
    return selected


def scan_payload(root: Path, *, start: int | None = None, end: int | None = None, limit: int | None = None) -> dict[str, Any]:
    pairs = find_pairs(root, start=start, end=end, limit=limit)
    valid = [pair for pair in pairs if validate_bioear_h5(pair.output)["ok"]]
    return {
        "schema": "conphon.bioear.scan.v1",
        "ok": True,
        "root": str(root),
        "pair_count": len(pairs),
        "bioear_done_count": len(valid),
        "pending_count": len(pairs) - len(valid),
        "pairs": [
            {
                "number": pair.number,
                "wav": str(pair.wav),
                "txt": str(pair.txt) if pair.txt else None,
                "textgrid": str(pair.textgrid),
                "output": str(pair.output),
                "valid_existing_output": validate_bioear_h5(pair.output)["ok"],
            }
            for pair in pairs
        ],
    }
