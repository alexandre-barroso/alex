#!/usr/bin/env bash

set -o pipefail

script_dir=$(
  cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
  pwd -P
)

beam=10
retry_beam=40
python=${PYTHON_BIN:-${PYTHON:-python3}}
locale=${ALIGNER_LOCALE:-pt_BR.UTF-8}
aligner_dir=${ALIGNER_DIR:-}
speech_engine_root=${ALEX_SPEECH_ENGINE_ROOT:-}
bp_acoustic_recipe_root=${ALEX_BP_ACOUSTIC_RECIPE_ROOT:-}
speech_recipe=${ALEX_SPEECH_RECIPE:-auto}
output_dir=
work_dir=${ALIGNER_WORK_DIR:-}

help_message="usage: $0 [options] <wav-file> <txt-file> <am-tag>
  <wav-file> is the audio input file
  <txt-file> is the transcription input file
  <am-tag> is the tag corresponding to the acoustic model

  options:
    --beam <n>              alignment beam, default: $beam
    --retry-beam <n>        retry beam, default: $retry_beam
    --aligner-dir <dir>     model/resource cache directory
    --python <python3>      Python interpreter, default: $python
    --locale <locale>       collation locale, default: $locale
    --speech-engine-root <dir>      speech engine root; defaults to vendor/speech_engine
    --bp-acoustic-recipe-root <dir> BP acoustic recipe root; also accepted via ALEX_BP_ACOUSTIC_RECIPE_ROOT
    --speech-recipe <name>   auto, bp, or generic; default: $speech_recipe
    --output-dir <dir>      directory for resulting TextGrid files;
                            default: same directory as <wav-file>
    --work-dir <dir>        writable speech recipe workspace; defaults to TMPDIR

  valid am tags: mono, tri1b, tri1, tri2b, tri3b, tdnn

  e.g.: ALEX_SPEECH_ENGINE_ROOT=\$HOME/alex-speech-engine bash $0 demo/coxinha.wav demo/coxinha.txt mono
"

. "$script_dir/utils/portable.sh" || exit 1
. "$script_dir/utils/parse_options.sh" || exit 1

function usage {
  printf "%s\n" "$help_message"
}

if [ $# -ne 3 ] ; then
  usage
  exit 1
fi

case "$python" in
  */*) PYTHON_BIN=$(portable_abspath "$python") ;;
  *) PYTHON_BIN=$python ;;
esac
ALIGNER_LOCALE=$locale
export PYTHON_BIN ALIGNER_LOCALE
case "$PYTHON_BIN" in
  */*) export PATH="$(dirname "$PYTHON_BIN"):$PATH" ;;
esac

if [ -z "$speech_engine_root" ] && [ -d "$script_dir/vendor/speech_engine" ] ; then
  speech_engine_root="$script_dir/vendor/speech_engine"
fi
if [ -z "$bp_acoustic_recipe_root" ] && [ -d "$script_dir/vendor/bp_acoustic_recipe" ] ; then
  bp_acoustic_recipe_root="$script_dir/vendor/bp_acoustic_recipe"
fi
if [ -n "$speech_engine_root" ] ; then
  speech_engine_root=$(portable_abspath "$speech_engine_root")
fi
if [ -n "$bp_acoustic_recipe_root" ] ; then
  bp_acoustic_recipe_root=$(portable_abspath "$bp_acoustic_recipe_root")
fi
ALEX_SPEECH_ENGINE_ROOT=$speech_engine_root
ALEX_BP_ACOUSTIC_RECIPE_ROOT=$bp_acoustic_recipe_root
ALEX_SPEECH_RECIPE=$speech_recipe
export ALEX_SPEECH_ENGINE_ROOT ALEX_BP_ACOUSTIC_RECIPE_ROOT ALEX_SPEECH_RECIPE
portable_export_engine_compat "$ALEX_SPEECH_ENGINE_ROOT" "$ALEX_BP_ACOUSTIC_RECIPE_ROOT" "$ALEX_SPEECH_RECIPE"

if [ -d "$ALEX_SPEECH_ENGINE_ROOT/tools/openfst-1.8.4/bin" ] ; then
  export PATH="$ALEX_SPEECH_ENGINE_ROOT/tools/openfst-1.8.4/bin:$PATH"
fi

if [ -z "$aligner_dir" ] ; then
  aligner_dir=$(portable_default_aligner_dir)
fi
ALIGNER_DIR=$(portable_abspath "$aligner_dir")
export ALIGNER_DIR

