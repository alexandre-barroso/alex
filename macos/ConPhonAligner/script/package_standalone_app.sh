#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PACKAGE_ROOT="$REPO_ROOT/macos/ConPhonAligner"
DIST_DIR="$REPO_ROOT/dist"
APP_NAME="ALEX"
APP_DIR="$DIST_DIR/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
APP_REPO_DIR="$RESOURCES_DIR/ALEX"
PYTHON_VENV="${ALEX_PYTHON_VENV:-/Volumes/ConPhonData/conphon_python_env/.venv}"
PYTHON_BASE=""
INCLUDE_PYTHON=1
JAVA_HOME_SOURCE="${ALEX_JAVA_HOME:-}"
INCLUDE_JAVA=1
CLEAN=1
SIGN=1

usage() {
  cat <<'EOF'
usage: package_standalone_app.sh [options]

Build ALEX.app from the SwiftPM app and ALEX-local runtime assets.

Options:
  --python-venv PATH   Python virtualenv whose site-packages will be bundled.
                       Defaults to ALEX_PYTHON_VENV or /Volumes/ConPhonData/conphon_python_env/.venv.
  --python-base PATH   Python base runtime to bundle under Contents/Resources/python_runtime.
                       Defaults to sys.base_prefix from --python-venv.
  --no-python-venv     Build a development app that still needs an external Python.
  --java-home PATH     Java runtime home to bundle under Contents/Resources/java_home.
                       Defaults to ALEX_JAVA_HOME or Homebrew OpenJDK when available.
  --no-java            Build without bundled Java. Portuguese alignment will need external Java.
  --no-clean           Do not remove the previous dist/ALEX.app first.
  --no-sign            Skip local ad-hoc codesigning.
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python-venv)
      PYTHON_VENV="${2:?missing path after --python-venv}"
      shift 2
      ;;
    --python-base)
      PYTHON_BASE="${2:?missing path after --python-base}"
      shift 2
      ;;
    --no-python-venv)
      INCLUDE_PYTHON=0
      shift
      ;;
    --java-home)
      JAVA_HOME_SOURCE="${2:?missing path after --java-home}"
      shift 2
      ;;
    --no-java)
      INCLUDE_JAVA=0
      shift
      ;;
    --no-clean)
      CLEAN=0
      shift
      ;;
    --no-sign)
      SIGN=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$INCLUDE_PYTHON" -eq 1 && ! -x "$PYTHON_VENV/bin/python" ]]; then
  echo "Python venv not found or not executable: $PYTHON_VENV/bin/python" >&2
  echo "Pass --python-venv PATH or --no-python-venv for a development bundle." >&2
  exit 1
fi
if [[ "$INCLUDE_PYTHON" -eq 1 && -z "$PYTHON_BASE" ]]; then
  PYTHON_BASE="$("$PYTHON_VENV/bin/python" - <<'PY'
import sys
print(sys.base_prefix)
PY
)"
fi
if [[ "$INCLUDE_PYTHON" -eq 1 && ! -x "$PYTHON_BASE/bin/python3.12" ]]; then
  echo "Python base runtime not found or not executable: $PYTHON_BASE/bin/python3.12" >&2
  echo "Pass --python-base PATH to a Python 3.12 base runtime." >&2
  exit 1
fi
if [[ "$INCLUDE_JAVA" -eq 1 && -z "$JAVA_HOME_SOURCE" ]]; then
  for candidate in \
    /opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home \
    /opt/homebrew/opt/openjdk \
    /usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home \
    /usr/local/opt/openjdk
  do
    if [[ -x "$candidate/bin/java" ]]; then
      JAVA_HOME_SOURCE="$(cd "$candidate" && pwd -P)"
      break
    fi
  done
fi
if [[ "$INCLUDE_JAVA" -eq 1 && ! -x "$JAVA_HOME_SOURCE/bin/java" ]]; then
  echo "Java runtime not found or not executable: $JAVA_HOME_SOURCE/bin/java" >&2
  echo "Pass --java-home PATH or --no-java for a development bundle." >&2
  exit 1
