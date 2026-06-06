# Vendored Runtime

This directory is the self-contained native macOS runtime expected by the
aligner scripts:

```text
speech_engine/             ALEX speech-engine runtime
bp_acoustic_recipe/        Brazilian Portuguese acoustic recipe runtime
annotation_validator_chunks/ checksum-protected annotation validator runtime chunks
```

The shell entrypoints discover these paths automatically. `ALEX_SPEECH_ENGINE_ROOT`,
`ALEX_BP_ACOUSTIC_RECIPE_ROOT`, and `ALEX_ANNOTATION_VALIDATOR` are supported as
explicit overrides.

The annotation-validator executable is kept as checksum-protected chunks under
`annotation_validator_chunks/` so source files stay below GitHub-friendly blob
sizes. The portable helpers reassemble it only into ignored local runtime caches
or into the separately packaged macOS application.

Credits and upstream license notices name the third-party projects that power
these neutral ALEX runtime bundles.
