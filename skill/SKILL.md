---
name: perf-harness
description: Use this skill when the user wants to find and fix performance bottlenecks in a CLI tool or HTTP API by running real benchmarks under load, profiling to identify hotspots, proposing code changes, and verifying speedups against the same workload. Triggers include "make this faster", "find the bottleneck", "optimize this endpoint", "why is X slow", "this CLI takes too long", and any request pairing a runnable target with a desire for measured speedups. Do NOT use for: refactoring requests with no perf criteria, abstract algorithm questions, or optimizing LLM inference itself.
---

# Performance Harness

Profile-guided optimization loop: **measure → locate → hypothesize → patch → re-measure**. Never accept a "fix" that has not been verified on the same workload that produced the baseline.

## Required tools

Check availability before starting; ask the user before installing anything globally.
- `hyperfine` — statistical CLI benchmarking
- `strace` (Linux) / `dtruss` (macOS) — syscall profiling
- `py-spy` — Python sampling profiler
- `samply` — cross-platform sampling profiler for native binaries
- `locust` — HTTP load testing

## Step 1 — Classify the target

Pick one mode. Ask only if genuinely ambiguous.

- **CLI mode** — executable invoked with args, exits.
- **API mode** — long-running HTTP service.
- **Function mode** (fallback) — user pointed at a specific function with no runnable target. Switch to function-level workflow: build a replay test from real inputs, then optimize against that.

Also establish, in this turn, before any code runs:
1. A **representative workload**. For CLI: a real input, not a toy. Ask if not provided. For API: which endpoints, at what mix.
2. A **success criterion**. Default: ≥10% p50 improvement, p95 not regressing, all tests passing. Confirm with user.

State both back to the user explicitly before proceeding.

## Step 2 — Baseline (mandatory; never skip)

### CLI
```bash
hyperfine --warmup 3 --runs 20 \
  --export-json baseline.json \
  --export-markdown baseline.md \
  '<command with representative args>'
```
For sub-50ms commands, raise `--runs` to 100+ — shell startup dominates. For cache-sensitive runs, add `--prepare 'sync; echo 3 | sudo tee /proc/sys/vm/drop_caches'` (Linux).

### API
Write `locustfile.py` exercising endpoints at the agreed mix. Run headless:
```bash
locust -f locustfile.py --headless \
  --users 50 --spawn-rate 10 --run-time 2m \
  --host http://localhost:PORT \
  --csv baseline
```
Read `baseline_stats.csv` and `baseline_failures.csv`. **Identify the worst offender by p95, not mean.** Mean hides tail latency.

Save baseline artifacts to `./perf/baseline/`. Do not modify them later.

## Step 3 — Profile the hotspot

The benchmark says *what* is slow. A profile says *why*. You need both before patching.

### CLI
- **Always run a syscall summary first** — cheap, often decisive:
  ```bash
  strace -c -o syscalls.txt <command>   # Linux
  dtruss -c <command> 2> syscalls.txt   # macOS
  ```
  Look for: unexpected call counts (10k `stat`s when ~10 expected), time concentrated in `read`/`openat` (I/O-bound, not CPU-bound — changes the entire optimization strategy).
- **Sampling profile for CPU-bound work:**
  - Python: `py-spy record -o profile.svg -- python script.py`
  - Native: `samply record <command>`
  - Identify top 1–3 functions by **self-time**, not total time.

### API
While Locust is running, attach a profiler to the server process:
- Python: `py-spy record --pid <pid> --duration 60 -o api.svg`
- Node.js: `clinic flame -- node app.js` or `0x`
- Native: `samply record -p <pid>`

Cross-check: the function flagged by the flame graph should be on the call path of the slow endpoint from Step 2. If it isn't, you are profiling the wrong thing.

## Step 4 — Hypothesize and patch

State the hypothesis in plain English **before** writing code: "Function X is slow because Y; I will change Z, expecting A% improvement." If it is a guess, say so.

Common patterns to consider, in rough order of frequency:
- Repeated work inside a hot loop → cache / hoist / memoize
- N+1 queries → batch / join / prefetch
- Sync I/O on hot path → async / batch / move off-path
- Wrong data structure (linear scan where set/dict works) → swap
- Re-parsing / re-compiling per call → do it once at module load
- Excessive allocations → reuse buffers, switch to iterators / generators
- Wrong algorithm (O(n²) where O(n log n) exists) → swap

Apply the **smallest** patch that tests the hypothesis. Run the existing test suite first; abort if anything fails.

## Step 5 — Verify (hard gates)

Re-run the **exact** Step 2 benchmark. Same workload, same hardware, same warm-up. Save to `./perf/run-N/`.

```bash
# CLI direct comparison:
hyperfine --warmup 3 --runs 20 \
  --export-markdown comparison.md \
  '<git stash; original command; git stash pop>' \
  '<optimized command>'
```

Three gates, ALL must pass:
1. **Tests pass.** Hard fail → revert.
2. **Improvement exceeds noise.** p50 drops ≥10% AND the delta is larger than 2× the pooled stdev. Otherwise reject.
3. **No regression elsewhere.** CLI: warm/cold both improved or held? API: other endpoints unchanged?

If accepted: report numerically — `"p50 412ms → 287ms, 1.43× faster, n=20, σ=4ms"`. If rejected: revert, append to `./perf/attempted.md` with what was tried and why it failed, and either form a new hypothesis or report back.

## Step 6 — Loop until diminishing returns

After each accepted patch, re-profile (Step 3). The bottleneck moves. Stop when any of:
- Success criterion from Step 1 is met
- Three consecutive hypotheses fail to produce an accepted patch
- Remaining hotspots are in third-party code you cannot modify

End with a summary: baseline → final numbers, accepted patches with individual contributions, rejected hypotheses with reasons.

## Inviolable rules

- **No speedup claim without a re-run on the same workload.** LLMs routinely produce code that looks faster but isn't. The benchmark is the only signal.
- **Do not modify the benchmark to make the patch look better.** Same workload, hardware, warm-up.
- **One change per benchmark cycle.** Stacking changes makes attribution impossible.
- **Tests are non-negotiable.** A 5× speedup that breaks a test is a regression.
- **If no test suite exists, generate replay tests from real inputs before touching code.** Capture inputs to the target function during a real run, replay them as assertions.
- **Do not optimize blind.** If Step 2 or Step 3 was skipped, stop and run them.

## Supporting files (agent should create on first use)

- `scripts/baseline-cli.sh` — wraps Step 2 CLI invocation
- `scripts/baseline-api.sh` — wraps Step 2 Locust invocation
- `scripts/compare.py` — diffs two hyperfine JSON files with stdev-aware significance check
- `templates/locustfile.py` — starter for API workloads (see below)
- `templates/replay-test.py` — generates pytest from captured function inputs

### `templates/locustfile.py` (starter)
```python
from locust import HttpUser, task, between

class WorkloadUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(10)  # weight = relative frequency
    def hot_endpoint(self):
        self.client.get("/api/most-called")

    @task(3)
    def warm_endpoint(self):
        self.client.post("/api/sometimes-called", json={"k": "v"})

    @task(1)
    def cold_endpoint(self):
        self.client.get("/api/rarely-called")
```
Weights should mirror real traffic. If unknown, ask the user; do not invent a distribution.