fi
PACKAGING_PYTHON="/usr/bin/python3"
if [[ -x "$PYTHON_VENV/bin/python" ]]; then
  PACKAGING_PYTHON="$PYTHON_VENV/bin/python"
fi

loader_path_for() {
  "$PACKAGING_PYTHON" - "$1" "$2" <<'PY'
import os
import sys

owner = os.path.realpath(sys.argv[1])
target = os.path.realpath(sys.argv[2])
rel = os.path.relpath(target, os.path.dirname(owner))
print("@loader_path/" + rel)
PY
}

mkdir -p "$DIST_DIR"
if [[ "$CLEAN" -eq 1 ]]; then
  rm -rf "$APP_DIR"
fi
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

echo "[ALEX package] Building Swift release executable"
swift build --package-path "$PACKAGE_ROOT" -c release --product ConPhonAligner
BIN_DIR="$(swift build --package-path "$PACKAGE_ROOT" -c release --show-bin-path)"
cp "$BIN_DIR/ConPhonAligner" "$MACOS_DIR/ConPhonAligner"

echo "[ALEX package] Creating app icon"
ICONSET="$DIST_DIR/ALEX.iconset"
rm -rf "$ICONSET"
xcrun swift "$PACKAGE_ROOT/Tools/make_app_icon.swift" "$ICONSET"
iconutil -c icns "$ICONSET" -o "$RESOURCES_DIR/ALEX.icns"

echo "[ALEX package] Copying ALEX runtime assets"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.build/' \
  --exclude '.pytest_cache/' \
  --exclude '.DS_Store' \
  --exclude '**/.DS_Store' \
  --exclude '.swiftpm/' \
  --exclude '**/.build/' \
  --exclude 'dist/' \
  --exclude '/data/' \
  --exclude '.venv/' \
  --exclude 'aligner/.venv/' \
  --exclude 'aligner/.aligner-cache/' \
  --exclude 'aligner/vendor/speech_engine/egs/aligner/' \
  --exclude 'aligner/vendor/speech_engine/tools/openfst-1.8.4/src/' \
  --exclude '**/__pycache__/' \
  --exclude '**/.pytest_cache/' \
  --exclude 'demos copy/' \
  --exclude '*.h5' \
  --exclude '*.npy' \
  --exclude '*.npz' \
  --exclude '*.parquet' \
  "$REPO_ROOT/" "$APP_REPO_DIR/"

ALEX_ANNOTATION_VALIDATOR="$APP_REPO_DIR/aligner/vendor/annotation_validator_runtime/annotation_validator"
if [[ -f "$APP_REPO_DIR/aligner/utils/portable.sh" ]]; then
  # shellcheck disable=SC1090
  . "$APP_REPO_DIR/aligner/utils/portable.sh"
  if ! portable_materialize_annotation_validator "$APP_REPO_DIR/aligner" "$ALEX_ANNOTATION_VALIDATOR" >/dev/null; then
    echo "Could not materialize bundled annotation validator from source chunks." >&2
    exit 1
  fi
fi
if [[ -L "$ALEX_ANNOTATION_VALIDATOR" ]]; then
  VALIDATOR_REAL="$("$PACKAGING_PYTHON" - "$ALEX_ANNOTATION_VALIDATOR" <<'PY'
import os
import sys
print(os.path.realpath(sys.argv[1]))
PY
)"
  if [[ ! -x "$VALIDATOR_REAL" ]]; then
    echo "Bundled annotation validator symlink target is not executable: $VALIDATOR_REAL" >&2
    exit 1
  fi
  rm "$ALEX_ANNOTATION_VALIDATOR"
  cp "$VALIDATOR_REAL" "$ALEX_ANNOTATION_VALIDATOR"
  chmod +x "$ALEX_ANNOTATION_VALIDATOR"
fi

