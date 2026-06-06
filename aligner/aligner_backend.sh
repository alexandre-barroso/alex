#!/usr/bin/env bash
#
# CLI-first ALEX alignment backend.

set -o pipefail

script_dir=$(
  cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
  pwd -P
)

am_tag=
beam=10
retry_beam=40
python=${PYTHON_BIN:-${PYTHON:-python3}}
locale=${ALIGNER_LOCALE:-pt_BR.UTF-8}
annotation_validator=${ALEX_ANNOTATION_VALIDATOR:-"$script_dir/bin/annotation-validator"}
annotation_validation=true
aligner_dir=${ALIGNER_DIR:-}
speech_engine_root=${ALEX_SPEECH_ENGINE_ROOT:-}
bp_acoustic_recipe_root=${ALEX_BP_ACOUSTIC_RECIPE_ROOT:-}
speech_recipe=${ALEX_SPEECH_RECIPE:-auto}
output_dir=
work_dir=${ALIGNER_WORK_DIR:-}
continue_on_error=false
overwrite=false

help_message="usage: $0 [options] <wav-file> <txt-file> [<wav-file> <txt-file> ...]
  Backend automation entrypoint for sequential alignment runs.

  options:
    --am-tag <tag>             Acoustic model tag: mono, tri1b, tri1, tri2b, tri3b, tdnn
    --speech-engine-root <dir>         speech engine root; defaults to vendor/speech_engine
    --bp-acoustic-recipe-root <dir>    BP acoustic recipe root; also accepted via ALEX_BP_ACOUSTIC_RECIPE_ROOT
    --speech-recipe <name>             auto, bp, or generic; default: $speech_recipe
    --python <python3>         Python interpreter, default: $python
    --aligner-dir <dir>       model/resource cache directory
    --locale <locale>          collation locale, default: $locale
    --beam <n>                 alignment beam, default: $beam
    --retry-beam <n>           retry beam, default: $retry_beam
    --annotation-validator <path>      annotation validator executable, default: $annotation_validator
    --annotation-validation <bool>     validate each TextGrid with the annotation validator, default: $annotation_validation
    --output-dir <dir>         optional flat TextGrid output directory
    --work-dir <dir>           writable speech recipe workspace; defaults to TMPDIR
    --continue-on-error <bool> keep aligning later pairs after a failed pair
    --overwrite <bool>         replace <wav-stem>.TextGrid instead of suffixing

  e.g.:
    bash $0 --speech-engine-root \$HOME/alex-speech-engine --python .venv/bin/python --am-tag mono demo/coxinha.wav demo/coxinha.txt
"

. "$script_dir/utils/portable.sh" || exit 1
. "$script_dir/utils/parse_options.sh" || exit 1

if [ -z "$am_tag" ] ; then
  echo "$0: error: --am-tag is required" >&2
  printf "%s\n" "$help_message" >&2
  exit 1
fi

if [ $# -lt 2 ] || [ $(( $# % 2 )) -ne 0 ] ; then
  printf "%s\n" "$help_message" >&2
  exit 1
fi

if [ -z "$speech_engine_root" ] && [ -d "$script_dir/vendor/speech_engine" ] ; then
  speech_engine_root="$script_dir/vendor/speech_engine"
fi
if [ -z "$bp_acoustic_recipe_root" ] && [ -d "$script_dir/vendor/bp_acoustic_recipe" ] ; then
  bp_acoustic_recipe_root="$script_dir/vendor/bp_acoustic_recipe"
fi

if [ -z "$speech_engine_root" ] ; then
  echo "$0: error: --speech-engine-root, ALEX_SPEECH_ENGINE_ROOT, or vendor/speech_engine is required" >&2
  exit 1
fi

speech_engine_root=$(portable_abspath "$speech_engine_root")
if [ -n "$bp_acoustic_recipe_root" ] ; then
  bp_acoustic_recipe_root=$(portable_abspath "$bp_acoustic_recipe_root")
fi
export ALEX_SPEECH_ENGINE_ROOT=$speech_engine_root
export ALEX_BP_ACOUSTIC_RECIPE_ROOT=$bp_acoustic_recipe_root
export ALEX_SPEECH_RECIPE=$speech_recipe
portable_export_engine_compat "$ALEX_SPEECH_ENGINE_ROOT" "$ALEX_BP_ACOUSTIC_RECIPE_ROOT" "$ALEX_SPEECH_RECIPE"

if [ -d "$ALEX_SPEECH_ENGINE_ROOT/tools/openfst-1.8.4/bin" ] ; then
  export PATH="$ALEX_SPEECH_ENGINE_ROOT/tools/openfst-1.8.4/bin:$PATH"
fi

check_opts=(--python "$python" --locale "$locale" --speech-recipe "$speech_recipe")
annotation_validator_bin=
if $annotation_validation ; then
  annotation_validator_bin=$(portable_find_annotation_validator "$annotation_validator") || {
    echo "$0: error: annotation validator not found; pass --annotation-validator /path/to/validator" >&2
    exit 1
  }
  check_opts+=(--annotation-validator "$annotation_validator_bin" --require-annotation-validator true)
else
  check_opts+=(--require-annotation-validator false)
fi
if [ -n "$bp_acoustic_recipe_root" ] ; then
  check_opts+=(--bp-acoustic-recipe-root "$bp_acoustic_recipe_root")
fi
ALEX_SPEECH_ENGINE_ROOT=$speech_engine_root ALEX_BP_ACOUSTIC_RECIPE_ROOT=$bp_acoustic_recipe_root ALEX_SPEECH_RECIPE=$speech_recipe \
  bash "$script_dir/utils/check_dependencies.sh" "${check_opts[@]}" || exit 1

batch_opts=(
  --beam "$beam"
  --retry-beam "$retry_beam"
  --python "$python"
  --locale "$locale"
  --speech-recipe "$speech_recipe"
  --annotation-validation "$annotation_validation"
  --continue-on-error "$continue_on_error"
  --overwrite "$overwrite"
)

if [ -n "$annotation_validator_bin" ] ; then
  batch_opts+=(--annotation-validator "$annotation_validator_bin")
fi
if [ -n "$aligner_dir" ] ; then
  batch_opts+=(--aligner-dir "$aligner_dir")
fi
if [ -n "$bp_acoustic_recipe_root" ] ; then
  batch_opts+=(--bp-acoustic-recipe-root "$bp_acoustic_recipe_root")
fi
if [ -n "$output_dir" ] ; then
  batch_opts+=(--output-dir "$output_dir")
fi
if [ -n "$work_dir" ] ; then
  batch_opts+=(--work-dir "$work_dir")
fi

ALEX_SPEECH_ENGINE_ROOT=$speech_engine_root ALEX_BP_ACOUSTIC_RECIPE_ROOT=$bp_acoustic_recipe_root ALEX_SPEECH_RECIPE=$speech_recipe \
  bash "$script_dir/aligner_batch.sh" "${batch_opts[@]}" "$am_tag" "$@"
