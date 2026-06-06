# Changelog

All notable changes to ALEX are documented here.

## 2.0 - 2026-06-06

### Added

- Standalone macOS app bundle for ALEX, including the SwiftUI interface, Python runtime, Python packages, Java runtime, alignment assets, and BioEar backend code.
- Portuguese audio/TXT alignment workflow that creates TextGrid sidecars beside source files.
- Recursive corpus scanning for large folders without loading full corpora into GUI memory.
- Audio normalization pipeline for readable audio formats, converting inputs to mono 16 kHz WAV before alignment or BioEar extraction.
- Canonical Portuguese TextGrid tier creation with `phonemes`, `words`, `syllables`, and `utterance`.
- Existing TextGrid policy prompt for Portuguese alignment, allowing users to continue only missing files or replace existing TextGrids.
- Language-agnostic BioEar extraction for same-stem audio, TXT, and TextGrid trios.
- Smart TextGrid tier detection for `phonemes` or `phones`, `words`, `syllables` or `syl`, and optional `sentence` or `utterance`.
- TextGrid standardization wizard for recursively scanning, mapping, and renaming tier names with backups.
- Balanced-rich BioEar output with rate neurograms, spike neurograms, IHC receptor potential, synapse drive, and redocking time.
- Restartable BioEar enrichment CLI that skips complete rich files and backfills redocking when needed.
- Bilingual Portuguese/English GUI with localized labels, sheets, alerts, help, and about text.
- Professional app packaging script with cache cleanup, bundled dependency path rewriting, and ad-hoc signing.
- Demo corpus smoke tests for Portuguese TextGrid creation and rich BioEar output.

### Changed

- ALEX now writes scientific outputs as sidecars next to original files instead of redirecting them into detached build folders.
- Long-running work is executed through CLI subprocesses under the GUI, with progress streamed back to the interface.
- Runtime and vendor folder names use neutral operational naming; third-party project names are reserved for credits and license notices.
- Repository ignore rules keep generated H5 files, app bundles, caches, extracted alignment models, and build products out of source control.

### Verified

- Swift package tests pass.
- Python CLI and runtime-path tests pass.
- The packaged `ALEX.app` launches on macOS.
- A copied `ALEX.app` outside the repository can create a TextGrid, build a balanced BioEar H5, append IHC/synapse/redocking, and validate finite H5 arrays using only bundled resources.