mkdir -p "$ALIGNER_DIR" || {
  echo "$0: error: could not create aligner dir '$ALIGNER_DIR'" >&2
  exit 1
}

ALEX_SPEECH_ENGINE_ROOT=$ALEX_SPEECH_ENGINE_ROOT \
ALEX_BP_ACOUSTIC_RECIPE_ROOT=$ALEX_BP_ACOUSTIC_RECIPE_ROOT \
ALEX_SPEECH_RECIPE=$ALEX_SPEECH_RECIPE \
  bash "$script_dir/utils/check_dependencies.sh" \
    --python "$PYTHON_BIN" \
    --locale "$ALIGNER_LOCALE" || exit 1

wav_file=$(portable_abspath "$1")
txt_file=$(portable_abspath "$2")
am_tag=$3

for f in "$wav_file" "$txt_file" ; do
  [ ! -f "$f" ] && echo "$0: error: file '$f' does not exist" >&2 && exit 1
done

if [ -n "$output_dir" ] ; then
  output_dir=$(portable_abspath "$output_dir")
else
  output_dir=$(dirname "$wav_file")
fi

case "$am_tag" in
  tri1)
    am_tag=tri1b
    ;;
  mono|tri1b|tri2b|tri3b|tdnn)
    ;;
  *)
    echo "$0: error: bad acoustic model tag '$am_tag'" >&2
    exit 1
    ;;
esac

recipe_selection=$(portable_speech_recipe_source "$ALEX_SPEECH_ENGINE_ROOT" "$ALEX_BP_ACOUSTIC_RECIPE_ROOT" "$ALEX_SPEECH_RECIPE") || exit 1
recipe_name=${recipe_selection%%:*}
recipe_workspace=${recipe_selection#*:}
portable_log "$0: using $recipe_name speech recipe from $recipe_workspace"

portable_log "$0: downloading models"
bash "$script_dir/utils/download_model.sh" --python "$PYTHON_BIN" "data" "$ALIGNER_DIR" || exit 1
bash "$script_dir/utils/download_model.sh" --python "$PYTHON_BIN" "m2m" "$ALIGNER_DIR" || exit 1
bash "$script_dir/utils/download_model.sh" --python "$PYTHON_BIN" "$am_tag" "$ALIGNER_DIR" || exit 1
if [ "$am_tag" = "tdnn" ] ; then
  bash "$script_dir/utils/download_model.sh" --python "$PYTHON_BIN" "ie" "$ALIGNER_DIR" || exit 1
fi

if [ -n "$work_dir" ] ; then
  work_root=$(portable_abspath "$work_dir")
  mkdir -p "$work_root" || exit 1
else
  work_root=$(mktemp -d "${TMPDIR:-/tmp}/alex-aligner.XXXXXX") || exit 1
fi
mkdir -p "$work_root/egs" || exit 1
portable_refresh_symlink "$ALEX_SPEECH_ENGINE_ROOT/tools" "$work_root/tools" || exit 1
portable_refresh_symlink "$ALEX_SPEECH_ENGINE_ROOT/src" "$work_root/src" || exit 1
egs_dir="$work_root/egs/aligner/s5"
if [ "${ALEX_KEEP_ALIGNMENT_WORK:-0}" != "1" ] ; then
  trap 'rm -rf "$work_root"' EXIT
fi
rm -rf "$egs_dir/data" "$egs_dir/conf" "$egs_dir/local" "$egs_dir/steps" "$egs_dir/utils" "$egs_dir/path.sh"
mkdir -p "$egs_dir/data/local" || exit 1

cp -R "$script_dir/conf" "$script_dir/local" "$egs_dir" || exit 1
cp -R "$ALIGNER_DIR/data" "$egs_dir" || exit 1
portable_refresh_symlink "$recipe_workspace/steps" "$egs_dir/steps" || exit 1
portable_refresh_symlink "$recipe_workspace/utils" "$egs_dir/utils" || exit 1
portable_refresh_symlink "$recipe_workspace/path.sh" "$egs_dir/path.sh" || exit 1

########################################
### speech-engine scripting starts here ###
########################################
cd "$egs_dir" || exit 1

. path.sh || exit 1

portable_log "$0: preparing data"
mkdir -p data/alignme || exit 1
utt_id=$(basename "$wav_file")
utt_id=${utt_id%.wav}
echo "$utt_id $wav_file" > data/alignme/wav.scp
echo "$utt_id $(cat "$txt_file")" > data/alignme/text
echo "$utt_id $utt_id" > data/alignme/utt2spk
utils/utt2spk_to_spk2utt.pl \
  data/alignme/utt2spk > data/alignme/spk2utt || exit 1

portable_log "$0: extending lexicon and lang"
ALIGNER_DIR=$ALIGNER_DIR \
ALIGNER_LOCALE=$ALIGNER_LOCALE \
PYTHON_BIN=$PYTHON_BIN \
  bash local/ext_dict.sh \
    "$txt_file" data/dict/lexicon.txt data/dict/syllables.txt data/dict/syllphones.txt || exit 1

# The lexicon can grow for each transcript, so the language graph is refreshed
# before alignment.
portable_log "$0: rebuilding language graph"
utils/prepare_lang.sh data/dict "<UNK>" data/lang_tmp data/lang || exit 1

portable_log "$0: extracting mfccs"
conf=conf/mfcc.conf
[ "$am_tag" = "tdnn" ] && conf=conf/mfcc_hires.conf
steps/make_mfcc.sh --nj 1 --mfcc-config "$conf" data/alignme || exit 1
steps/compute_cmvn_stats.sh data/alignme || exit 1
utils/fix_data_dir.sh data/alignme || exit 1

if [ "$am_tag" = "tdnn" ] ; then
  portable_log "$0: extracting ivectors"
  steps/online/nnet2/extract_ivectors_online.sh --nj 1 \
    data/alignme "$ALIGNER_DIR/ie" data/alignme/ivector_hires || exit 1
fi

portable_log "$0: aligning"
case "$am_tag" in
  mono|tri1b|tri2b|tri3b)
    steps/align_si.sh --nj 1 --beam "$beam" --retry-beam "$retry_beam" \
      data/alignme data/lang "$ALIGNER_DIR/$am_tag" data/alignme_ali || exit 1
    ;;
  tdnn)
    steps/nnet3/align.sh --nj 1 --use-gpu false \
      --beam "$beam" --retry-beam "$retry_beam" \
      --online-ivector-dir data/alignme/ivector_hires \
      --scale-opts '--transition-scale=1.0 --acoustic-scale=1.0 --self-loop-scale=1.0' \
      data/alignme data/lang "$ALIGNER_DIR/$am_tag" data/alignme_ali || exit 1
    ;;
