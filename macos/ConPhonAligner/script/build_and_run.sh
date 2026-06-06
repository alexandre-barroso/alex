#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ALEX_ROOT="$(cd "$PACKAGE_ROOT/../.." && pwd)"

export CONPHON_REPO_ROOT="$ALEX_ROOT"
export CONPHON_BACKEND_ROOT="$ALEX_ROOT"
export CONPHON_ALIGNER_ROOT="$ALEX_ROOT/aligner"

cd "$PACKAGE_ROOT"
exec swift run ConPhonAligner "$@"

