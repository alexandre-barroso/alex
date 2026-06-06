# aligner

`aligner` is the repository-local Brazilian Portuguese forced-alignment backend.
It takes matching WAV/TXT pairs and writes TextGrid files beside the source WAV
files. It is CLI-first so it can run from scripts, the GUI, and batch jobs.

The active runtime is self-contained inside this folder:

```text
aligner.sh              single WAV/TXT pair
aligner_batch.sh        sequential WAV/TXT argument pairs
aligner_backend.sh      backend wrapper with vendored defaults
align_folder.py         recursive same-stem WAV/TXT scanner
align_folder_chunked.py high-throughput multi-utterance chunk runner
clean_textgrids.py      post-hoc TextGrid label cleaner
bin/annotation-validator stable annotation-validator launcher
local/                  TextGrid conversion helpers
utils/                  shell portability, dependency, and model helpers
conf/                   feature configs
demo/                   small validator-checkable examples
vendor/                 neutral ALEX speech-engine and validator runtime
.venv/                  Python runtime
.aligner-cache/         acoustic resources, dictionaries, and NLP jar
```

## Output Contract

For each input pair `path/name.wav` and `path/name.txt`, the default output is:

```text
path/name.TextGrid
```

If that file already exists, batch entrypoints use suffixes such as
`name_1.TextGrid`, `name_2.TextGrid`, and so on unless `--overwrite` is passed.
Folder runners skip existing same-stem TextGrids by default.

All TextGrid labels are lowercased, punctuation/symbol/control characters are
removed, whitespace is collapsed, silence phones are blank, and phonetic tiers
are emitted in IPA.

## Quick Checks

```bash
python3 align_folder.py demo --dry-run --no-skip-existing
bash aligner_backend.sh --python .venv/bin/python --aligner-dir .aligner-cache --am-tag mono --annotation-validation false --overwrite true demo/coxinha.wav demo/coxinha.txt
.venv/bin/python clean_textgrids.py demo --dry-run
```

On macOS, the scripts automatically prefer the vendored runtime when present:

```text
vendor/speech_engine
vendor/bp_acoustic_recipe
vendor/annotation_validator_chunks
.venv/bin/python
.aligner-cache
```

If Homebrew OpenJDK is installed, `align_folder.py` also prepends its `bin`
directory for the annotation support jar.

The default MFCC config accepts higher-rate WAV files by allowing the speech
engine to downsample to the model sample rate during feature extraction.

## Batch Use

Small sequential batch:

```bash
bash aligner_batch.sh mono \
  demo/coxinha.wav demo/coxinha.txt \
  demo/M-001.wav demo/M-001.txt
```

Recursive folder scan:

```bash
python3 align_folder.py /path/to/corpus --am-tag mono
```

Large corpora:

```bash
python3 align_folder_chunked.py /path/to/corpus --am-tag mono --chunk-size 1000 --jobs 4
```

Annotation validation is intentionally off for folder and chunked runs because
the console validator can abort after a TextGrid has already been written. Use
`--annotation-validation` only for small manual QA batches.

## Demo

The demo folder contains three WAV/TXT pairs and generated TextGrids:

```text
demo/coxinha.*
demo/M-001.*
demo/annotation-support.*
```

Open the TextGrids in your annotation editor to inspect alignment tiers manually.
