"""Tests for scripts/compare.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPARE_PATH = REPO_ROOT / "scripts" / "compare.py"


def _load_compare():
    spec = importlib.util.spec_from_file_location("compare", COMPARE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


compare_mod = _load_compare()


def hf_json(times_s: list[float], command: str = "cmd") -> dict:
    """Build a minimal hyperfine-shaped JSON payload."""
    import statistics

    return {
        "results": [
            {
                "command": command,
                "mean": statistics.fmean(times_s),
                "stddev": statistics.stdev(times_s) if len(times_s) > 1 else 0.0,
                "median": statistics.median(times_s),
                "min": min(times_s),
                "max": max(times_s),
                "times": times_s,
                "exit_codes": [0] * len(times_s),
            }
        ]
    }


def write_json(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return p


def test_clear_speedup_is_accepted(tmp_path):
    base = write_json(tmp_path, "base.json", hf_json([0.400] * 20))
    cand = write_json(tmp_path, "cand.json", hf_json([0.250] * 20))
    rc = compare_mod.main([str(base), str(cand)])
    assert rc == 0


def test_no_change_is_rejected(tmp_path):
    base = write_json(tmp_path, "base.json", hf_json([0.400] * 20))
    cand = write_json(tmp_path, "cand.json", hf_json([0.400] * 20))
    rc = compare_mod.main([str(base), str(cand)])
    assert rc != 0


def test_regression_is_rejected(tmp_path):
    base = write_json(tmp_path, "base.json", hf_json([0.400] * 20))
    cand = write_json(tmp_path, "cand.json", hf_json([0.500] * 20))
    rc = compare_mod.main([str(base), str(cand)])
    assert rc != 0


def test_below_min_delta_rejected(tmp_path):
    # 5% improvement: below default 10% gate.
    base = write_json(tmp_path, "base.json", hf_json([0.400] * 20))
    cand = write_json(tmp_path, "cand.json", hf_json([0.380] * 20))
    rc = compare_mod.main([str(base), str(cand)])
    assert rc != 0


def test_min_delta_override_accepts(tmp_path):
    # Same 5% improvement with --min-delta 5 should pass (still need to clear noise gate).
    base = write_json(tmp_path, "base.json", hf_json([0.400] * 20))
    cand = write_json(tmp_path, "cand.json", hf_json([0.380] * 20))
    rc = compare_mod.main(["--min-delta", "5", str(base), str(cand)])
    assert rc == 0


def test_noisy_runs_below_noise_threshold_rejected(tmp_path):
    # Big stddev relative to the delta: 2× pooled σ exceeds the median delta.
    noisy_a = [0.40 + 0.05 * (i % 4 - 1.5) for i in range(20)]  # σ ~ 0.05
    noisy_b = [0.36 + 0.05 * (i % 4 - 1.5) for i in range(20)]  # σ ~ 0.05
    base = write_json(tmp_path, "base.json", hf_json(noisy_a))
    cand = write_json(tmp_path, "cand.json", hf_json(noisy_b))
    rc = compare_mod.main([str(base), str(cand)])
    assert rc != 0


def test_json_mode_emits_full_report(tmp_path, capsys):
    base = write_json(tmp_path, "base.json", hf_json([0.400] * 20))
    cand = write_json(tmp_path, "cand.json", hf_json([0.250] * 20))
    compare_mod.main(["--json", str(base), str(cand)])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["gates"]["accepted"] is True
    assert payload["delta"]["speedup"] == pytest.approx(0.400 / 0.250, rel=1e-6)
    assert payload["baseline"]["n"] == 20
    assert payload["candidate"]["n"] == 20


def test_invalid_file_errors(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")  # no 'results' key
    good = write_json(tmp_path, "good.json", hf_json([0.4] * 5))
    with pytest.raises(SystemExit):
        compare_mod.main([str(bad), str(good)])


def test_index_out_of_range(tmp_path):
    base = write_json(tmp_path, "base.json", hf_json([0.4] * 5))
    cand = write_json(tmp_path, "cand.json", hf_json([0.3] * 5))
    with pytest.raises(SystemExit):
        compare_mod.main(["--baseline-index", "5", str(base), str(cand)])
