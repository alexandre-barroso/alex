#!/usr/bin/env bash
# Extend lexicon resources with missing transcript words.

set -o pipefail

if [ $# -ne 4 ] ; then
  echo "usage: $0 <trans-file> <lex-file> <syll-file> <sp-file>"
  echo "  <trans-file> is the text transcription file"
  echo "  <lex-file> is the phonetic dict file"
  echo "  <syll-file> is the syllabic dict file"
  echo "  <sp-file> is the syllphones dict file"
  exit 1
fi

txt_file=$1
lex_file=$2
syll_file=$3
sp_file=$4
python=${PYTHON_BIN:-python3}
locale_name=${ALIGNER_LOCALE:-pt_BR.UTF-8}

if locale -a | awk -v want="$locale_name" 'tolower($0) == tolower(want) { found = 1 } END { exit found ? 0 : 1 }' ; then
  export LC_ALL=$locale_name
elif locale -a | awk 'tolower($0) == "c.utf-8" { found = 1 } END { exit found ? 0 : 1 }' ; then
  echo "$0: warn: locale '$locale_name' not available; using C.UTF-8" >&2
  export LC_ALL=C.UTF-8
else
  echo "$0: warn: locale '$locale_name' not available; using C" >&2
  export LC_ALL=C
fi

rm -f ./*.tmp ./*.err
trap 'rm -f ./*.tmp ./*.err' EXIT INT TERM
for word in $(cat "$txt_file") ; do
  echo "$word"
done > wlist.tmp

awk '{print $1}' "$lex_file" | "$python" -c "
import sys
lex = set([word.strip() for word in sys.stdin])
with open('wlist.tmp') as f:
  wlist = set([word.strip() for word in f])
miss = set()
for word in wlist:
  if word not in lex:
    print(f'$0: warning: {word=} not in lex', file=sys.stderr)
    miss.add(word)
if len(miss) == 0:
  print('$0: info: no words missing in dict. great!', file=sys.stderr)
for m in miss:
  print(m)
" | sort > miss.tmp

echo "$0: info: extending lexicon"
java -jar "$ALIGNER_DIR/fb_nlplib.jar" -g -i miss.tmp -o lex.tmp || exit 1
(
  head -n 2 "$lex_file"
  (
    tail -n +3 "$lex_file"
    cat lex.tmp
  ) | sort -u | "$python" local/parse_abbrev.py
) > lex || exit 1
mv -v lex "$lex_file"

echo "$0: info: extending syllables"
java -jar "$ALIGNER_DIR/fb_nlplib.jar" -s -i miss.tmp -o syll.tmp || exit 1
sort -u "$syll_file" syll.tmp | "$python" local/fix_syll.py > syll || exit 1
mv -v syll "$syll_file"

echo "$0: info: extending syllphones"
"$python" local/dict2news.py \
  --m2m_lut_file sp.lut.tmp lex.tmp syll.tmp > sp.news.tmp || exit 1
"$python" local/m2m_aligner.py \
  --max_x 4 \
  --max_y 1 \
  --input_file sp.news.tmp \
  --output_file sp.ali.tmp \
  --aligner_in "$ALIGNER_DIR/m2m.model" || exit 1
(
  head -n 1 "$sp_file"
  (
    tail -n +2 "$sp_file"
    "$python" local/ali2syllphones.py < sp.ali.tmp
    cat sp.lut.tmp
  ) | sort -u | "$python" local/parse_abbrev.py
) > sp || exit 1
mv sp "$sp_file"

[ -s sp.ali.tmp.err ] && \
  echo "$0: warn: the syllables from the following words could not be " && \
  echo "properly aligned to their phonetic transcription, " && \
  echo "so they will NOT appear in the syllphones dict:" && \
  cat sp.ali.tmp.err

echo "$0: info: success!"
