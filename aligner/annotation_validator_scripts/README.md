# Annotation Validator Backend Files

This directory contains annotation-validator console-mode scripts used by the native backend.
The shell entrypoint is `../aligner_backend.sh`; it runs aligner from CLI
arguments and validates generated TextGrids with the annotation validator using `--run`.

The stable launcher is `../bin/annotation-validator`. It finds `ALEX_ANNOTATION_VALIDATOR`,
`../vendor/annotation_validator_runtime/annotation_validator`, `/path/to/validator`.

`aligner_pair.validator` is the annotation-validator wrapper for one pair. It exposes
`speech_engine_root`, optional `bp_acoustic_recipe_root`, `speech_recipe`, `python_bin`,
`model_cache_dir`, `acoustic_model`, `wav_file`, and `txt_file`.

Example:

```bash
../bin/annotation-validator --run validate_textgrid.validator ../demo/coxinha.wav ../demo/coxinha.TextGrid
```
