from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from .extractor import (
    AUTO_EXTRACTION_PROFILE,
    CANONICAL_EXTRACTION_PROFILE,
    EXTRACTION_PROFILES,
    BioEarError,
    build_canonical_corpus,
    detect_homogeneous_sidecar_profile,
    doctor_payload,
    extract_biological_ear,
    request_graceful_stop,
    validate_bioear_h5,
)


app = typer.Typer(no_args_is_help=True, help="Biological auditory-periphery extraction utilities.")
BUILD_PROFILES = (AUTO_EXTRACTION_PROFILE, *EXTRACTION_PROFILES)
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = Path(os.environ.get("CONPHON_DATA_ROOT", REPO_ROOT / "data")).expanduser()
DEFAULT_BUILD_DATA_JOBS = max(1, int(os.environ.get("CONPHON_BUILD_DATA_JOBS", "8")))
CORPUS_ROOTS = {
    "portuguese_40": "corpus_portuguese_40",
    "portuguese_80": "corpus_portuguese_80",
    "portuguese_120": "corpus_portuguese_120",
    "portuguese_160": "corpus_portuguese_160",
    "mandarin_40": "corpus_mandarin_40",
    "english_40": "corpus_english_40",
}
_BIOEAR_CLI_CONTRACT_ERRORS = (
    BioEarError,
    OSError,
    ImportError,
    RuntimeError,
    TypeError,
    ValueError,
    json.JSONDecodeError,
)


def canonical_corpus_root(corpus: str) -> Path:
    key = corpus.strip().lower().replace("-", "_")
    try:
        dirname = CORPUS_ROOTS[key]
    except KeyError as exc:
        supported = ", ".join(sorted(CORPUS_ROOTS))
        raise typer.BadParameter(f"unsupported corpus {corpus!r}; expected one of: {supported}") from exc
    return DATA_ROOT / dirname


def _is_under_data_root(path: Path) -> bool:
    try:
        Path(path).expanduser().resolve(strict=False).relative_to(DATA_ROOT.resolve(strict=False))
        return True
    except ValueError:
        return False


def _require_canonical_data_root(path: Path, *, role: str) -> None:
    if not _is_under_data_root(path):
        return
    if not DATA_ROOT.exists():
        raise BioEarError(
            f"ConPhonData data root is not mounted at {DATA_ROOT}; refusing to create empty data directories"
        )
    if not path.exists():
        raise BioEarError(
            f"{role} {path} is unavailable under the protected external data root; "
            "mount/populate ConPhonData instead of creating an empty corpus folder"
        )


def _handle_graceful_stop(signum: int, _frame: Any) -> None:
    request_graceful_stop()
    try:
        signal_name = signal.Signals(signum).name
    except ValueError:
        signal_name = str(signum)
    print(f"[bioear] {signal_name}: graceful stop requested; finishing active bundle tasks only.", file=sys.stderr, flush=True)


def install_signal_handlers() -> None:
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, _handle_graceful_stop)
    signal.signal(signal.SIGTERM, _handle_graceful_stop)


