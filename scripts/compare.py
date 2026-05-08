#!/usr/bin/env python3
"""
Diff two hyperfine JSON exports with stdev-aware significance check.

Implements the Step 5 gate from SKILL.md:
  p50 (median) drops >= MIN_DELTA_PCT  AND
  |median delta| > NOISE_K * pooled_stddev.

Default: MIN_DELTA_PCT=10, NOISE_K=2.

Usage:
  scripts/compare.py baseline.json candidate.json
  scripts/compare.py --min-delta 5 --noise-k 3 a.json b.json
  scripts/compare.py --json baseline.json candidate.json   # machine-readable

Each input file is the --export-json output of hyperfine. If a file contains
multiple commands, the first result is used; pass --baseline-index/--candidate-index
to pick a different one.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Run:
    label: str
    times: list[float]  # seconds

    @property
    def n(self) -> int:
        return len(self.times)

    @property
    def median(self) -> float:
        return statistics.median(self.times)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.times)

    @property
    def stddev(self) -> float:
        if self.n < 2:
            return 0.0
        return statistics.stdev(self.times)


def load_run(path: Path, index: int) -> Run:
    data = json.loads(path.read_text())
    results = data.get("results")
    if not results:
        raise SystemExit(f"{path}: no 'results' key (not a hyperfine JSON?)")
    if index >= len(results):
        raise SystemExit(
            f"{path}: --index {index} out of range (file has {len(results)} results)"
        )
    r = results[index]
    times = r.get("times")
    if not times:
        raise SystemExit(f"{path}: result {index} has no 'times' array")
    return Run(label=r.get("command", path.stem), times=times)


def pooled_stddev(a: Run, b: Run) -> float:
    """Standard pooled stddev: sqrt(((n1-1)s1^2 + (n2-1)s2^2) / (n1+n2-2))."""
    if a.n < 2 or b.n < 2:
        return max(a.stddev, b.stddev)
    num = (a.n - 1) * a.stddev ** 2 + (b.n - 1) * b.stddev ** 2
    den = a.n + b.n - 2
    return math.sqrt(num / den)


def fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f}ms"


def compare(
    baseline: Run,
    candidate: Run,
    min_delta_pct: float,
    noise_k: float,
) -> dict:
    delta_s = baseline.median - candidate.median  # positive = faster
    delta_pct = 100.0 * delta_s / baseline.median if baseline.median else 0.0
    speedup = baseline.median / candidate.median if candidate.median else float("inf")
    sigma = pooled_stddev(baseline, candidate)
    noise_threshold = noise_k * sigma

    gate_delta_pct = delta_pct >= min_delta_pct
    gate_above_noise = abs(delta_s) > noise_threshold
    accepted = gate_delta_pct and gate_above_noise and delta_s > 0

    return {
        "baseline": {
            "label": baseline.label,
            "n": baseline.n,
            "median_s": baseline.median,
            "mean_s": baseline.mean,
            "stddev_s": baseline.stddev,
        },
        "candidate": {
            "label": candidate.label,
            "n": candidate.n,
            "median_s": candidate.median,
            "mean_s": candidate.mean,
            "stddev_s": candidate.stddev,
        },
        "delta": {
            "median_s": delta_s,
            "median_pct": delta_pct,
            "speedup": speedup,
        },
        "noise": {
            "pooled_stddev_s": sigma,
            "threshold_s": noise_threshold,
            "noise_k": noise_k,
        },
        "gates": {
            "min_delta_pct": min_delta_pct,
            "delta_meets_min": gate_delta_pct,
            "delta_above_noise": gate_above_noise,
            "accepted": accepted,
        },
    }


def render(report: dict) -> str:
    b, c = report["baseline"], report["candidate"]
    d, n, g = report["delta"], report["noise"], report["gates"]

    lines = []
    lines.append(f"  baseline:  {fmt_ms(b['median_s']):>8}  (mean {fmt_ms(b['mean_s'])}, σ {fmt_ms(b['stddev_s'])}, n={b['n']})")
    lines.append(f"  candidate: {fmt_ms(c['median_s']):>8}  (mean {fmt_ms(c['mean_s'])}, σ {fmt_ms(c['stddev_s'])}, n={c['n']})")
    lines.append("")
    arrow = "→"
    lines.append(f"  median   {fmt_ms(b['median_s'])} {arrow} {fmt_ms(c['median_s'])}   "
                 f"Δ {d['median_pct']:+.1f}%   {d['speedup']:.2f}× speedup")
    lines.append(f"  noise    pooled σ {fmt_ms(n['pooled_stddev_s'])}   "
                 f"threshold (kσ={n['noise_k']:g}) {fmt_ms(n['threshold_s'])}")
    lines.append("")
    lines.append("  gates")
    lines.append(f"    [{'PASS' if g['delta_meets_min'] else 'FAIL'}] "
                 f"|Δ%| ≥ {g['min_delta_pct']:g}%   (got {d['median_pct']:+.1f}%)")
    lines.append(f"    [{'PASS' if g['delta_above_noise'] else 'FAIL'}] "
                 f"|Δ| > {n['noise_k']:g}σ          (got {fmt_ms(abs(d['median_s']))} vs {fmt_ms(n['threshold_s'])})")
    lines.append("")
    verdict = "ACCEPTED" if g["accepted"] else "REJECTED"
    lines.append(f"  verdict: {verdict}")
    if not g["accepted"] and d["median_s"] < 0:
        lines.append("  (candidate is slower than baseline)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Compare two hyperfine JSON results with significance check.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("baseline", type=Path, help="hyperfine --export-json file (slower / before)")
    p.add_argument("candidate", type=Path, help="hyperfine --export-json file (candidate / after)")
    p.add_argument("--baseline-index", type=int, default=0,
                   help="result index in baseline file (default 0)")
    p.add_argument("--candidate-index", type=int, default=0,
                   help="result index in candidate file (default 0)")
    p.add_argument("--min-delta", type=float, default=10.0, dest="min_delta_pct",
                   help="minimum median improvement %% to accept (default 10)")
    p.add_argument("--noise-k", type=float, default=2.0,
                   help="multiplier on pooled stddev for noise gate (default 2)")
    p.add_argument("--json", action="store_true",
                   help="emit JSON report instead of human-readable")
    args = p.parse_args(argv)

    baseline = load_run(args.baseline, args.baseline_index)
    candidate = load_run(args.candidate, args.candidate_index)

    report = compare(baseline, candidate, args.min_delta_pct, args.noise_k)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report))

    return 0 if report["gates"]["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
