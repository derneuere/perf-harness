# perf-harness

A profile-guided optimization skill for [Claude Code](https://claude.com/claude-code) (and any agent that loads `SKILL.md` files), plus a tiny scaffolding CLI.

The agent runs the loop **measure → locate → hypothesize → patch → re-measure**, with hard gates that reject any "speedup" that isn't statistically real on the same workload that produced the baseline.

## What's in here

```
skill/SKILL.md          # the skill itself — drop into .claude/skills/perf-harness/
scripts/
  baseline-cli.sh       # hyperfine wrapper for Step 2 (CLI mode)
  baseline-api.sh       # locust wrapper for Step 2 (API mode)
  compare.py            # diffs two hyperfine JSONs with stdev-aware significance check
templates/
  locustfile.py         # starter for API workloads
  replay-test.py        # record/replay scaffolding for function-mode optimization
src/perf_harness/       # tiny CLI: init, check, compare
tests/                  # tests for compare.py
```

## Quick start

### Use it in a project (no install)

The skill is a single Markdown file. Drop it where Claude Code looks for skills:

```bash
mkdir -p .claude/skills/perf-harness
cp skill/SKILL.md .claude/skills/perf-harness/SKILL.md
```

Then ask Claude something like:

> The CLI tool in `./bin/foo` takes ~2s on `examples/big.json`. Make it faster.

The skill triggers on phrases like *"make this faster"*, *"find the bottleneck"*, *"why is X slow"*, *"optimize this endpoint"* — see the YAML frontmatter for the full trigger description.

### With the CLI helper

```bash
git clone https://github.com/derneuere/perf-harness
cd perf-harness
pip install -e .

cd /path/to/your/project
perf-harness check          # verify hyperfine, locust, py-spy, etc. are installed
perf-harness init           # scaffold ./perf, ./scripts, .claude/skills/perf-harness/
```

`perf-harness init` creates:

```
.claude/skills/perf-harness/SKILL.md   # so Claude Code picks it up
scripts/baseline-cli.sh                # ready to run
scripts/baseline-api.sh
scripts/compare.py
perf/
  baseline/                            # Step 2 artifacts go here
  runs/                                # run-1/, run-2/, … from Step 5
  attempted.md                         # rejected hypotheses log
  locustfile.py                        # edit weights to match real traffic
  replay-test.py                       # function-mode scaffolding
```

The CLI is editable-install only — it reads canonical files from the repo clone. The skill itself is portable; if you don't want the CLI, just copy `skill/SKILL.md` and `scripts/*` directly.

## Required tools

The skill expects these on `$PATH`. `perf-harness check` reports availability.

| Tool        | Why                                | Install                                                |
|-------------|------------------------------------|--------------------------------------------------------|
| `hyperfine` | CLI benchmarking (required)        | <https://github.com/sharkdp/hyperfine#installation>    |
| `locust`    | HTTP load testing (API mode)       | `pip install locust`                                   |
| `py-spy`    | Python sampling profiler           | `pip install py-spy`                                   |
| `samply`    | Native sampling profiler           | <https://github.com/mstange/samply#installation>       |
| `strace`    | Linux syscall summary              | distro package                                         |
| `dtruss`    | macOS syscall summary              | preinstalled (needs `sudo`)                            |

## How the loop runs (TL;DR of `SKILL.md`)

1. **Classify**: CLI / API / function mode. Establish the workload and a numeric success criterion before running anything.
2. **Baseline**: `hyperfine` or `locust`, results into `./perf/baseline/`.
3. **Profile**: `strace -c` first (cheap, often decisive), then `py-spy`/`samply` for CPU-bound work.
4. **Hypothesize and patch**: state the hypothesis in plain English first; smallest change that tests it; tests must still pass.
5. **Verify**: re-run the *exact* baseline. Three gates — tests pass, p50 drops ≥10%, |Δ| > 2σ. Reject if any fails.
6. **Loop** until the success criterion is met or three hypotheses fail in a row.

The "inviolable rules" in the SKILL — no speedup claim without a re-run, one change per benchmark cycle, never modify the benchmark to make the patch look better — are the load-bearing parts.

## `compare.py`

Does the Step 5 significance check. Takes two `hyperfine --export-json` files:

```bash
scripts/compare.py perf/baseline/baseline.json perf/runs/run-1/run-1.json
# → human-readable verdict, exit code 0 if accepted

scripts/compare.py --json baseline.json candidate.json
# → machine-readable; exit code reflects gate outcome

# tune the gates
scripts/compare.py --min-delta 5 --noise-k 3 baseline.json candidate.json
```

Defaults: `--min-delta 10` (≥10% median improvement), `--noise-k 2` (|Δ| must exceed 2× pooled stddev). Both gates must pass; otherwise exit code is non-zero.

## License

MIT. See [LICENSE](LICENSE).