@app.command("doctor")
def doctor_command(
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    payload = doctor_payload()
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        typer.echo("ok" if payload["ok"] else payload.get("error", "bioear doctor failed"))
    if not payload["ok"]:
        raise typer.Exit(1)


@app.command("extract-pair")
def extract_pair_command(
    wav: Annotated[Path, typer.Option("--wav", help="Input 16 kHz WAV.")],
    textgrid: Annotated[Path, typer.Option("--textgrid", help="TextGrid with four standard non-empty layers, or Mandarin hanzis/pinyings/phones layers.")],
    out: Annotated[Path | None, typer.Option("--out", help="Optional output HDF5 path.")] = None,
    profile: Annotated[str, typer.Option("--profile", help=f"BioEar extraction profile: {', '.join(EXTRACTION_PROFILES)}.")] = CANONICAL_EXTRACTION_PROFILE,
    replace_confirmed: Annotated[bool, typer.Option("--replace-confirmed", help="Replace an existing invalid or valid HDF5.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="Suppress per-CF progress.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    try:
        payload = extract_biological_ear(wav, textgrid, out, replace=replace_confirmed, progress=not quiet, profile=profile)
    except _BIOEAR_CLI_CONTRACT_ERRORS as exc:
        payload = {"ok": False, "error": str(exc), "wav": str(wav), "textgrid": str(textgrid)}
        if json_output:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            typer.echo(payload["error"])
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        typer.echo(payload["output"])


@app.command("validate")
def validate_command(
    path: Annotated[Path, typer.Argument(help="Bioear HDF5 path.")],
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    payload = validate_bioear_h5(path)
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        typer.echo("ok" if payload["ok"] else str(payload.get("errors") or payload.get("error")))
    if not payload["ok"]:
        raise typer.Exit(1)


@app.command("detect-profile")
def detect_profile_command(
    root: Annotated[Path, typer.Option("--input", help="Numbered WAV/TextGrid/BioEar sidecar corpus root.")],
    limit: Annotated[int | None, typer.Option("--limit", help="Optional maximum folders to inspect.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    payload = detect_homogeneous_sidecar_profile(root, limit=limit)
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        typer.echo(str(payload.get("profile") or payload.get("errors")))
    if not payload["ok"]:
        raise typer.Exit(1)


@app.command("build-data")
def build_data_command(
    root: Annotated[Path | None, typer.Option("--input", help="Numbered WAV/TextGrid/_bioear.h5 corpus root, with optional TXT transcripts. Defaults to the selected corpus root.")] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Output root that will receive bioear/ manifest, indexes, and records. Defaults to the selected corpus root.")] = None,
    corpus: Annotated[str, typer.Option("--corpus", help="Canonical corpus root: portuguese_40/80/120/160, mandarin_40, or english_40.")] = "portuguese_160",
    profile: Annotated[
        str,
        typer.Option("--profile", help=f"BioEar profile to build: {', '.join(BUILD_PROFILES)}."),
    ] = AUTO_EXTRACTION_PROFILE,
    start: Annotated[int | None, typer.Option("--start", help="First numbered folder to include.")] = None,
    end: Annotated[int | None, typer.Option("--end", help="Last numbered folder to include.")] = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Maximum selected folders.")] = None,
    replace_confirmed: Annotated[bool, typer.Option("--replace-confirmed", help="Replace existing canonical records/indexes.")] = False,
    jobs: Annotated[int, typer.Option("--jobs", help="Parallel workers for canonical validation, record install, hashing, and indexing.")] = DEFAULT_BUILD_DATA_JOBS,
    copy_mode: Annotated[str, typer.Option("--copy-mode", help="Canonical HDF5 install mode: auto, clone, copy, or symlink.")] = "auto",
    quiet: Annotated[bool, typer.Option("--quiet", help="Suppress extraction/build progress.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    install_signal_handlers()
    if profile not in BUILD_PROFILES:
        raise typer.BadParameter(f"expected one of {BUILD_PROFILES}")
    if copy_mode not in {"auto", "clone", "copy", "symlink"}:
        raise typer.BadParameter("copy-mode must be one of: auto, clone, copy, symlink")
    selected_root = canonical_corpus_root(corpus)
    input_root = root if root is not None else selected_root
    output_root = output if output is not None else selected_root
    _require_canonical_data_root(input_root, role="input corpus root")
    _require_canonical_data_root(output_root, role="output corpus root")
    try:
        payload = build_canonical_corpus(
            input_root,
            output_root=output_root,
            replace=replace_confirmed,
            limit=limit,
            start=start,
            end=end,
            progress=not quiet,
            command_provenance=["python", "-m", "conphon", "bioear", "build-data"],
            profile=profile,
            jobs=jobs,
            copy_mode=copy_mode,
        )
    except _BIOEAR_CLI_CONTRACT_ERRORS as exc:
        payload = {"ok": False, "error": str(exc), "input": str(input_root), "output": str(output_root), "profile": profile}
        if json_output:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            typer.echo(payload["error"])
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        typer.echo(str(payload.get("base_dir") or payload.get("output_root") or selected_root / "bioear"))
    if payload.get("interrupted"):
        raise typer.Exit(130)
    if not payload.get("ok", False):
        raise typer.Exit(1)
