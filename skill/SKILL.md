---
name: perf-harness
description: Use this skill when the user wants to find and fix performance bottlenecks in a CLI tool, HTTP API, browser app, or specific function by running real benchmarks under load, profiling to identify hotspots, proposing code changes, and verifying speedups against the same workload. Triggers include "make this faster", "find the bottleneck", "optimize this endpoint", "why is X slow", "this CLI takes too long", and any request pairing a runnable target with a desire for measured speedups.
---

# Performance Harness

Profile-guided optimization loop: **measure → locate → hypothesize → patch → re-measure**. Never accept a "fix" that has not been verified on the same workload that produced the baseline.

## Required tools

Check availability before starting; ask the user before installing anything globally.

- `hyperfine` — statistical CLI benchmarking
- Sampling profiler appropriate to the runtime:
  - Python: `py-spy`; native binaries: `samply`
  - Node / Bun: `node --cpu-prof` (built-in), `clinic flame`, `0x`, or `bun --inspect`
  - Browser: Chrome DevTools Performance panel; headless via `puppeteer` + `Page.profiler`
- `locust` — HTTP load testing

## Step 1 — Classify the target

Pick one mode. Ask only if genuinely ambiguous.

- **CLI mode** — executable invoked with args, exits.
- **API mode** — long-running HTTP service.
- **Browser mode** — code runs in a user's browser. Profile with DevTools or headless puppeteer; `hyperfine`-the-binary won't apply.
- **Function mode** — a specific function with no runnable target around it. Build a replay test from real inputs, run in-process with `performance.now()` / `time.perf_counter()`, n ≥ 30. Use this fallback whenever the runnable target is dominated by startup overhead (loader, JIT warmup) — otherwise you'll be optimizing the harness, not the code.

For SPAs talking to a backend (React/Vue/Svelte + REST/GraphQL/RPC), time *both* the API and the browser-perceived latency: the ratio tells you whether you're network-bound (≈1:1) or render-bound (API ≪ browser).

Also establish, in this turn, before any code runs:

1. **Where the code actually runs in production.** Browser? Node server? CLI on a developer's laptop? A library used in two of those? Read the README/CONTEXT/package.json. A patch that helps Node but degrades the browser (or vice versa) is a regression, not a fix — and you cannot tell which is which without naming the deployment target up front.
2. A **representative workload**. CLI: a real input, not a toy. API: which endpoints, at what mix. Browser: which user interaction.
3. A **success criterion**. Default: ≥10% p50 improvement, p95 not regressing, all tests passing.

State all three back to the user explicitly before proceeding.

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
Read `baseline_stats.csv` and `baseline_failures.csv`. Identify the worst offender by p95, not mean.

### Function / Browser
In-process timer around the captured workload, n ≥ 30 (≥ 25 with ≥ 5 warmup discarded for browser benches — cold V8/Chrome warmup is meaningful). Save per-iteration timings as JSON in hyperfine's shape (`{"results":[{"times":[...]}]}`) so the same `compare.py` works.

For frameworks with a development mode (Vite / Next / CRA / SvelteKit), bench the production build, not the dev server — DEV-mode runtime checks can inflate timings 30%+.

**Browser-mode iteration hygiene.** Three sources of false readings to watch for:
- Query-cache poisoning (TanStack Query / SWR / Apollo / RTK Query) — invalidate between iterations, otherwise only iteration 1 measures real work.
- Auth-restore race — for SPAs that fire data hooks before auth rehydrates, log in then reload before starting.
- Auto-cancelled in-flight requests — wait for `networkidle` between iterations; some SDKs (PocketBase, Apollo) return 204 on duplicate-in-flight aborts.

**Noise check:** if σ/p50 > 5% on the baseline, raise n to 50+ before relying on the Step 5 gates — short workloads with GC/JIT noise will not produce stable verdicts at n=20.

Save baseline artifacts to `./perf/baseline/`.

## Step 3 — Profile the hotspot

The benchmark says *what* is slow. A profile says *why*. You need both before patching.

Lead with a sampling profile of the hot path. The right tool depends on runtime:

