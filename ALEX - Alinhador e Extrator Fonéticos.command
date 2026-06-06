#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CONPHON_REPO_ROOT="$REPO_ROOT"
export CONPHON_ALIGNER_ROOT="$REPO_ROOT/aligner"
export CONPHON_BACKEND_ROOT="$REPO_ROOT"

for candidate in \
  "$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/aligner/.venv/bin/python" \
  "/Volumes/ConPhonData/conphon_python_env/.venv/bin/python" \
  "/Volumes/ConPhon/conphon_python_env/.venv/bin/python" \
  "/usr/bin/python3"
do
  if [[ -x "$candidate" ]]; then
    export CONPHON_PYTHON="$candidate"
    break
  fi
done
if [[ -z "${CONPHON_PYTHON:-}" ]]; then
  echo "No usable Python interpreter found for ALEX." >&2
  exit 1
fi
cd "$REPO_ROOT/macos/ConPhonAligner"
exec swift run --package-path "$REPO_ROOT/macos/ConPhonAligner" ConPhonAligner "$@"