if [[ -d "$APP_REPO_DIR/aligner/vendor/speech_engine/tools/openfst-1.8.4" && ! -e "$APP_REPO_DIR/aligner/vendor/speech_engine/tools/openfst" ]]; then
  (cd "$APP_REPO_DIR/aligner/vendor/speech_engine/tools" && ln -s openfst-1.8.4 openfst)
fi
SPEECH_ENGINE_SRC_DIR="$APP_REPO_DIR/aligner/vendor/speech_engine/src"
if [[ -d "$SPEECH_ENGINE_SRC_DIR" ]]; then
  rm -rf "$SPEECH_ENGINE_SRC_DIR/lib"
  mkdir -p "$SPEECH_ENGINE_SRC_DIR/lib"
  while IFS= read -r -d '' speech_engine_lib; do
    rel="../$(basename "$(dirname "$speech_engine_lib")")/$(basename "$speech_engine_lib")"
    ln -s "$rel" "$SPEECH_ENGINE_SRC_DIR/lib/$(basename "$speech_engine_lib")"
  done < <(find "$SPEECH_ENGINE_SRC_DIR" -mindepth 2 -maxdepth 2 -type f -name 'libk*.dylib' -print0)
fi

if [[ "$INCLUDE_PYTHON" -eq 1 ]]; then
  PYTHON_VERSION="$("$PYTHON_VENV/bin/python" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  echo "[ALEX package] Copying Python runtime from $PYTHON_BASE"
  rm -rf "$RESOURCES_DIR/python_runtime"
  mkdir -p "$RESOURCES_DIR/python_runtime/bin" "$RESOURCES_DIR/python_runtime/lib"
  cp "$PYTHON_BASE/bin/python3.12" "$RESOURCES_DIR/python_runtime/bin/python3.12"
  ln -sf python3.12 "$RESOURCES_DIR/python_runtime/bin/python3"
  ln -sf python3.12 "$RESOURCES_DIR/python_runtime/bin/python"
  cp "$PYTHON_BASE/lib/libpython3.12.dylib" "$RESOURCES_DIR/python_runtime/lib/libpython3.12.dylib"
  rsync -a --delete \
    --exclude 'site-packages/' \
    --exclude '__pycache__/' \
    --exclude 'test/' \
    --exclude 'idlelib/' \
    "$PYTHON_BASE/lib/python$PYTHON_VERSION/" "$RESOURCES_DIR/python_runtime/lib/python$PYTHON_VERSION/"
  install_name_tool -id "@rpath/libpython3.12.dylib" "$RESOURCES_DIR/python_runtime/lib/libpython3.12.dylib"
  install_name_tool -change "$PYTHON_BASE/lib/libpython3.12.dylib" "@executable_path/../lib/libpython3.12.dylib" "$RESOURCES_DIR/python_runtime/bin/python3.12"

  echo "[ALEX package] Rewriting Python runtime native dependencies"

  copy_python_dep_if_referenced() {
    local source="$1"
    local loader_change="$2"
    local referenced=0
    local native
    while IFS= read -r -d '' native; do
      if otool -L "$native" 2>/dev/null | awk '{print $1}' | grep -Fxq "$source"; then
        referenced=1
        break
      fi
    done < <(find "$RESOURCES_DIR/python_runtime/lib/python$PYTHON_VERSION/lib-dynload" -type f \( -name '*.so' -o -name '*.dylib' \) -print0)
    if [[ "$referenced" -eq 1 && -f "$source" ]]; then
      cp "$source" "$RESOURCES_DIR/python_runtime/lib/"
      install_name_tool -id "@loader_path/$(basename "$source")" "$RESOURCES_DIR/python_runtime/lib/$(basename "$source")" || true
      while IFS= read -r -d '' native; do
        install_name_tool -change "$source" "$loader_change" "$native" 2>/dev/null || true
      done < <(find "$RESOURCES_DIR/python_runtime/lib/python$PYTHON_VERSION/lib-dynload" -type f \( -name '*.so' -o -name '*.dylib' \) -print0)
    fi
  }

  copy_python_dep_if_referenced /opt/homebrew/opt/openssl@3/lib/libssl.3.dylib "@loader_path/../../libssl.3.dylib"
  copy_python_dep_if_referenced /opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib "@loader_path/../../libcrypto.3.dylib"
  copy_python_dep_if_referenced /opt/homebrew/opt/readline/lib/libreadline.8.dylib "@loader_path/../../libreadline.8.dylib"

  if [[ -f "$RESOURCES_DIR/python_runtime/lib/libssl.3.dylib" && -f "$RESOURCES_DIR/python_runtime/lib/libcrypto.3.dylib" ]]; then
    while IFS= read -r dep; do
      install_name_tool -change "$dep" "@loader_path/libcrypto.3.dylib" "$RESOURCES_DIR/python_runtime/lib/libssl.3.dylib" || true
    done < <(otool -L "$RESOURCES_DIR/python_runtime/lib/libssl.3.dylib" | awk 'index($1, "libcrypto.3.dylib") && substr($1, 1, 1) == "/" {print $1}')
  fi
  while IFS= read -r -d '' native; do
    install_name_tool -change /opt/homebrew/opt/xz/lib/liblzma.5.dylib /usr/lib/liblzma.5.dylib "$native" 2>/dev/null || true
  done < <(find "$RESOURCES_DIR/python_runtime/lib/python$PYTHON_VERSION/lib-dynload" -type f \( -name '*.so' -o -name '*.dylib' \) -print0)

  echo "[ALEX package] Copying Python packages from $PYTHON_VENV"
  rm -rf "$RESOURCES_DIR/python_env"
  mkdir -p "$RESOURCES_DIR/python_env/lib/python$PYTHON_VERSION"
  "$PYTHON_VENV/bin/python" - "$PYTHON_VENV/lib/python$PYTHON_VERSION/site-packages" "$RESOURCES_DIR/python_env/lib/python$PYTHON_VERSION/site-packages" <<'PY'