- **Python**: `py-spy record -o profile.svg -- python script.py`
- **Native**: `samply record <command>`
- **Node / Bun**: `node --cpu-prof --cpu-prof-dir=./perf/cpuprof <entry>` produces a `.cpuprofile` (open in Chrome DevTools, or parse the JSON's `nodes`/`samples`/`timeDeltas` for top self-time). Bun: `bun --inspect <entry>`.
- **Browser**: DevTools Performance → record a real interaction → Bottom-Up by self-time.
- **API**: attach to the running server while load is in flight: `py-spy record --pid`, `clinic flame -- node app.js`, or `samply record -p <pid>`.

Identify top 1–3 functions by **self-time**, not total time. Cross-check that they sit on the call path from Step 2's workload.

**Loader noise** in short Node CLIs: top frames like `makeSyncRequest`, `compileSourceTextModule`, `tsx`/`ts-node` mean you're profiling the loader; switch to function mode (Step 1). Bun handles TS natively so this rarely applies there.

## Step 4 — Hypothesize and patch

State the hypothesis in plain English **before** writing code: "Function X is slow because Y; I will change Z, expecting A% improvement."

Common patterns, in rough order of frequency:

- Repeated work inside a hot loop → cache / hoist / memoize
- N+1 queries → batch / join / prefetch
- Sync I/O on hot path → async / batch / move off-path
- Wrong data structure (linear scan where set/dict works) → swap
- Re-parsing / re-compiling per call → do it once at module load
- Excessive allocations → reuse buffers, switch to iterators / generators
- Wrong algorithm (O(n²) where O(n log n) exists) → swap

Apply the **smallest** patch that tests the hypothesis. Run tests first; abort on failure.

If the patch is runtime-conditional (e.g., swap a JS dep for a native binding in Node only, keep the original in the browser), the deployment-target answer from Step 1 decides which path matters. A "Node-only" speedup in a browser-first project is a misfire.

## Step 5 — Verify (hard gates)

Re-run the **exact** Step 2 benchmark. Same workload, same hardware, same warm-up. Save to `./perf/run-N/`. Prefer interleaved A/B over sequential separate runs — system noise leaks across longer time gaps:

```bash
hyperfine --warmup 3 --runs 20 \
  --export-json compare.json \
  --export-markdown comparison.md \
  '<git stash; original command; git stash pop>' \
  '<optimized command>'
```

Three gates, ALL must pass:

1. **Tests pass.** Hard fail → revert.
2. **Improvement exceeds noise.** p50 drops ≥10% AND |Δ| > 2× pooled stddev.
3. **No regression elsewhere.** CLI: warm/cold both held? API: other endpoints unchanged? Library used in browser AND Node: both runtimes verified.

If accepted: report numerically — `"p50 412ms → 287ms, 1.43× faster, n=20, σ=4ms"`. If rejected: revert, append to `./perf/attempted.md`, form a new hypothesis or report back.

## Step 6 — Loop until diminishing returns

After each accepted patch, re-profile (Step 3). The bottleneck moves. Stop when any of:

- Success criterion from Step 1 is met
- Three consecutive hypotheses fail to produce an accepted patch
- Remaining hotspots are in third-party code you cannot modify

End with: baseline → final numbers, accepted patches with individual contributions, rejected hypotheses with reasons.

## Inviolable rules

- No speedup claim without a re-run on the same workload.
- Do not modify the benchmark to make the patch look better.
- One change per benchmark cycle.
- Tests pass, or revert.
- If no test suite exists, generate replay tests from captured real inputs before patching.
- Do not optimize blind: never skip Step 2 or Step 3.

## Supporting files (agent should create on first use)

- `scripts/baseline-cli.sh` — wraps Step 2 CLI invocation
- `scripts/baseline-api.sh` — wraps Step 2 Locust invocation
- `scripts/baseline-fn.sh` — wraps Step 2 function-mode replay (in-process timer, JSON out)
- `scripts/compare.py` — diffs hyperfine JSON files (sequential or single-file two-result) with stdev-aware significance check
- `scripts/analyze-cpuprof.mjs` — top self-time frames from a Node / DevTools `.cpuprofile`
- `templates/locustfile.py` — starter for API workloads (weighted `@task` per endpoint; weights mirror real traffic, ask the user if unknown)
- `templates/replay-test.py` — generates pytest from captured function inputs
