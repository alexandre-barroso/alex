#!/usr/bin/env bash

script_dir=$(
  cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
  pwd -P
)

ok=true
python=${PYTHON_BIN:-${PYTHON:-python3}}
locale=${ALIGNER_LOCALE:-pt_BR.UTF-8}
annotation_validator=${ALEX_ANNOTATION_VALIDATOR:-}
require_annotation_validator=false
speech_engine_root=${ALEX_SPEECH_ENGINE_ROOT:-}
bp_acoustic_recipe_root=${ALEX_BP_ACOUSTIC_RECIPE_ROOT:-}
speech_recipe=${ALEX_SPEECH_RECIPE:-auto}

. "$script_dir/portable.sh" || exit 1
. "$script_dir/parse_options.sh" || exit 1

function require_cmd {
  local cmd=$1

  if ! portable_command_exists "$cmd" ; then
    ok=false
    echo "$0: error: $cmd not installed" >&2
  fi
}

function require_python_import {
  local package=$1
  local import_name=$2

  if ! "$python" -c "import $import_name" 2>/dev/null ; then
    ok=false
    echo "$0: error: please install $package for '$python'" >&2
  fi
}

aligner_root=$(portable_abspath "$script_dir/..")
if [ -z "$speech_engine_root" ] && [ -d "$aligner_root/vendor/speech_engine" ] ; then
  speech_engine_root="$aligner_root/vendor/speech_engine"
fi
if [ -z "$bp_acoustic_recipe_root" ] && [ -d "$aligner_root/vendor/bp_acoustic_recipe" ] ; then
  bp_acoustic_recipe_root="$aligner_root/vendor/bp_acoustic_recipe"
fi
if [ -n "$speech_engine_root" ] ; then
  speech_engine_root=$(portable_abspath "$speech_engine_root")
fi
ALEX_SPEECH_ENGINE_ROOT=$speech_engine_root
export ALEX_SPEECH_ENGINE_ROOT

if [ -d "$ALEX_SPEECH_ENGINE_ROOT/tools/openfst-1.8.4/bin" ] ; then
  export PATH="$ALEX_SPEECH_ENGINE_ROOT/tools/openfst-1.8.4/bin:$PATH"
fi

if [ -z "$ALEX_SPEECH_ENGINE_ROOT" ] || [ ! -d "$ALEX_SPEECH_ENGINE_ROOT/egs" ] ; then
  ok=false
  echo "$0: error: please set ALEX_SPEECH_ENGINE_ROOT or install vendor/speech_engine: '$ALEX_SPEECH_ENGINE_ROOT'" >&2
fi

if [ -n "$bp_acoustic_recipe_root" ] ; then
  bp_acoustic_recipe_root=$(portable_abspath "$bp_acoustic_recipe_root")
fi

for f in bash tar curl java gzip gunzip awk sort head tail tee ; do
  require_cmd "$f"
done

if ! portable_command_exists "$python" ; then
  ok=false
  echo "$0: error: python interpreter '$python' not found" >&2
else
  needs_download=false
  if [ -n "${ALIGNER_DIR:-}" ] ; then
    for f in data.tar.gz m2m.model.gz mono.tar.gz fb_nlplib.jar ; do
      if [ ! -f "$ALIGNER_DIR/$f" ] ; then
        needs_download=true
      fi
    done
  else
    needs_download=true
  fi
  if $needs_download && ! portable_command_exists gdown && ! "$python" -c "import gdown" 2>/dev/null ; then
    ok=false
    echo "$0: error: please install gdown executable or gdown for '$python' to download missing model archives" >&2
  fi
  require_python_import numpy numpy
  require_python_import pandas pandas
  require_python_import TextGrid textgrid
  require_python_import Unidecode unidecode
fi

if ! portable_command_exists md5sum && ! portable_command_exists md5 && ! portable_command_exists openssl ; then
  ok=false
  echo "$0: error: need one checksum tool: md5sum, md5, or openssl" >&2
fi

if $require_annotation_validator ; then
  annotation_validator_bin=$(portable_find_annotation_validator "$annotation_validator") || {
    ok=false
    echo "$0: error: annotation validator not found; pass --annotation-validator /path/to/validator" >&2
  }
  if [ -n "${annotation_validator_bin:-}" ] && ! "$annotation_validator_bin" --version >/dev/null 2>&1 ; then
    ok=false
    echo "$0: error: annotation validator is not runnable: '$annotation_validator_bin'" >&2
  fi
fi

if ! portable_locale_exists "$locale" ; then
  fallback_locale=$(portable_select_locale "$locale")
  echo "$0: warn: locale '$locale' not available; runtime will fall back to '$fallback_locale'" >&2
fi

if [ -n "$ALEX_SPEECH_ENGINE_ROOT" ] && [ -d "$ALEX_SPEECH_ENGINE_ROOT/egs" ] ; then
  recipe_selection=$(portable_speech_recipe_source "$ALEX_SPEECH_ENGINE_ROOT" "$bp_acoustic_recipe_root" "$speech_recipe") || {
    ok=false
    recipe_selection=
  }

  if [ -n "$recipe_selection" ] ; then
    recipe_name=${recipe_selection%%:*}
    recipe_workspace=${recipe_selection#*:}
    echo "$0: info: using $recipe_name speech recipe from '$recipe_workspace'" >&2
    for f in "$recipe_workspace/steps" "$recipe_workspace/utils" "$recipe_workspace/path.sh" ; do
      if [ ! -e "$f" ] ; then
        ok=false
        echo "$0: error: missing speech recipe path '$f'" >&2
      fi
    done
  fi

  if [ -n "${recipe_workspace:-}" ] && [ -f "$recipe_workspace/path.sh" ] ; then
    missing_bins=$(
      export ALEX_SPEECH_ENGINE_ROOT
      if [ -d "$ALEX_SPEECH_ENGINE_ROOT/tools/openfst-1.8.4/bin" ] ; then
        export PATH="$ALEX_SPEECH_ENGINE_ROOT/tools/openfst-1.8.4/bin:$PATH"
      fi
      portable_export_engine_compat "$ALEX_SPEECH_ENGINE_ROOT" "$bp_acoustic_recipe_root" "$speech_recipe"
      . "$recipe_workspace/path.sh" >/dev/null 2>&1
      for f in ali-to-phones linear-to-nbest lattice-align-words nbest-to-ctm fstcompile fstarcsort ; do
        command -v "$f" >/dev/null 2>&1 || echo "$f"
      done
    )
    if [ -n "$missing_bins" ] ; then
      ok=false
      echo "$0: error: missing speech-engine binaries after sourcing path.sh: $missing_bins" >&2
    fi
  fi
fi

$ok && echo "$0: info: success!" || exit 1
