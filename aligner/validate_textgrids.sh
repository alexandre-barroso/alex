#!/usr/bin/env bash
#
# Validate TextGrid output through the bundled no-GUI annotation validator.

set -o pipefail

script_dir=$(
  cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
  pwd -P
)

annotation_validator=${ALEX_ANNOTATION_VALIDATOR:-}

help_message="usage: $0 [options] <wav-file> <textgrid-file> [<wav-file> <textgrid-file> ...]
  Validates generated TextGrid files in console mode.

  options:
    --annotation-validator <path>   annotation validator executable.

  e.g.:
    bash $0 --annotation-validator /path/to/validator demo/coxinha.wav demo/coxinha.TextGrid
"

. "$script_dir/utils/portable.sh" || exit 1
. "$script_dir/utils/parse_options.sh" || exit 1

if [ $# -lt 2 ] || [ $(( $# % 2 )) -ne 0 ] ; then
  printf "%s\n" "$help_message" >&2
  exit 1
fi

annotation_validator_bin=$(portable_find_annotation_validator "$annotation_validator") || {
  echo "$0: error: annotation validator not found; pass --annotation-validator /path/to/validator" >&2
  exit 1
}

while [ $# -gt 0 ] ; do
  wav_file=$(portable_abspath "$1")
  textgrid_file=$(portable_abspath "$2")
  shift 2

  [ ! -f "$wav_file" ] && echo "$0: error: wav file not found: $wav_file" >&2 && exit 1
  [ ! -f "$textgrid_file" ] && echo "$0: error: TextGrid file not found: $textgrid_file" >&2 && exit 1

  "$annotation_validator_bin" \
    --no-pref-files \
    --no-plugins \
    --run "$script_dir/annotation_validator_scripts/validate_textgrid.validator" \
    "$wav_file" "$textgrid_file" || exit 1
done
