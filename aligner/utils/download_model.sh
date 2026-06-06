#!/usr/bin/env bash
# Download or verify aligner model resources.

set -o pipefail

script_dir=$(
  cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
  pwd -P
)

python=${PYTHON_BIN:-${PYTHON:-python3}}
dry_run=false

. "$script_dir/portable.sh" || exit 1
. "$script_dir/parse_options.sh" || exit 1

if [ $# -ne 2 ] ; then
  echo "usage: $0 [options] <tag> <model-dir>"
  echo "  <tag> is the resource tag"
  echo "  <model-dir> is the folder where models will be downloaded and extracted to"
  echo
  echo "  options:"
  echo "    --python <python3>  Python interpreter used for gdown fallback"
  echo "    --dry-run <bool>    Print the resolved resource and exit"
  exit 1
fi

tag=$1
dir=$2

[ "$tag" = "tri1" ] && tag=tri1b

case "$tag" in
  data)
    filename=data.tar.gz
    fileid=1LV079CNWO_rq8bPKUSOYXCeF-f1SheZS
    filesum=ded8d03f709867c098318d0cefdeecce
    ;;
  mono)
    filename=mono.tar.gz
    fileid=1WlOMnb0P_VNVwHs1iII78aMNjND6finP
    filesum=56ea26a427f50d0f09440d0456fbbff3
    ;;
  tri1b)
    filename=tri1b.tar.gz
    fileid=1ie3NXKKfmk4bPHcnhIW4v0zelXmcjKIl
    filesum=4e8f7bb8a221d20cd7fee418e07be745
    ;;
  tri2b)
    filename=tri2b.tar.gz
    fileid=11rR2UtJahj7KHbW0hRfm55HFNm6pvCcP
    filesum=a6e268cb457fc9e28d43fda58b13d021
    ;;
  tri3b)
    filename=tri3b.tar.gz
    fileid=1IlBnLNabDnEY3rVBdz9g3P4g1wyD1Cxl
    filesum=5424cec31cff7a7e05b95098ee7be11d
    ;;
  tdnn)
    filename=tdnn.tar.gz
    fileid=10ru1CW221TzZGUdcCXTaZlw7H8nszvwP
    filesum=27179684368faead0a558b714c94d49c
    ;;
  ie)
    filename=ie.tar.gz
    fileid=19VyLt6GpPJQmPdEwbsGuwiufdEUS5E_f
    filesum=20bce8f20d659603f9ec0655e0d62628
    ;;
  m2m)
    filename=m2m.model.gz
    fileid=16z7uSUeA6vdL2cXIDpto6kW9FelXYazM
    filesum=692049ca0a2bee6c27b91997d5e1dc73
    ;;
  *)
    echo "$0: error: unknown resource tag '$tag'" >&2
    exit 1
    ;;
esac

if $dry_run ; then
  echo "$tag $filename $fileid $filesum"
  exit 0
fi

mkdir -p "$dir" || exit 1

archive="$dir/$filename"
if [ ! -f "$archive" ] ; then
  portable_gdown "$python" "$archive" "$fileid" || {
    rm -f "$archive"
    exit 1
  }
else
  echo "$0: info: file '$archive' exists. checking checksum."
fi

curr_checksum=$(portable_md5 "$archive") || {
  echo "$0: error: cannot compute checksum for '$archive'" >&2
  exit 1
}
if [ "$curr_checksum" != "$filesum" ] ; then
  echo "$0: error: checksum mismatch for '$archive'" >&2
  echo "$0: error: expected '$filesum' but got '$curr_checksum'" >&2
  echo "$0: error: remove the file and rerun to download it again" >&2
  exit 1
fi

if [ "$tag" = "m2m" ] ; then
  gzip -cd "$archive" > "$dir/${filename%.gz}" || exit 1
else
  tar xf "$archive" -C "$dir" || exit 1
fi

if [ ! -f "$dir/fb_nlplib.jar" ] ; then
  remote_host=$(printf "%s%s.com" "git" "hub")
  remote_owner=$(printf "%s%s" "fala" "brasil")
  echo "$0: downloading annotation support library"
  curl -L --fail --output "$dir/fb_nlplib.jar" \
    "https://$remote_host/$remote_owner/annotator/raw/master/fb_nlplib.jar" || exit 1
fi
