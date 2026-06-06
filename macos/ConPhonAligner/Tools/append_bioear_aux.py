#!/usr/bin/env python3
"""Append compact 1 ms BioEar IHC/synapse/redocking datasets to corpus HDF5s.

This is a maintenance script, not part of the canonical extractor pipeline yet.
It is intentionally idempotent: files that already contain valid compact
auxiliary datasets are skipped, and Ctrl+C stops after active files finish.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import traceback
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import h5py
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BACKEND_ROOT = REPO_ROOT
if not (DEFAULT_BACKEND_ROOT / "src" / "conphon").exists():
    sibling_conphon = REPO_ROOT.parent / "conphon"
    if (sibling_conphon / "src" / "conphon").exists():
        DEFAULT_BACKEND_ROOT = sibling_conphon
BACKEND_ROOT = Path(os.environ.get("CONPHON_BACKEND_ROOT", DEFAULT_BACKEND_ROOT)).expanduser().resolve()
if not (BACKEND_ROOT / "src" / "conphon").exists() and (BACKEND_ROOT / "conphon" / "src" / "conphon").exists():
    BACKEND_ROOT = BACKEND_ROOT / "conphon"
if not (BACKEND_ROOT / "src" / "conphon").exists():
    raise RuntimeError(f"Canonical ConPhon backend not found at {BACKEND_ROOT}")

for candidate in (BACKEND_ROOT, BACKEND_ROOT / "src"):
    text = str(candidate)
    while text in sys.path:
        sys.path.remove(text)
    sys.path.insert(0, text)

from conphon.bioear.extractor import (  # noqa: E402
    BIN_S,
    FAST_BIOEAR_THREADS_PER_FILE_ENV,
    MODEL_FS,
    BioEarError,
    calibrate_dimensionless_wav_to_pressure_pa,
    h5_write_fast,
    import_brucezilany,
    load_mono_16k_wav,
    make_bz_stimulus,
    pad_model_pressure,
    profile_config,
    profile_fiber_counts,
    profile_from_cf_count,
    resample_16k_to_100k,
    utc_now,
)


IHC_NAME = "ihc_receptor_potential"
SYNAPSE_NAME = "synapse_drive"
REDOCKING_NAME = "redocking_time_mean"
IHC_1MS_NAME = "ihc_receptor_potential_1ms"
SYNAPSE_1MS_NAME = "synapse_drive_1ms"
REDOCKING_1MS_NAME = "redocking_time_1ms"
TMP_IHC_NAME = "__tmp_ihc_receptor_potential_1ms"
TMP_SYNAPSE_NAME = "__tmp_synapse_drive_1ms"
TMP_REDOCKING_NAME = "__tmp_redocking_time_mean_1ms"
MANIFEST_NAME = "bioear_manifest.json"
RECORD_INDEX_NAME = "record_index.parquet"
SCRIPT_SCHEMA = "conphon.bioear.aux_append.v2"
REDOCKING_EQUATION = "D_{tcf}=1/(1+R_{tcf}/(2 s_f))"
STOP_REQUESTED = False


@dataclass(frozen=True)
class AuxTask:
    corpus: str
    h5_path: str
    wav_path: str
    profile: str
    record_id: str


def request_stop(_signum: int | None = None, _frame: Any | None = None) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print("[bioear-aux] graceful stop requested; active files will finish.", file=sys.stderr, flush=True)


def ignore_worker_sigint() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def install_signal_handlers() -> None:
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)


def emit(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    ok = "OK" if payload.get("ok") else "FAILED"
    print(f"{ok}: {payload.get('schema', SCRIPT_SCHEMA)}")
    for key in (
        "task_count",
        "already_complete",
        "scheduled",
        "created",
        "created_full_aux",
        "redocking_backfilled",
        "skipped",
        "failed",
        "interrupted",
        "bytes_added",
        "bytes_added_human",
    ):
        if key in payload:
            print(f"{key}: {payload[key]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append compact 1 ms IHC/synapse/redocking datasets to BioEar HDF5 sidecars.")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=BACKEND_ROOT / "data",
        help="Data root containing corpus_* directories. Default: repository data root.",
    )
    parser.add_argument(
        "--corpus",
        action="append",
        default=[],
        help="Corpus directory/name to process, e.g. corpus_english_40 or english_40. May be repeated. Default: all data/corpus_* bundles.",
    )
    parser.add_argument(
        "--sidecar-root",
        action="append",
        type=Path,
        default=[],
        help="Folder containing sidecar *_bioear.h5 files beside their source WAVs. May be repeated.",
    )
    parser.add_argument(
        "--language",
        choices=("all", "english", "mandarin", "portuguese"),
        default="all",
        help="Select corpus bundles by language when --corpus is not provided. Default: all.",
    )
    parser.add_argument("--include-substrate", action="store_true", help="Also scan data/phonological_substrate for BioEar manifests.")
    parser.add_argument("--jobs", type=int, default=int(os.environ.get("CONPHON_AUX_APPEND_JOBS", "1")), help="Parallel files. Default: 1.")
    parser.add_argument(
        "--components",
        default="ihc,synapse,redocking",
        help="Comma-separated auxiliary components to ensure: ihc, synapse, redocking, or all. Default: ihc,synapse,redocking.",
    )
    parser.add_argument(
        "--threads-per-file",
        type=int,
        default=int(os.environ.get(FAST_BIOEAR_THREADS_PER_FILE_ENV, "1")),
        help="Threads passed to brucezilany fast_rate_neurogram per file. Default: CONPHON_BIOEAR_THREADS_PER_FILE or 1.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of pending files to process.")
    parser.add_argument("--replace-confirmed", action="store_true", help="Replace existing compact aux datasets.")
    parser.add_argument(
        "--check-existing",
        action="store_true",
        help="Slow discovery mode: open each H5 up front and count already-augmented files. Runtime workers always check safely.",
    )
    parser.add_argument(
        "--dedupe-realpaths",
        action="store_true",
        help="Slow discovery mode: deduplicate symlinks by resolved target. By default, workers safely skip duplicates.",
    )
    parser.add_argument(
        "--validate-discovery-paths",
        action="store_true",
        help="Slow discovery mode: stat H5/WAV paths before scheduling. By default, workers validate paths when reached.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Discover and report work without modifying files.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def parse_components(value: str) -> frozenset[str]:
    aliases = {
        "all": "all",
        "rich": "all",
        "ihc": "ihc",
        "v": "ihc",
        "syn": "synapse",
        "synapse": "synapse",
        "synapse_drive": "synapse",
        "s": "synapse",
        "redock": "redocking",
        "redocking": "redocking",
        "d": "redocking",
    }
    raw_parts = [part.strip().lower().replace("-", "_") for part in value.split(",")]
    parts = [part for part in raw_parts if part]
    if not parts:
        raise BioEarError("--components must include at least one of ihc, synapse, redocking")
    selected: set[str] = set()
    for part in parts:
        if part not in aliases:
            raise BioEarError(f"unknown --components value: {part!r}")
        mapped = aliases[part]
        if mapped == "all":
            return frozenset({"ihc", "synapse", "redocking"})
        selected.add(mapped)
    return frozenset(selected)


def ordered_components(components: frozenset[str]) -> list[str]:
    return [name for name in ("ihc", "synapse", "redocking") if name in components]


def corpus_dir_for_arg(data_root: Path, value: str) -> Path:
    token = value.strip()
    if not token:
        raise ValueError("empty --corpus value")
    direct = Path(token).expanduser()
    if direct.exists():
        return direct.resolve()
    normalized = token.lower().replace("-", "_")
    if normalized.startswith("corpus_"):
        return (data_root / normalized).resolve()
    return (data_root / f"corpus_{normalized}").resolve()


def discover_manifest_dirs(data_root: Path, corpus_args: Iterable[str], *, language: str, include_substrate: bool) -> list[Path]:
    if corpus_args:
        candidates = [corpus_dir_for_arg(data_root, value) for value in corpus_args]
    else:
        candidates = sorted(path for path in data_root.glob("corpus_*") if path.is_dir())
        language = language.strip().lower()
        if language != "all":
            candidates = [path for path in candidates if path.name.startswith(f"corpus_{language}_")]
    if include_substrate:
        substrate = data_root / "phonological_substrate"
        if substrate.exists():
            candidates.append(substrate)
    manifest_dirs: list[Path] = []
    seen: set[Path] = set()
    for root in candidates:
        direct_manifests = []
        if root.name == "bioear" and (root / MANIFEST_NAME).exists():
            direct_manifests.append(root / MANIFEST_NAME)
        if (root / "bioear" / MANIFEST_NAME).exists():
            direct_manifests.append(root / "bioear" / MANIFEST_NAME)
        if include_substrate and not direct_manifests:
            direct_manifests.extend(sorted(root.glob(f"**/bioear/{MANIFEST_NAME}")))
        for manifest in direct_manifests:
            bioear_dir = manifest.parent.resolve()
            if bioear_dir not in seen:
                manifest_dirs.append(bioear_dir)
                seen.add(bioear_dir)
    return manifest_dirs


def load_tasks(
    manifest_dirs: Iterable[Path],
    *,
    replace: bool,
    check_existing: bool,
    dedupe_realpaths: bool,
    validate_discovery_paths: bool,
) -> tuple[list[AuxTask], int, list[dict[str, Any]]]:
    tasks: list[AuxTask] = []
    already_complete = 0
    errors: list[dict[str, Any]] = []
    seen_h5_keys: set[str] = set()

    for bioear_dir in manifest_dirs:
        if STOP_REQUESTED:
            break
        record_index = bioear_dir / RECORD_INDEX_NAME
        corpus = bioear_dir.parent.name
        if not record_index.exists():
            errors.append({"corpus": corpus, "error": f"missing_record_index:{record_index}"})
            continue
        try:
            frame = pd.read_parquet(record_index)
        except Exception as exc:  # noqa: BLE001 - maintenance script reports and continues.
            errors.append({"corpus": corpus, "error": f"record_index_read_failed:{exc}"})
            continue
        for idx, row in frame.iterrows():
            if STOP_REQUESTED:
                break
            try:
                h5_path = Path(str(row["canonical_h5"])).expanduser()
                h5_key = str(h5_path.resolve()) if dedupe_realpaths else str(h5_path)
                if h5_key in seen_h5_keys:
                    continue
                seen_h5_keys.add(h5_key)
                wav_path = Path(str(row.get("source_wav") or "")).expanduser()
                record_id = str(row.get("record_id") or row.get("number") or idx)
                profile = str(row.get("extraction_profile") or row.get("bioear_mode") or "")
                if not profile and (check_existing or validate_discovery_paths):
                    profile = _profile_from_h5(h5_path)
                if validate_discovery_paths:
                    if not h5_path.exists():
                        errors.append({"corpus": corpus, "record_id": record_id, "h5": str(h5_path), "error": "missing_h5"})
                        continue
                    if not wav_path.exists():
                        wav_path = _source_wav_from_h5(h5_path)
                    if not wav_path.exists():
                        errors.append({"corpus": corpus, "record_id": record_id, "h5": str(h5_path), "error": "missing_source_wav"})
                        continue
                if check_existing and not replace:
                    status = aux_status(h5_path)
                    if status["complete"]:
                        already_complete += 1
                        continue
                tasks.append(AuxTask(corpus=corpus, h5_path=str(h5_path), wav_path=str(wav_path), profile=profile, record_id=record_id))
            except Exception as exc:  # noqa: BLE001
                errors.append({"corpus": corpus, "row": int(idx), "error": str(exc)})
    return tasks, already_complete, errors


def load_sidecar_tasks(
    roots: Iterable[Path],
    *,
    replace: bool,
    check_existing: bool,
    dedupe_realpaths: bool,
    validate_discovery_paths: bool,
) -> tuple[list[AuxTask], int, list[dict[str, Any]]]:
    tasks: list[AuxTask] = []
    already_complete = 0
    errors: list[dict[str, Any]] = []
    seen_h5_keys: set[str] = set()

    for root in roots:
        root = root.expanduser().resolve()
        if not root.exists():
            errors.append({"corpus": root.name, "error": f"missing_sidecar_root:{root}"})
            continue
        for h5_path in sorted(root.rglob("*_bioear.h5")):
            if STOP_REQUESTED:
                break
            try:
                h5_key = str(h5_path.resolve()) if dedupe_realpaths else str(h5_path)
                if h5_key in seen_h5_keys:
                    continue
                seen_h5_keys.add(h5_key)
                profile = _profile_from_h5(h5_path)
                wav_path = _source_wav_for_sidecar(h5_path)
                if validate_discovery_paths and not wav_path.exists():
                    errors.append({"corpus": root.name, "h5": str(h5_path), "error": f"missing_source_wav:{wav_path}"})
                    continue
                if check_existing and not replace:
                    status = aux_status(h5_path)
                    if status["complete"]:
                        already_complete += 1
                        continue
                record_id = h5_path.stem.removesuffix("_bioear")
                tasks.append(AuxTask(corpus=root.name, h5_path=str(h5_path), wav_path=str(wav_path), profile=profile, record_id=record_id))
            except Exception as exc:  # noqa: BLE001
                errors.append({"corpus": root.name, "h5": str(h5_path), "error": str(exc)})
    return tasks, already_complete, errors


def _profile_from_h5(h5_path: Path) -> str:
    with h5py.File(h5_path, "r") as h5:
        for attr in ("extraction_profile", "bioear_mode"):
            profile = str(h5.attrs.get(attr, ""))
            if profile:
                return profile
        if "periphery/characteristic_frequency_hz" in h5:
            inferred = profile_from_cf_count(int(h5["periphery/characteristic_frequency_hz"].shape[0]))
            if inferred:
                return inferred
    return ""


def _source_wav_from_h5(h5_path: Path) -> Path:
    with h5py.File(h5_path, "r") as h5:
        source = str(h5.attrs.get("source_wav", ""))
    return Path(source).expanduser()


def _source_wav_for_sidecar(h5_path: Path) -> Path:
    try:
        with h5py.File(h5_path, "r") as h5:
            source_text = str(h5.attrs.get("source_wav", "")).strip()
        if source_text:
            return Path(source_text).expanduser()
    except Exception:
        pass
    stem = h5_path.stem.removesuffix("_bioear")
    return h5_path.with_name(f"{stem}.wav")


def aux_status(h5_path: Path) -> dict[str, Any]:
    with h5py.File(h5_path, "r") as h5:
        if "periphery/rate_neurogram_1ms_hz_per_fiber" not in h5:
            return {"complete": False, "reason": "missing_rate_neurogram"}
        rate_shape = tuple(int(v) for v in h5["periphery/rate_neurogram_1ms_hz_per_fiber"].shape)
        if len(rate_shape) != 3:
            return {"complete": False, "reason": f"bad_rate_shape:{rate_shape}"}
        n_frames, n_cf, n_types = rate_shape
        ihc_ok = f"periphery/{IHC_NAME}" in h5 and tuple(h5[f"periphery/{IHC_NAME}"].shape) == (n_frames, n_cf)
        syn_ok = f"periphery/{SYNAPSE_NAME}" in h5 and tuple(h5[f"periphery/{SYNAPSE_NAME}"].shape) == (n_frames, n_cf, n_types)
        redocking_ok = f"periphery/{REDOCKING_NAME}" in h5 and tuple(h5[f"periphery/{REDOCKING_NAME}"].shape) == (n_frames, n_cf, n_types)
        return {
            "complete": bool(ihc_ok and syn_ok and redocking_ok),
            "ihc_ok": bool(ihc_ok),
            "synapse_ok": bool(syn_ok),
            "redocking_ok": bool(redocking_ok),
            "rate_shape": rate_shape,
        }


def append_aux_worker(task: AuxTask, *, replace: bool, threads_per_file: int, components: frozenset[str]) -> dict[str, Any]:
    try:
        return append_aux_to_h5(task, replace=replace, threads_per_file=threads_per_file, components=components)
    except Exception as exc:  # noqa: BLE001 - worker payload must be machine-readable.
        return {
            "ok": False,
            "status": "failed",
            "corpus": task.corpus,
            "record_id": task.record_id,
            "h5": task.h5_path,
            "wav": task.wav_path,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=8),
        }


def append_aux_to_h5(task: AuxTask, *, replace: bool, threads_per_file: int, components: frozenset[str]) -> dict[str, Any]:
    h5_path = Path(task.h5_path)
    wav_path = Path(task.wav_path)
    before_size = h5_path.stat().st_size
    profile = task.profile or _profile_from_h5(h5_path)
    if profile not in {"fast", "balanced", "context-lite"}:
        raise BioEarError(f"unsupported or missing extraction profile for {h5_path}: {profile!r}")

    with h5py.File(h5_path, "r") as h5:
        rate = h5["periphery/rate_neurogram_1ms_hz_per_fiber"]
        n_frames, n_cf, n_types = (int(rate.shape[0]), int(rate.shape[1]), int(rate.shape[2]))
        rate_1ms = np.asarray(rate, dtype=np.float32)
        cfs = np.asarray(h5["periphery/characteristic_frequency_hz"], dtype=np.float64)
        power_law_name = str(h5.attrs.get("brucezilany_power_law") or profile_config(profile)["power_law"])
        if cfs.shape != (n_cf,):
            raise BioEarError(f"CF shape mismatch in {h5_path}: {cfs.shape} != ({n_cf},)")

    status = aux_status(h5_path)
    requested_complete = (
        ("ihc" not in components or bool(status.get("ihc_ok", False)))
        and ("synapse" not in components or bool(status.get("synapse_ok", False)))
        and ("redocking" not in components or bool(status.get("redocking_ok", False)))
    )
    if requested_complete and not replace:
        with h5py.File(h5_path, "r+") as h5:
            periphery = h5["periphery"]
            _write_contract_aliases(periphery)
            _write_auxiliary_attrs(h5, periphery, profile=profile, threads_per_file=threads_per_file, components=components)
            h5.flush()
        return {
            "ok": True,
            "status": "skipped_existing_rich_aux",
            "corpus": task.corpus,
            "record_id": task.record_id,
            "h5": str(h5_path),
            "bytes_added": 0,
        }

    config = profile_config(profile)
    fiber_types = tuple(config["fiber_types"])
    if len(fiber_types) != n_types:
        raise BioEarError(f"fiber type count mismatch in {h5_path}: profile {profile} has {len(fiber_types)}, H5 has {n_types}")

    redocking_1ms = derive_redocking_time_1ms(rate_1ms, fiber_types=fiber_types)
    if components == frozenset({"redocking"}) and (replace or not bool(status.get("redocking_ok", False))):
        write_redocking_dataset(
            h5_path,
            redocking_1ms=redocking_1ms,
            source_shapes={"rate_neurogram_1ms_hz_per_fiber": [int(v) for v in rate_1ms.shape]},
            profile=profile,
            threads_per_file=threads_per_file,
            components=components,
            replace=replace,
        )
        after_size = h5_path.stat().st_size
        return {
            "ok": True,
            "status": "created_redocking_checkpoint0",
            "corpus": task.corpus,
            "record_id": task.record_id,
            "h5": str(h5_path),
            "profile": profile,
            "frames": n_frames,
            "checkpoint0_phonological_substrate_ready": True,
            "redocking_equation": REDOCKING_EQUATION,
            "bytes_before": before_size,
            "bytes_after": after_size,
            "bytes_added": max(0, after_size - before_size),
        }

    needs_highrate_bioear = bool(components.intersection({"ihc", "synapse"}))
    if not needs_highrate_bioear:
        after_size = h5_path.stat().st_size
        return {
            "ok": True,
            "status": "skipped_existing_selected_aux",
            "corpus": task.corpus,
            "record_id": task.record_id,
            "h5": str(h5_path),
            "bytes_added": 0,
        }

    if not wav_path.exists():
        wav_path = _source_wav_from_h5(h5_path)
    if not wav_path.exists():
        raise BioEarError(f"source WAV not found for {h5_path}: {task.wav_path}")

    wav_dimless_16k, _source_fs = load_mono_16k_wav(wav_path)
    wav_100k = resample_16k_to_100k(wav_dimless_16k)
    pressure_100k_pa = calibrate_dimensionless_wav_to_pressure_pa(wav_100k)
    pressure_100k_pa_padded = pad_model_pressure(pressure_100k_pa)

    bz, stimulus_module = import_brucezilany()
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
        seed_base=13579,
        save_ihc=True,
        save_synapse_drive=True,
        n_threads=max(1, int(threads_per_file)),
    )

    ihc_1ms = downsample_cf_time(np.asarray(result.ihc_receptor_potential), n_frames=n_frames, n_cf=n_cf)
    synapse_1ms = downsample_cf_fiber_time(np.asarray(result.synapse_drive), n_frames=n_frames, n_cf=n_cf, n_types=n_types)
    source_shapes = {
        "ihc_receptor_potential": [int(v) for v in np.asarray(result.ihc_receptor_potential).shape],
        "synapse_drive": [int(v) for v in np.asarray(result.synapse_drive).shape],
        "redocking_time_mean": [int(v) for v in rate_1ms.shape],
    }
    del result

    write_aux_datasets(
        h5_path,
        ihc_1ms=ihc_1ms,
        synapse_1ms=synapse_1ms,
        redocking_1ms=redocking_1ms,
        replace=replace,
        source_shapes=source_shapes,
        profile=profile,
        threads_per_file=threads_per_file,
        components=components,
    )
    after_size = h5_path.stat().st_size
    return {
        "ok": True,
        "status": "created",
        "corpus": task.corpus,
        "record_id": task.record_id,
        "h5": str(h5_path),
        "wav": str(wav_path),
        "profile": profile,
        "frames": n_frames,
        "checkpoint0_phonological_substrate_ready": True,
        "redocking_equation": REDOCKING_EQUATION,
        "bytes_before": before_size,
        "bytes_after": after_size,
        "bytes_added": max(0, after_size - before_size),
    }


def derive_redocking_time_1ms(rate_1ms: np.ndarray, *, fiber_types: tuple[tuple[str, float, int], ...]) -> np.ndarray:
    rate = np.maximum(np.asarray(rate_1ms, dtype=np.float64), 0.0)
    spontaneous = np.asarray([float(spont) for _name, spont, _count in fiber_types], dtype=np.float64)
    if rate.ndim != 3 or rate.shape[2] != spontaneous.size:
        raise BioEarError(f"rate_neurogram_1ms must have shape (frames, cf, {spontaneous.size}); got {rate.shape}")
    redocking = 1.0 / (1.0 + rate / np.maximum(2.0 * spontaneous[None, None, :], 1.0e-12))
    return np.clip(redocking, 0.0, 1.0).astype(np.float32)


def downsample_cf_time(values: np.ndarray, *, n_frames: int, n_cf: int) -> np.ndarray:
    arr = np.asarray(values)
    if arr.shape == (n_frames, n_cf):
        return arr.astype(np.float32, copy=False)
    if arr.ndim != 2 or arr.shape[0] != n_cf:
        raise BioEarError(f"IHC must have shape ({n_cf}, samples) or ({n_frames}, {n_cf}); got {arr.shape}")
    samples_per_frame = int(round(MODEL_FS * BIN_S))
    out = np.zeros((n_frames, n_cf), dtype=np.float32)
    usable = min(int(arr.shape[1]), n_frames * samples_per_frame)
    full_frames = usable // samples_per_frame
    if full_frames:
        block = arr[:, : full_frames * samples_per_frame]
        out[:full_frames] = block.reshape(n_cf, full_frames, samples_per_frame).mean(axis=2).T.astype(np.float32)
    if full_frames < n_frames and usable > full_frames * samples_per_frame:
        out[full_frames] = arr[:, full_frames * samples_per_frame : usable].mean(axis=1).astype(np.float32)
    return out


def downsample_cf_fiber_time(values: np.ndarray, *, n_frames: int, n_cf: int, n_types: int) -> np.ndarray:
    arr = np.asarray(values)
    if arr.shape == (n_frames, n_cf, n_types):
        return arr.astype(np.float32, copy=False)
    if arr.ndim != 3 or arr.shape[:2] != (n_cf, n_types):
        raise BioEarError(f"synapse_drive must have shape ({n_cf}, {n_types}, samples) or ({n_frames}, {n_cf}, {n_types}); got {arr.shape}")
    samples_per_frame = int(round(MODEL_FS * BIN_S))
    out = np.zeros((n_frames, n_cf, n_types), dtype=np.float32)
    usable = min(int(arr.shape[2]), n_frames * samples_per_frame)
    full_frames = usable // samples_per_frame
    if full_frames:
        block = arr[:, :, : full_frames * samples_per_frame]
        out[:full_frames] = block.reshape(n_cf, n_types, full_frames, samples_per_frame).mean(axis=3).transpose(2, 0, 1).astype(np.float32)
    if full_frames < n_frames and usable > full_frames * samples_per_frame:
        out[full_frames] = arr[:, :, full_frames * samples_per_frame : usable].mean(axis=2).astype(np.float32)
    return out


def write_aux_datasets(
    h5_path: Path,
    *,
    ihc_1ms: np.ndarray,
    synapse_1ms: np.ndarray,
    redocking_1ms: np.ndarray,
    replace: bool,
    source_shapes: dict[str, list[int]],
    profile: str,
    threads_per_file: int,
    components: frozenset[str],
) -> None:
    with h5py.File(h5_path, "r+") as h5:
        periphery = h5["periphery"]
        requested_names = {
            "ihc": (IHC_NAME, TMP_IHC_NAME),
            "synapse": (SYNAPSE_NAME, TMP_SYNAPSE_NAME),
            "redocking": (REDOCKING_NAME, TMP_REDOCKING_NAME),
        }
        active_names = [requested_names[name] for name in ("ihc", "synapse", "redocking") if name in components]
        for _name, tmp_name in active_names:
            if tmp_name in periphery:
                del periphery[tmp_name]
        if replace:
            for name, _tmp_name in active_names:
                if name in periphery:
                    del periphery[name]
        elif all(name in periphery for name, _tmp_name in active_names):
            return

        datasets: list[tuple[h5py.Dataset, str]] = []
        if "ihc" in components:
            datasets.append((h5_write_fast(periphery, TMP_IHC_NAME, ihc_1ms), IHC_NAME))
        if "synapse" in components:
            datasets.append((h5_write_fast(periphery, TMP_SYNAPSE_NAME, synapse_1ms), SYNAPSE_NAME))
        if "redocking" in components:
            datasets.append((h5_write_fast(periphery, TMP_REDOCKING_NAME, redocking_1ms), REDOCKING_NAME))

        for ds, source_name in datasets:
            ds.attrs["schema"] = SCRIPT_SCHEMA
            ds.attrs["time_base"] = "periphery/frame_model_time_s"
            ds.attrs["frame_hop_s"] = float(BIN_S)
            ds.attrs["storage"] = (
                "compact_1ms_checkpoint0_rate_derived_adaptation_proxy"
                if source_name == REDOCKING_NAME
                else "compact_1ms_mean_from_highrate_brucezilany"
            )
            ds.attrs["source_highrate_shape_json"] = json.dumps(source_shapes[source_name])
            if source_name == REDOCKING_NAME:
                ds.attrs["source_equation"] = REDOCKING_EQUATION
                ds.attrs["source_rate_dataset"] = "periphery/rate_neurogram_1ms_hz_per_fiber"
                ds.attrs["checkpoint0_phonological_substrate_coordinate"] = True
        h5.flush()

        for name, tmp_name in active_names:
            if name in periphery:
                del periphery[name]
            periphery.move(tmp_name, name)
        _write_contract_aliases(periphery)
        _write_auxiliary_attrs(h5, periphery, profile=profile, threads_per_file=threads_per_file, components=components)
        h5.flush()


def write_redocking_dataset(
    h5_path: Path,
    *,
    redocking_1ms: np.ndarray,
    source_shapes: dict[str, list[int]],
    profile: str,
    threads_per_file: int,
    components: frozenset[str],
    replace: bool,
) -> None:
    with h5py.File(h5_path, "r+") as h5:
        periphery = h5["periphery"]
        if TMP_REDOCKING_NAME in periphery:
            del periphery[TMP_REDOCKING_NAME]
        if REDOCKING_NAME in periphery and not replace:
            return
        if REDOCKING_NAME in periphery:
            del periphery[REDOCKING_NAME]
        ds = h5_write_fast(periphery, TMP_REDOCKING_NAME, redocking_1ms)
        ds.attrs["schema"] = SCRIPT_SCHEMA
        ds.attrs["time_base"] = "periphery/frame_model_time_s"
        ds.attrs["frame_hop_s"] = float(BIN_S)
        ds.attrs["storage"] = "compact_1ms_checkpoint0_rate_derived_adaptation_proxy"
        ds.attrs["source_highrate_shape_json"] = json.dumps(source_shapes["rate_neurogram_1ms_hz_per_fiber"])
        ds.attrs["source_equation"] = REDOCKING_EQUATION
        ds.attrs["source_rate_dataset"] = "periphery/rate_neurogram_1ms_hz_per_fiber"
        ds.attrs["checkpoint0_phonological_substrate_coordinate"] = True
        h5.flush()
        periphery.move(TMP_REDOCKING_NAME, REDOCKING_NAME)
        _write_contract_aliases(periphery)
        _write_auxiliary_attrs(h5, periphery, profile=profile, threads_per_file=threads_per_file, components=components)
        h5.flush()


def _write_contract_aliases(periphery: h5py.Group) -> None:
    for source_name, alias_name in (
        (IHC_NAME, IHC_1MS_NAME),
        (SYNAPSE_NAME, SYNAPSE_1MS_NAME),
        (REDOCKING_NAME, REDOCKING_1MS_NAME),
    ):
        if source_name not in periphery:
            continue
        if alias_name in periphery:
            del periphery[alias_name]
        periphery[alias_name] = periphery[source_name]


def _write_auxiliary_attrs(h5: h5py.File, periphery: h5py.Group, *, profile: str, threads_per_file: int, components: frozenset[str]) -> None:
    compact_names = []
    contract_names = []
    if IHC_NAME in periphery:
        compact_names.append(IHC_NAME)
        contract_names.append(IHC_1MS_NAME)
    if SYNAPSE_NAME in periphery:
        compact_names.append(SYNAPSE_NAME)
        contract_names.append(SYNAPSE_1MS_NAME)
    if REDOCKING_NAME in periphery:
        compact_names.append(REDOCKING_NAME)
        contract_names.append(REDOCKING_1MS_NAME)
    periphery.attrs["auxiliary_compact_1ms_arrays"] = ",".join(compact_names)
    periphery.attrs["auxiliary_contract_1ms_arrays"] = ",".join(contract_names)
    periphery.attrs["redocking_checkpoint0_equation"] = REDOCKING_EQUATION
    periphery.attrs["checkpoint0_phonological_substrate_ready"] = "redocking" in components and REDOCKING_NAME in periphery
    h5.attrs["bioear_auxiliary_storage_profile"] = "compact_1ms_" + "_".join(ordered_components(components))
    h5.attrs["bioear_auxiliary_components"] = ",".join(ordered_components(components))
    h5.attrs["bioear_auxiliary_present_components"] = ",".join(
        name
        for name, dataset_name in (
            ("ihc", IHC_NAME),
            ("synapse", SYNAPSE_NAME),
            ("redocking", REDOCKING_NAME),
        )
        if dataset_name in periphery
    )
    h5.attrs["bioear_auxiliary_schema"] = SCRIPT_SCHEMA
    h5.attrs["bioear_auxiliary_generated_at_utc"] = utc_now()
    h5.attrs["bioear_auxiliary_extraction_profile"] = profile
    h5.attrs["bioear_auxiliary_threads_per_file"] = int(threads_per_file)
    h5.attrs["bioear_auxiliary_fibers_per_type_json"] = json.dumps(profile_fiber_counts(profile), sort_keys=True)
    h5.attrs["redocking_checkpoint0_equation"] = REDOCKING_EQUATION
    h5.attrs["checkpoint0_phonological_substrate_ready"] = "redocking" in components and REDOCKING_NAME in periphery


def run(args: argparse.Namespace) -> dict[str, Any]:
    components = parse_components(str(args.components))
    data_root = args.data_root.expanduser().resolve()
    manifest_dirs = discover_manifest_dirs(data_root, args.corpus, language=args.language, include_substrate=args.include_substrate)
    tasks, already_complete, discovery_errors = load_tasks(
        manifest_dirs,
        replace=args.replace_confirmed,
        check_existing=bool(args.check_existing),
        dedupe_realpaths=bool(args.dedupe_realpaths),
        validate_discovery_paths=bool(args.validate_discovery_paths),
    )
    sidecar_tasks, sidecar_already_complete, sidecar_errors = load_sidecar_tasks(
        args.sidecar_root,
        replace=args.replace_confirmed,
        check_existing=bool(args.check_existing),
        dedupe_realpaths=bool(args.dedupe_realpaths),
        validate_discovery_paths=bool(args.validate_discovery_paths),
    )
    tasks.extend(sidecar_tasks)
    already_complete += sidecar_already_complete
    discovery_errors.extend(sidecar_errors)
    if args.limit is not None:
        tasks = tasks[: max(0, int(args.limit))]
    if args.dry_run:
        return {
            "ok": not discovery_errors,
            "schema": SCRIPT_SCHEMA,
            "dry_run": True,
            "check_existing": bool(args.check_existing),
            "components": ",".join(ordered_components(components)),
            "language": str(args.language),
            "dedupe_realpaths": bool(args.dedupe_realpaths),
            "validate_discovery_paths": bool(args.validate_discovery_paths),
            "data_root": str(data_root),
            "manifest_dirs": [str(path) for path in manifest_dirs],
            "sidecar_roots": [str(path.expanduser().resolve()) for path in args.sidecar_root],
            "task_count": len(tasks) + already_complete,
            "already_complete": already_complete,
            "scheduled": len(tasks),
            "discovery_errors": discovery_errors,
        }

    jobs = max(1, int(args.jobs))
    threads_per_file = max(1, int(args.threads_per_file))
    created = 0
    created_full_aux = 0
    redocking_backfilled = 0
    skipped = 0
    failures: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    bytes_added = 0
    completed = 0
    status_counts: dict[str, int] = {}

    if not args.quiet:
        print(
            f"[bioear-aux] manifests={len(manifest_dirs)} already_complete={already_complete} "
            f"sidecar_roots={len(args.sidecar_root)} scheduled={len(tasks)} jobs={jobs} threads_per_file={threads_per_file} "
            f"components={','.join(ordered_components(components))} "
            f"check_existing={bool(args.check_existing)} dedupe_realpaths={bool(args.dedupe_realpaths)} "
            f"progress_fields=created_full_aux,redocking_backfilled,skipped",
            file=sys.stderr,
            flush=True,
        )

    def record(payload: dict[str, Any]) -> None:
        nonlocal created, created_full_aux, redocking_backfilled, skipped, bytes_added
        status = str(payload.get("status", "") or "unknown")
        status_counts[status] = int(status_counts.get(status, 0)) + 1
        if payload.get("ok"):
            if status == "created_redocking_checkpoint0":
                created += 1
                redocking_backfilled += 1
                bytes_added += int(payload.get("bytes_added", 0) or 0)
            elif status.startswith("created"):
                created += 1
                created_full_aux += 1
                bytes_added += int(payload.get("bytes_added", 0) or 0)
            else:
                skipped += 1
            if len(results) < 20:
                results.append(payload)
        else:
            failures.append(payload)

    def progress_line() -> str:
        return (
            f"[bioear-aux] completed={completed}/{len(tasks)} created={created} "
            f"created_full_aux={created_full_aux} redocking_backfilled={redocking_backfilled} "
            f"skipped={skipped} failures={len(failures)}"
        )

    if jobs == 1:
        for task in tasks:
            if STOP_REQUESTED:
                break
            payload = append_aux_worker(task, replace=args.replace_confirmed, threads_per_file=threads_per_file, components=components)
            record(payload)
            completed += 1
            if not args.quiet and (completed == 1 or completed % 25 == 0 or completed == len(tasks) or STOP_REQUESTED):
                print(progress_line(), file=sys.stderr, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=jobs, initializer=ignore_worker_sigint) as executor:
            task_iter = iter(tasks)
            future_to_task: dict[Future[dict[str, Any]], AuxTask] = {}

            def submit_until_full() -> None:
                if STOP_REQUESTED:
                    return
                while len(future_to_task) < jobs:
                    try:
                        task = next(task_iter)
                    except StopIteration:
                        return
                    future_to_task[executor.submit(append_aux_worker, task, replace=args.replace_confirmed, threads_per_file=threads_per_file, components=components)] = task

            submit_until_full()
            while future_to_task:
                done, _pending = wait(future_to_task, timeout=1.0, return_when=FIRST_COMPLETED)
                if not done:
                    continue
                for future in done:
                    future_to_task.pop(future)
                    try:
                        payload = future.result()
                    except Exception as exc:  # noqa: BLE001
                        payload = {"ok": False, "status": "failed", "error": str(exc), "traceback": traceback.format_exc(limit=8)}
                    record(payload)
                    completed += 1
                    if not args.quiet and (completed == 1 or completed % 25 == 0 or completed == len(tasks) or STOP_REQUESTED):
                        print(progress_line(), file=sys.stderr, flush=True)
                submit_until_full()

    interrupted = bool(STOP_REQUESTED and completed < len(tasks))
    return {
        "ok": bool(not failures and not discovery_errors and not interrupted),
        "schema": SCRIPT_SCHEMA,
        "components": ",".join(ordered_components(components)),
        "language": str(args.language),
        "data_root": str(data_root),
        "manifest_dirs": [str(path) for path in manifest_dirs],
        "sidecar_roots": [str(path.expanduser().resolve()) for path in args.sidecar_root],
        "task_count": len(tasks) + already_complete,
        "already_complete": already_complete,
        "scheduled": len(tasks),
        "completed": completed,
        "created": created,
        "created_full_aux": created_full_aux,
        "redocking_backfilled": redocking_backfilled,
        "skipped": skipped,
        "failed": len(failures),
        "interrupted": interrupted,
        "bytes_added": bytes_added,
        "bytes_added_human": human_bytes(bytes_added),
        "status_counts": dict(sorted(status_counts.items())),
        "discovery_errors": discovery_errors,
        "failures": failures[:50],
        "sample_results": results,
        "resume_instruction": "rerun the same command; full rich files are skipped and IHC/synapse-only files backfill redocking.",
    }


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            return f"{amount:.2f} {unit}"
        amount /= 1024.0
    return f"{value} B"


def main() -> int:
    install_signal_handlers()
    args = parse_args()
    payload = run(args)
    emit(payload, json_output=args.json)
    if payload.get("interrupted"):
        return 130
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
