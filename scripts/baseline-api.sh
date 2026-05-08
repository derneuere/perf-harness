#!/usr/bin/env bash
# Wraps Step 2 API baseline. Saves to $OUTDIR (default ./perf/baseline).
#
# Usage:
#   scripts/baseline-api.sh
#   scripts/baseline-api.sh --label run-1 --host http://localhost:8000
#
# Env (or flags):
#   PERF_OUTDIR        output directory (default ./perf/<label>, label default "baseline")
#   PERF_HOST          --host (default http://localhost:8000)
#   PERF_USERS         --users (default 50)
#   PERF_SPAWN_RATE    --spawn-rate (default 10)
#   PERF_DURATION      --run-time (default 2m)
#   PERF_LOCUSTFILE    -f (default ./locustfile.py, then ./templates/locustfile.py)

set -euo pipefail

LABEL="baseline"
HOST="${PERF_HOST:-http://localhost:8000}"
USERS="${PERF_USERS:-50}"
SPAWN_RATE="${PERF_SPAWN_RATE:-10}"
DURATION="${PERF_DURATION:-2m}"
LOCUSTFILE="${PERF_LOCUSTFILE:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --label)       LABEL="$2"; shift 2;;
    --host)        HOST="$2"; shift 2;;
    --users)       USERS="$2"; shift 2;;
    --spawn-rate)  SPAWN_RATE="$2"; shift 2;;
    --run-time)    DURATION="$2"; shift 2;;
    -f|--locustfile) LOCUSTFILE="$2"; shift 2;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 64
      ;;
  esac
done

if ! command -v locust >/dev/null 2>&1; then
  echo "error: locust not found. Install: pip install locust" >&2
  exit 127
fi

if [ -z "$LOCUSTFILE" ]; then
  for f in ./locustfile.py ./templates/locustfile.py ./perf/locustfile.py; do
    if [ -f "$f" ]; then LOCUSTFILE="$f"; break; fi
  done
fi
if [ -z "$LOCUSTFILE" ] || [ ! -f "$LOCUSTFILE" ]; then
  echo "error: no locustfile found. Pass -f PATH or run 'perf-harness init'." >&2
  exit 66
fi

OUTDIR="${PERF_OUTDIR:-./perf/$LABEL}"
mkdir -p "$OUTDIR"

echo "==> locust -f $LOCUSTFILE --headless --host $HOST"
echo "    --users $USERS --spawn-rate $SPAWN_RATE --run-time $DURATION"
echo "    --csv $OUTDIR/$LABEL"

locust -f "$LOCUSTFILE" --headless \
  --users "$USERS" --spawn-rate "$SPAWN_RATE" --run-time "$DURATION" \
  --host "$HOST" \
  --csv "$OUTDIR/$LABEL" \
  --only-summary

echo
echo "Saved:"
ls -1 "$OUTDIR"/${LABEL}_*.csv 2>/dev/null || true
echo
echo "Read p95 with:"
echo "  column -ts, $OUTDIR/${LABEL}_stats.csv | less -S"