import importlib.metadata as md
import os
import shutil
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve()
dest = Path(sys.argv[2]).resolve()
dest.mkdir(parents=True, exist_ok=True)

needed = [
    "numpy",
    "scipy",
    "h5py",
    "soundfile",
    "cffi",
    "pycparser",
    "pandas",
    "python-dateutil",
    "six",
    "tzdata",
    "TextGrid",
    "Unidecode",
    "brucezilany",
    "typer",
    "click",
    "shellingham",
    "rich",
    "markdown-it-py",
    "mdurl",
    "Pygments",
    "typing_extensions",
    "annotated-doc",
]

def copy_path(path: Path) -> None:
    if "__pycache__" in path.parts or path.suffix == ".pyc":
        return
    try:
        rel = path.resolve().relative_to(source)
    except ValueError:
        return
    target = dest / rel
    if path.is_dir():
        shutil.copytree(path, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    elif path.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

for name in needed:
    try:
        dist = md.distribution(name)
    except md.PackageNotFoundError:
        if name in {"tzdata", "annotated-doc"}:
            continue
        raise
    files = dist.files or ()
    top_names = {line.strip() for line in (dist.read_text("top_level.txt") or "").splitlines() if line.strip()}
    for file in files:
        parts = Path(file).parts
        if not parts:
            continue
        first = parts[0]
        if first.endswith((".dist-info", ".data")):
            continue
        if len(parts) > 1 or Path(first).suffix in {".py", ".so", ".pyd", ".dylib"}:
            top_names.add(Path(first).stem if Path(first).suffix == ".py" else first)
    for top in sorted(top_names):
        for candidate in source.glob(top + "*"):
            copy_path(candidate)
    for file in files:
        copy_path(Path(dist.locate_file(file)))

for entry in dest.rglob("*.pth"):
    text = entry.read_text(errors="ignore")
    if any(marker in text for marker in ("/Volumes/", "/Users/", "/opt/homebrew")):
        entry.unlink()
PY
  find "$RESOURCES_DIR/python_env/lib/python$PYTHON_VERSION/site-packages" -name '*.pth' -print0 |
    while IFS= read -r -d '' pth; do
      if grep -Eq '/Volumes/|/Users/|/opt/homebrew' "$pth"; then
        rm -f "$pth"
      fi
    done
  SITE_PACKAGES_DIR="$RESOURCES_DIR/python_env/lib/python$PYTHON_VERSION/site-packages"
  echo "[ALEX package] Rewriting Python package native dependencies"
  while IFS= read -r -d '' native; do
    if [[ "$native" == *.dylib ]]; then
      install_name_tool -id "@loader_path/$(basename "$native")" "$native" 2>/dev/null || true
    fi
    while IFS= read -r dep; do
      target=""
      case "$dep" in
        /DLC/*)
          target="$SITE_PACKAGES_DIR/${dep#/DLC/}"
          ;;
      esac
      if [[ -n "$target" && -f "$target" ]]; then
        loader_dep="$(loader_path_for "$native" "$target")"
        install_name_tool -change "$dep" "$loader_dep" "$native" 2>/dev/null || true
      fi
    done < <(otool -L "$native" 2>/dev/null | awk 'NR > 1 && substr($1, 1, 1) == "/" {print $1}')
  done < <(find "$SITE_PACKAGES_DIR" -type f \( -name '*.dylib' -o -name '*.so' -o -name '*.cpython-*.so' \) -print0)
fi

if [[ "$INCLUDE_JAVA" -eq 1 ]]; then
  echo "[ALEX package] Copying Java runtime from $JAVA_HOME_SOURCE"
  rm -rf "$RESOURCES_DIR/java_home"
  rsync -a --delete \
    --exclude '.DS_Store' \
    --exclude 'demo/' \
    --exclude 'man/' \
    "$JAVA_HOME_SOURCE/" "$RESOURCES_DIR/java_home/"
  echo "[ALEX package] Bundling Java runtime native dependencies"
  for dylib in \
    /opt/homebrew/opt/giflib/lib/libgif.dylib \
    /opt/homebrew/opt/jpeg-turbo/lib/libjpeg.8.dylib \
    /opt/homebrew/opt/libpng/lib/libpng16.16.dylib \
    /opt/homebrew/opt/harfbuzz/lib/libharfbuzz.0.dylib \
    /opt/homebrew/opt/freetype/lib/libfreetype.6.dylib \
    /opt/homebrew/opt/little-cms2/lib/liblcms2.2.dylib \
    /opt/homebrew/opt/glib/lib/libglib-2.0.0.dylib \
    /opt/homebrew/opt/gettext/lib/libintl.8.dylib \
    /opt/homebrew/opt/pcre2/lib/libpcre2-8.0.dylib \
    /opt/homebrew/opt/graphite2/lib/libgraphite2.3.dylib
  do
    if [[ -f "$dylib" ]]; then
      cp "$dylib" "$RESOURCES_DIR/java_home/lib/"
      install_name_tool -id "@loader_path/$(basename "$dylib")" "$RESOURCES_DIR/java_home/lib/$(basename "$dylib")" || true
    fi
  done
  while IFS= read -r -d '' native; do
    if [[ "$native" == *.dylib ]]; then
      install_name_tool -id "@loader_path/$(basename "$native")" "$native" 2>/dev/null || true
    fi
    while IFS= read -r dep; do
      target=""
      for source_prefix in \
        "$JAVA_HOME_SOURCE" \
        /opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home \
        /opt/homebrew/opt/openjdk \
        /usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home \
        /usr/local/opt/openjdk
      do
        case "$dep" in
          "$source_prefix"/*)
            rel="${dep#"$source_prefix"/}"
            target="$RESOURCES_DIR/java_home/$rel"
            break
            ;;
        esac
      done
      base="$(basename "$dep")"
      if [[ -z "$target" || ! -f "$target" ]]; then
        if [[ -f "$RESOURCES_DIR/java_home/lib/$base" ]]; then
          target="$RESOURCES_DIR/java_home/lib/$base"
        elif [[ -f "$RESOURCES_DIR/java_home/lib/server/$base" ]]; then
          target="$RESOURCES_DIR/java_home/lib/server/$base"
        fi
      fi
      if [[ -n "$target" && -f "$target" ]]; then
        loader_dep="$(loader_path_for "$native" "$target")"
        install_name_tool -change "$dep" "$loader_dep" "$native" 2>/dev/null || true
      fi
    done < <(otool -L "$native" 2>/dev/null | awk 'NR > 1 && substr($1, 1, 1) == "/" && $1 !~ /^\/usr\/lib\// && $1 !~ /^\/System\/Library\// {print $1}')
  done < <(find "$RESOURCES_DIR/java_home" -type f \( -name '*.dylib' -o -perm -111 \) -print0)
fi

cat > "$MACOS_DIR/$APP_NAME" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCES_DIR="$APP_DIR/Resources"
export CONPHON_REPO_ROOT="$RESOURCES_DIR/ALEX"
export CONPHON_BACKEND_ROOT="$RESOURCES_DIR/ALEX"
export CONPHON_ALIGNER_ROOT="$RESOURCES_DIR/ALEX/aligner"
export PYTHONDONTWRITEBYTECODE=1
if [[ -d "$RESOURCES_DIR/python_runtime" ]]; then
  export PYTHONHOME="$RESOURCES_DIR/python_runtime"
  export ALEX_BUNDLED_PYTHON="$RESOURCES_DIR/python_runtime/bin/python3.12"
  export CONPHON_PYTHON="$ALEX_BUNDLED_PYTHON"
  PY_VERSION="$("$ALEX_BUNDLED_PYTHON" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  export ALEX_BUNDLED_SITE_PACKAGES="$RESOURCES_DIR/python_env/lib/python$PY_VERSION/site-packages"
fi
if [[ -x "$RESOURCES_DIR/java_home/bin/java" ]]; then
  export JAVA_HOME="$RESOURCES_DIR/java_home"
  export PATH="$JAVA_HOME/bin:$PATH"
fi
export PYTHONPATH="$RESOURCES_DIR/ALEX/src${ALEX_BUNDLED_SITE_PACKAGES:+:$ALEX_BUNDLED_SITE_PACKAGES}"
export MPLCONFIGDIR="${TMPDIR:-/tmp}/alex-matplotlib"
export XDG_CACHE_HOME="${TMPDIR:-/tmp}/alex-cache"
exec "$APP_DIR/MacOS/ConPhonAligner" "$@"
EOF
chmod +x "$MACOS_DIR/$APP_NAME"

cat > "$CONTENTS_DIR/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIconFile</key>
  <string>ALEX</string>
  <key>CFBundleIdentifier</key>
  <string>org.conphon.alex</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>ALEX</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>14.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
EOF

if [[ "$SIGN" -eq 1 ]]; then
  echo "[ALEX package] Ad-hoc signing bundled native runtimes"
  while IFS= read -r -d '' native; do
    if file "$native" | grep -q 'Mach-O'; then
      codesign --force --sign - "$native" >/dev/null 2>&1 || true
    fi
  done < <(find "$RESOURCES_DIR" -type f \( -name '*.dylib' -o -name '*.so' -o -name '*.cpython-*.so' -o -perm -111 \) -print0)
  echo "[ALEX package] Ad-hoc signing local app bundle"
  codesign --force --deep --sign - "$APP_DIR" >/dev/null
fi

echo "[ALEX package] Built $APP_DIR"
if [[ "$INCLUDE_PYTHON" -eq 0 ]]; then
  echo "[ALEX package] Note: built without bundled Python; this is not fully standalone."
fi
