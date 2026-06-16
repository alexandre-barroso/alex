# ALEX

ALEX is a standalone macOS application for TextGrid **al**ignment and BioEar **ex**traction (aka, **al** + **ex** = alex). It is designed for phonologists and phoneticians who need a local, production-oriented tool that can prepare corpus folders without requiring command-line knowledge.

Version: 2.0

## What ALEX Does

ALEX has two primary workflows:

- Portuguese alignment: create `.TextGrid` files from same-stem audio and `.txt` transcription pairs.
- BioEar extraction: create balanced-rich BioEar `.h5` files from same-stem audio, `.txt`, and `.TextGrid` trios for any language whose TextGrid tiers can be identified.

Scientific outputs are written as sidecars in the same folder as the source files. ALEX does not move a corpus into a detached output directory.

## Input Rules

### Portuguese Alignment

Portuguese alignment accepts recursive folders containing pairs such as:

```text
sample.wav
sample.txt
```

Readable audio formats are accepted, including WAV, FLAC, MP3, M4A, AIFF, CAF, OGG, and OPUS. ALEX converts readable audio to mono 16 kHz WAV before alignment.

Portuguese TextGrids are created with canonical tier names from the start:

```text
phonemes/phones
words
syllables
utterance
```

If TextGrids already exist, the GUI asks whether to continue only where TextGrids are missing or replace existing TextGrids with fresh canonical output.

### BioEar Extraction

BioEar extraction accepts recursive folders containing trios such as:

```text
sample.wav
sample.txt
sample.TextGrid
```

Audio is converted to mono 16 kHz WAV before BioEar extraction when needed. The resulting H5 is written beside the source files:

```text
sample_bioear.h5
```

## TextGrid Tier Detection

BioEar extraction is language-agnostic once tier roles can be identified. Preferred tier names are:

```text
phonemes or phones
words
syllables or syl
sentence or utterance
```

Tier order is secondary to explicit names. If the sentence or utterance tier is absent, ALEX synthesizes a single utterance interval for the file. Each audio file should contain one sentence or utterance.

For TextGrids with inconsistent tier names, ALEX provides a standardization wizard that scans recursively, suggests mappings, lets the user choose tier roles, and applies canonical names with backups.

## BioEar Output

ALEX 2.0 targets balanced-rich BioEar files:

- Balanced base profile: 64 characteristic frequencies, HSR/MSR/LSR fiber groups, 1 ms rate neurograms, and 1 ms spike neurograms.
- Rich enrichment: IHC receptor potential, synapse drive, and redocking time.
- Restartability: complete rich files are skipped, and files that already contain IHC/synapse can be backfilled with redocking.

Base balanced H5 files are valid intermediate checkpoints. They become final training artifacts only when IHC, synapse drive, and redocking are present.

## GUI Design

The GUI is intentionally a progress and orchestration layer over CLI tools. It does not load large audio or HDF5 corpora into Swift memory. Folder scans run away from the main UI thread, previews are bounded, TextGrid standardization streams file walks, and long jobs run as subprocesses with streamed progress.

The interface is bilingual in Portuguese and English. The language toggle changes labels, menus, help text, alerts, warnings, sheets, and popups. Technical contract names such as `TextGrid`, `BioEar`, `IHC`, `redocking`, and canonical tier names remain literal.

## Repository Layout

```text
aligner/                  Portuguese alignment runtime and recipes
demos/                    Small demo input folders
macos/ConPhonAligner/     SwiftPM macOS app and GUI tests
src/conphon/bioear/       ALEX-local BioEar backend subset
CHANGELOG.md              Release history
```

Generated app bundles, H5 outputs, extracted model caches, Python caches, and build products are ignored.

## Development Checks

Run Swift tests:

```bash
swift test --package-path macos/ConPhonAligner
```

Run Python tests:

```bash
python -m pytest -q macos/ConPhonAligner/TestsPython
```

Useful CLI smoke checks:

```bash
python macos/ConPhonAligner/Tools/extract_bioear.py run \
  --input /path/to/trios \
  --profile balanced \
  --json

python macos/ConPhonAligner/Tools/append_bioear_aux.py \
  --sidecar-root /path/to/trios \
  --jobs 8 \
  --threads-per-file 1 \
  --json
```

## Packaging Notes

See the `Releases` to download the ready-to-use app in MacOS (arm64). ALEX is part of my PhD project `ConPhon`.

## License

ALEX is released under the MIT License. See `LICENSE`. I would also like to thank the creators of the `brucezilany` backend module, the creators of the open source ecosystem `Kaldi` and `Kaldi-BR / Grupo FalaBrasil` backend modules and the creators of `Praat`. Additional thanks to the communities that maintain `OpenFST`, `NumPy`, `SciPy`, `h5py` and `SoundFile`. This package and repo would not be possible without relying in part on their own work -- and I thank them profusely and the open source community in general, as this package would be much harder to make if it were not for their efforts combined in open science frameworks. ALEX is also open source, and you can edit, modify, implement parts of the code on your own package and use it at will.

### Reference

```bibtex
@misc{barroso2026alexalignerextractor,
  author       = {Barroso, A. M.},
  title        = {ALEX: Aligner and Extractor},
  year         = {2026},
  howpublished = {Computer program. Registration no. BR5120260042372},
  note         = {Registered on June 16, 2026. National Institute of Industrial Property (INPI)}
}
```

