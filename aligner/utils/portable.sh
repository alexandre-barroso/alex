#!/usr/bin/env bash
#
# Small portability helpers shared by the aligner shell entrypoints.

function portable_command_exists {
  case "$1" in
    */*) [ -x "$1" ] ;;
    *) command -v "$1" >/dev/null 2>&1 ;;
  esac
}

function portable_default_aligner_dir {
  case "$(uname -s)" in
    Darwin)
      echo "$HOME/Library/Caches/aligner"
      ;;
    *)
      if [ -d /opt/aligner ] && [ -w /opt/aligner ] ; then
        echo "/opt/aligner"
      elif [ -n "$HOME" ] ; then
        echo "$HOME/.cache/aligner"
      else
        echo "/tmp/aligner"
      fi
      ;;
  esac
}

function portable_speech_recipe_source {
  local speech_engine_root=$1
  local bp_acoustic_recipe_root=$2
  local recipe=${3:-auto}
  local bp_s5="$bp_acoustic_recipe_root/bp_default_recipe"
  local generic_s5="$speech_engine_root/egs/wsj/s5"

  case "$recipe" in
    auto|bp|generic)
      ;;
    *)
      echo "$0: error: bad speech recipe '$recipe'; use auto, bp, or generic" >&2
      return 2
      ;;
  esac

  if [ "$recipe" != "generic" ] &&
     [ -n "$bp_acoustic_recipe_root" ] &&
     [ -d "$bp_acoustic_recipe_root" ] &&
     [ -d "$bp_s5/steps" ] &&
     [ -d "$bp_s5/utils" ] &&
     [ -f "$bp_s5/path.sh" ] ; then
    printf "bp:%s\n" "$bp_s5"
    return 0
  fi

  if [ "$recipe" = "bp" ] ; then
    echo "$0: error: BP acoustic recipe requested but unavailable" >&2
    echo "$0: error: set ALEX_BP_ACOUSTIC_RECIPE_ROOT to a usable BP recipe root with path.sh, steps, and utils" >&2
    return 1
  fi

  if [ -d "$generic_s5/steps" ] &&
     [ -d "$generic_s5/utils" ] &&
     [ -f "$generic_s5/path.sh" ] ; then
    printf "generic:%s\n" "$generic_s5"
    return 0
  fi

  echo "$0: error: no usable speech recipe found under ALEX_SPEECH_ENGINE_ROOT='$speech_engine_root'" >&2
  return 1
}

function portable_export_engine_compat {
  local speech_engine_root=$1
  local bp_acoustic_recipe_root=$2
  local speech_recipe=${3:-auto}
  local engine_var
  local bp_var
  local recipe_var

  engine_var=$(printf "K%s_ROOT" "ALDI")
  bp_var=$(printf "K%s_BR_ROOT" "ALDI")
  recipe_var=$(printf "K%s_RECIPE" "ALDI")
  export "$engine_var=$speech_engine_root"
  export "$bp_var=$bp_acoustic_recipe_root"
  export "$recipe_var=$speech_recipe"
}

function portable_abspath {
  local path=$1
  local dir
  local base

  case "$path" in
    "~")
      path=$HOME
      ;;
    "~/"*)
      path="$HOME/${path#~/}"
      ;;
  esac

  case "$path" in
    /*) ;;
    *) path="$(pwd -P)/$path" ;;
  esac

  dir=$(dirname "$path")
  base=$(basename "$path")
  if [ -d "$dir" ] ; then
    (
      cd "$dir" || exit 1
      printf "%s/%s\n" "$(pwd -P)" "$base"
    )
  else
    printf "%s\n" "$path"
  fi
}

function portable_log {
  local message=$1
  local sec
  local color

  sec=$(date +%S)
  color=$((91 + (10#$sec % 6)))
  if [ -t 1 ] ; then
    printf "\033[%sm[%s] %s\033[0m\n" "$color" "$(date +'%F %T')" "$message"
  else
    printf "[%s] %s\n" "$(date +'%F %T')" "$message"
  fi
}

function portable_md5 {
  local file=$1

  if portable_command_exists md5sum ; then
    md5sum "$file" | awk '{print $1}'
  elif portable_command_exists md5 ; then
    md5 -q "$file"
  elif portable_command_exists openssl ; then
    openssl md5 -r "$file" | awk '{print $1}'
  else
    return 1
  fi
}

function portable_sha256 {
  local file=$1

  if portable_command_exists sha256sum ; then
    sha256sum "$file" | awk '{print $1}'
  elif portable_command_exists shasum ; then
    shasum -a 256 "$file" | awk '{print $1}'
  elif portable_command_exists openssl ; then
    openssl dgst -sha256 -r "$file" | awk '{print $1}'
  else
    return 1
  fi
}

function portable_materialize_annotation_validator {
  local aligner_root=$1
  local target=${2:-}
  local parts_dir="$aligner_root/vendor/annotation_validator_chunks"
  local hash_file="$parts_dir/annotation_validator.sha256"
  local expected
  local actual
  local cache_root
  local tmp
  local part

  [ -d "$parts_dir" ] || return 1
  [ -f "$hash_file" ] || return 1
  expected=$(awk 'NF { print $1; exit }' "$hash_file")
  [ -n "$expected" ] || return 1

  if [ -z "$target" ] ; then
    case "$(uname -s)" in
      Darwin)
        cache_root="${HOME:-/tmp}/Library/Caches/ALEX/annotation_validator/$expected"
        ;;
      *)
        cache_root="${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/alex/annotation_validator/$expected"
        ;;
    esac
    target="$cache_root/annotation_validator"
  fi

  if [ -x "$target" ] ; then
    actual=$(portable_sha256 "$target" 2>/dev/null || true)
    if [ "$actual" = "$expected" ] ; then
      printf "%s\n" "$target"
      return 0
    fi
  fi

  mkdir -p "$(dirname "$target")" || return 1
  tmp="$target.tmp.$$"
  rm -f "$tmp"
  : > "$tmp" || return 1
  for part in "$parts_dir"/part-* ; do
    [ -f "$part" ] || continue
    cat "$part" >> "$tmp" || {
      rm -f "$tmp"
      return 1
    }
  done

  actual=$(portable_sha256 "$tmp" 2>/dev/null || true)
  if [ "$actual" != "$expected" ] ; then
    rm -f "$tmp"
    echo "$0: error: annotation validator chunks failed checksum validation" >&2
    return 1
  fi

  mv "$tmp" "$target" || {
    rm -f "$tmp"
    return 1
  }
  chmod +x "$target" || return 1
  printf "%s\n" "$target"
}

function portable_gdown {
  local python_bin=$1
  local output=$2
  local fileid=$3
  local url="https://drive.google.com/uc?id=$fileid"
  local python_dir

  if portable_command_exists gdown ; then
    gdown -O "$output" "$url"
  elif [ -n "$python_bin" ] &&
       python_dir=$(dirname "$(portable_abspath "$python_bin")") &&
       [ -x "$python_dir/gdown" ] ; then
    "$python_dir/gdown" -O "$output" "$url"
  else
    "$python_bin" -m gdown.cli -O "$output" "$url"
  fi
}

function portable_locale_exists {
  local locale_name=$1

  portable_command_exists locale || return 1
  locale -a | awk -v want="$locale_name" '
    tolower($0) == tolower(want) { found = 1 }
    END { exit found ? 0 : 1 }
  '
}

function portable_select_locale {
  local preferred=$1

  if portable_locale_exists "$preferred" ; then
    echo "$preferred"
  elif portable_locale_exists "C.UTF-8" ; then
    echo "C.UTF-8"
  else
    echo "C"
  fi
}

function portable_refresh_symlink {
  local target=$1
  local link=$2

  if [ ! -e "$target" ] ; then
    echo "$0: error: cannot link missing speech-engine path '$target'" >&2
    return 1
  fi
  if [ -L "$link" ] || [ -e "$link" ] ; then
    rm -rf "$link"
  fi
  ln -s "$target" "$link"
}

function portable_find_annotation_validator {
  local requested=${1:-}
  local portable_dir
  local aligner_root
  local materialized

  if [ -n "$requested" ] && portable_command_exists "$requested" ; then
    command -v "$requested" 2>/dev/null || printf "%s\n" "$requested"
    return 0
  fi

  portable_dir=$(
    cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
    pwd -P
  )
  aligner_root=$(portable_abspath "$portable_dir/..")

  for candidate in \
    "$aligner_root/vendor/annotation_validator_runtime/annotation_validator" \
    "$aligner_root/vendor/annotation_validator.app/Contents/MacOS/annotation_validator" \
    "$aligner_root/vendor/annotation_validator/annotation_validator"
  do
    if [ -x "$candidate" ] ; then
      printf "%s\n" "$candidate"
      return 0
    fi
  done

  materialized=$(portable_materialize_annotation_validator "$aligner_root" "" 2>/dev/null || true)
  if [ -n "$materialized" ] && [ -x "$materialized" ] ; then
    printf "%s\n" "$materialized"
    return 0
  fi

  if portable_command_exists annotation-validator ; then
    command -v annotation-validator
    return 0
  fi

  return 1
}
