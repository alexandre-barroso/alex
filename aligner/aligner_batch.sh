#!/usr/bin/env bash
#
# Sequential batch runner for aligner wav+txt pairs.

set -o pipefail

script_dir=$(
  cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
  pwd -P
)

beam=10
retry_beam=40
python=${PYTHON_BIN:-${PYTHON:-python3}}
locale=${ALIGNER_LOCALE:-pt_BR.UTF-8}
annotation_validator=${ALEX_ANNOTATION_VALIDATOR:-}
annotation_validation=false
aligner_dir=${ALIGNER_DIR:-}
speech_engine_root=${ALEX_SPEECH_ENGINE_ROOT:-}
bp_acoustic_recipe_root=${ALEX_BP_ACOUSTIC_RECIPE_ROOT:-}
speech_recipe=${ALEX_SPEECH_RECIPE:-auto}
output_dir=
work_dir=${ALIGNER_WORK_DIR:-}
continue_on_error=false
overwrite=false

help_message="usage: $0 [options] <am-tag> <wav-file> <txt-file> [<wav-file> <txt-file> ...]
  Runs aligner sequentially over one or more wav+txt pairs.

  options:
    --beam <n>                 alignment beam, default: $beam
    --retry-beam <n>           retry beam, default: $retry_beam
    --aligner-dir <dir>       model/resource cache directory
    --python <python3>         Python interpreter, default: $python
    --locale <locale>          collation locale, default: $locale
    --speech-engine-root <dir>         speech engine root; defaults to vendor/speech_engine
    --bp-acoustic-recipe-root <dir>    BP acoustic recipe root; also accepted via ALEX_BP_ACOUSTIC_RECIPE_ROOT
    --speech-recipe <name>             auto, bp, or generic; default: $speech_recipe
    --annotation-validator <path>      annotation validator executable for console validation
    --annotation-validation <bool>     validate each TextGrid with the annotation validator
    --output-dir <dir>         optional flat TextGrid output directory;
                               default: same directory as each <wav-file>
    --work-dir <dir>           writable speech recipe workspace; defaults to TMPDIR
    --continue-on-error <bool> keep aligning later pairs after a failed pair
    --overwrite <bool>         replace <wav-stem>.TextGrid instead of adding
                               _1, _2, ... suffixes when needed

  e.g.:
    ALEX_SPEECH_ENGINE_ROOT=\$HOME/alex-speech-engine bash $0 mono demo/coxinha.wav demo/coxinha.txt demo/M-001.wav demo/M-001.txt
"

. "$script_dir/utils/portable.sh" || exit 1
. "$script_dir/utils/parse_options.sh" || exit 1

function usage {
  printf "%s\n" "$help_message"
}

if [ $# -lt 3 ] ; then
  usage
  exit 1
fi

am_tag=$1
shift

if [ $(( $# % 2 )) -ne 0 ] ; then
  echo "$0: error: expected wav/txt arguments in pairs" >&2
  usage
  exit 1
fi

if [ -n "$output_dir" ] ; then
  output_dir=$(portable_abspath "$output_dir")
  mkdir -p "$output_dir" || exit 1
fi

if [ -z "$speech_engine_root" ] && [ -d "$script_dir/vendor/speech_engine" ] ; then
  speech_engine_root="$script_dir/vendor/speech_engine"
fi
if [ -z "$bp_acoustic_recipe_root" ] && [ -d "$script_dir/vendor/bp_acoustic_recipe" ] ; then
  bp_acoustic_recipe_root="$script_dir/vendor/bp_acoustic_recipe"
fi

runner_opts=(--beam "$beam" --retry-beam "$retry_beam" --python "$python" --locale "$locale" --speech-recipe "$speech_recipe")
if [ -n "$speech_engine_root" ] ; then
  runner_opts+=(--speech-engine-root "$speech_engine_root")
fi
if [ -n "$aligner_dir" ] ; then
  runner_opts+=(--aligner-dir "$aligner_dir")
fi
if [ -n "$bp_acoustic_recipe_root" ] ; then
  runner_opts+=(--bp-acoustic-recipe-root "$bp_acoustic_recipe_root")
fi
if [ -n "$work_dir" ] ; then
  runner_opts+=(--work-dir "$work_dir")
fi
validator_opts=()
if [ -n "$annotation_validator" ] ; then
  validator_opts+=(--annotation-validator "$annotation_validator")
fi

function next_textgrid_path {
  local dir=$1
  local stem=$2
  local target="$dir/$stem.TextGrid"
  local idx=1

  if $overwrite || [ ! -e "$target" ] ; then
    printf "%s\n" "$target"
    return 0
  fi

  while [ -e "$dir/${stem}_$idx.TextGrid" ] ; do
    idx=$((idx + 1))
  done
  printf "%s\n" "$dir/${stem}_$idx.TextGrid"
}

function make_temp_output_dir {
  local base=${TMPDIR:-/tmp}
  mktemp -d "$base/aligner-batch.XXXXXX"
}

failures=0
total=0

while [ $# -gt 0 ] ; do
  wav_file=$1
  txt_file=$2
  shift 2
  total=$((total + 1))

  wav_abs=$(portable_abspath "$wav_file")
  txt_abs=$(portable_abspath "$txt_file")
  utt_id=$(basename "$wav_abs")
  utt_id=${utt_id%.wav}
  if [ -n "$output_dir" ] ; then
    pair_output_dir="$output_dir"
  else
    pair_output_dir=$(dirname "$wav_abs")
  fi
  target=$(next_textgrid_path "$pair_output_dir" "$utt_id")

  mkdir -p "$pair_output_dir" || exit 1
  tmp_output_dir=$(make_temp_output_dir) || exit 1
  tmp_target="$tmp_output_dir/$utt_id.TextGrid"

  portable_log "$0: aligning pair $total: $wav_abs + $txt_abs"
  if bash "$script_dir/aligner.sh" "${runner_opts[@]}" --output-dir "$tmp_output_dir" "$wav_abs" "$txt_abs" "$am_tag" ; then
    if [ ! -s "$tmp_target" ] ; then
      echo "$0: error: expected TextGrid '$tmp_target' was not created" >&2
      failures=$((failures + 1))
      rm -rf "$tmp_output_dir"
      $continue_on_error || exit 1
      continue
    fi
    mv -f "$tmp_target" "$target" || exit 1
    rm -rf "$tmp_output_dir"
    if $annotation_validation ; then
      bash "$script_dir/validate_textgrids.sh" "${validator_opts[@]}" "$wav_abs" "$target" || exit 1
    fi
    portable_log "$0: wrote $target"
  else
    failures=$((failures + 1))
    rm -rf "$tmp_output_dir"
    $continue_on_error || exit 1
  fi
done

if [ "$failures" -gt 0 ] ; then
  echo "$0: error: $failures of $total pair(s) failed" >&2
  exit 1
fi

if [ -n "$output_dir" ] ; then
  portable_log "$0: success! aligned $total pair(s). TextGrid output: $output_dir"
else
  portable_log "$0: success! aligned $total pair(s). TextGrid files were written beside their WAV files"
fi
