#!/usr/bin/env bash
# Wraps Step 2 CLI baseline. Saves to $OUTDIR (default ./perf/baseline).
#
# Usage:
#   scripts/baseline-cli.sh '<command with args>'
#   scripts/baseline-cli.sh --label run-1 '<command>' '<other-command>'
#
# Env:
#   PERF_OUTDIR  output directory (default ./perf/<label>, label default "baseline")
#   PERF_RUNS    --runs (default 20; set 100+ for sub-50ms commands)
#   PERF_WARMUP  --warmup (default 3)
#   PERF_PREPARE optional --prepare command (e.g. cold-cache invalidation)

set -euo pipefail

LABEL="baseline"
if [ "${1:-}" = "--label" ]; then
  LABEL="$2"
  shift 2
fi

if [ $# -lt 1 ]; then
  echo "Usage: $0 [--label NAME] '<command>' ['<command>' ...]" >&2
  echo "  Quote each command as a single argument so hyperfine sees it as one." >&2
  exit 64
fi

if ! command -v hyperfine >/dev/null 2>&1; then
  echo "error: hyperfine not found. Install: https://github.com/sharkdp/hyperfine" >&2
  exit 127
fi

OUTDIR="${PERF_OUTDIR:-./perf/$LABEL}"
RUNS="${PERF_RUNS:-20}"
WARMUP="${PERF_WARMUP:-3}"

mkdir -p "$OUTDIR"

ARGS=(--warmup "$WARMUP" --runs "$RUNS"
      --export-json "$OUTDIR/$LABEL.json"
      --export-markdown "$OUTDIR/$LABEL.md")

if [ -n "${PERF_PREPARE:-}" ]; then
  ARGS+=(--prepare "$PERF_PREPARE")
fi

echo "==> hyperfine ${ARGS[*]} $*"
hyperfine "${ARGS[@]}" "$@"

echo
echo "Saved:"
echo "  $OUTDIR/$LABEL.json"
echo "  $OUTDIR/$LABEL.md"