esac

portable_log "$0: creating ctm"
frame_shift_opts=()
[ "$am_tag" = "tdnn" ] && frame_shift_opts=(--frame-shift=0.03)
for ali in data/alignme_ali/ali.*.gz ; do
  [ ! -e "$ali" ] && echo "$0: error: no alignment archives found" >&2 && exit 1

  ali-to-phones "${frame_shift_opts[@]}" --ctm-output=true \
    "$ALIGNER_DIR/$am_tag/final.mdl" \
    ark:"gunzip -c $ali |" \
    - | \
    tee "${ali%.gz}_p.ctm" | \
    utils/int2sym.pl -f 5 data/lang/phones.txt | \
    "$PYTHON_BIN" local/strip.py > "data/$am_tag.phonemes.ctm" || exit 1

  linear-to-nbest \
    "ark:gunzip -c $ali |" \
    "ark:utils/sym2int.pl --map-oov 2 -f 2- data/lang/words.txt < data/alignme/text |" \
    '' \
    '' \
    ark:- | \
  lattice-align-words \
    data/lang/phones/word_boundary.int \
    "$ALIGNER_DIR/$am_tag/final.mdl" \
    ark:- \
    ark:- | \
  nbest-to-ctm "${frame_shift_opts[@]}" --precision=3 --print-silence=true \
    ark:- \
    - | \
  tee "${ali%.gz}_w.ctm" | \
  utils/int2sym.pl -f 5 data/lang/words.txt | \
  "$PYTHON_BIN" local/strip.py > "data/$am_tag.graphemes.ctm" || exit 1
done

portable_log "$0: creating textgrid"
tg_output_dir="$PWD/data/tg"
[ -n "$output_dir" ] && tg_output_dir=$output_dir
"$PYTHON_BIN" local/ctm2tg.py \
  --graphemes-ctm-file "$PWD/data/$am_tag.graphemes.ctm" \
  --phonemes-ctm-file "$PWD/data/$am_tag.phonemes.ctm" \
  --phonetic-dictionary "$PWD/data/dict/lexicon.txt" \
  --syllphones-dictionary "$PWD/data/dict/syllphones.txt" \
  --output-dir "$tg_output_dir" || exit 1

cd - > /dev/null || exit 1

portable_log "$0: success! TextGrid output: $tg_output_dir"
