"""Replay-test scaffolding for function-mode optimization.

When a user points at a single function with no runnable target and no
test suite, the SKILL says: capture inputs to the function during a real
run, then replay them as assertions before touching the code. This file
gives you both halves.

  Phase 1 — record:
    Wrap the target with @record_calls(...) and run a real workload.
    Inputs + outputs are pickled to a JSONL+pickle bundle.

  Phase 2 — replay:
    pytest picks up generated cases from the bundle and asserts that
    refactored code returns the same outputs (or equivalent under a
    user-supplied compare fn).

Adapt the imports + the `target` reference at the bottom for your code.
This is a starter, not a generic library — keep it small and obvious.
"""
from __future__ import annotations

import functools
import os
import pickle
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

_RECORD_LOCK = threading.Lock()


@dataclass
class Recorder:
    out_dir: Path
    max_cases: int = 500

    def __post_init__(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._count = 0

    def write(self, args: tuple, kwargs: dict, result: Any) -> None:
        with _RECORD_LOCK:
            if self._count >= self.max_cases:
                return
            case_id = f"{self._count:04d}_{uuid.uuid4().hex[:8]}"
            self._count += 1
        path = self.out_dir / f"{case_id}.pkl"
        with path.open("wb") as f:
            pickle.dump({"args": args, "kwargs": kwargs, "result": result}, f)


def record_calls(out_dir: str | os.PathLike, *, max_cases: int = 500):
    """Decorator: pickle (args, kwargs, result) for each call.

    Disable in production by setting PERF_RECORD=0.
    """
    rec = Recorder(Path(out_dir), max_cases=max_cases)

    def decorator(fn: Callable):
        if os.environ.get("PERF_RECORD", "1") == "0":
            return fn

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            try:
                rec.write(args, kwargs, result)
            except (pickle.PicklingError, TypeError):
                # Don't let recording break the real call.
                pass
            return result

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def load_cases(out_dir: str | os.PathLike) -> Iterable[dict]:
    for path in sorted(Path(out_dir).glob("*.pkl")):
        with path.open("rb") as f:
            yield pickle.load(f) | {"_path": str(path)}


def default_eq(expected: Any, actual: Any) -> bool:
    return expected == actual


# ---------------------------------------------------------------------------
# pytest hookup — adapt these two lines for your project
# ---------------------------------------------------------------------------
# from yourpkg.module import target_function as target
# CASES_DIR = Path(__file__).parent / "cases"

try:
    target  # noqa: F821
except NameError:
    target = None  # type: ignore[assignment]
    CASES_DIR = Path(__file__).parent / "cases"


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        cases = list(load_cases(CASES_DIR)) if CASES_DIR.exists() else []
        ids = [Path(c["_path"]).stem for c in cases]
        metafunc.parametrize("case", cases, ids=ids)


def test_replay(case):
    if target is None:
        import pytest
        pytest.skip("Set `target` and CASES_DIR at the top of replay-test.py")
    actual = target(*case["args"], **case["kwargs"])
    assert default_eq(case["result"], actual), (
        f"replay mismatch for {case['_path']}:\n"
        f"  expected: {case['result']!r}\n"
        f"  actual:   {actual!r}"
    )
