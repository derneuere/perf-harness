"""perf-harness CLI: init, check, compare."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Files to copy on `init`. Source paths are relative to the repo root.
_SCAFFOLD = [
    ("scripts/baseline-cli.sh", "scripts/baseline-cli.sh", 0o755),
    ("scripts/baseline-api.sh", "scripts/baseline-api.sh", 0o755),
    ("scripts/compare.py", "scripts/compare.py", 0o755),
    ("templates/locustfile.py", "perf/locustfile.py", 0o644),
    ("templates/replay-test.py", "perf/replay-test.py", 0o644),
    ("skill/SKILL.md", ".claude/skills/perf-harness/SKILL.md", 0o644),
]

_DIRS = ["perf/baseline", "perf/runs"]

_ATTEMPTED_HEADER = """\
# Attempted patches

One row per hypothesis you tested, accepted or rejected. Append, never edit.

| date | hypothesis | patch summary | result | notes |
|------|------------|---------------|--------|-------|
"""

# Tools the SKILL references. (name, install hint, optional)
_TOOLS = [
    ("hyperfine", "https://github.com/sharkdp/hyperfine#installation", False),
    ("locust",    "pip install locust",                                  True),
    ("py-spy",    "pip install py-spy",                                  True),
    ("samply",    "https://github.com/mstange/samply#installation",      True),
    ("strace",    "apt-get install strace (Linux only)",                 True),
    ("dtruss",    "preinstalled on macOS (requires sudo)",               True),
]


def _repo_root() -> Path:
    """Find the source repo root.

    perf-harness is intended to be installed editable from a clone (`pip
    install -e .`); the canonical files live at the repo root, not inside
    the package. We walk up from this module to find them.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "skill" / "SKILL.md").exists() and (parent / "scripts").is_dir():
            return parent
    raise SystemExit(
        "perf-harness: could not locate the source tree. Install editable from "
        "a clone: `pip install -e .` from the perf-harness repo root."
    )


def _read_source(rel: str) -> bytes:
    return (_repo_root() / rel).read_bytes()


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path).resolve()
    target.mkdir(parents=True, exist_ok=True)
    print(f"Scaffolding into {target}")

    written = 0
    skipped = 0
    for src_rel, dst_rel, mode in _SCAFFOLD:
        dst = target / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and not args.force:
            print(f"  skip   {dst_rel}  (exists; use --force to overwrite)")
            skipped += 1
            continue
        dst.write_bytes(_read_source(src_rel))
        try:
            dst.chmod(mode)
        except (OSError, NotImplementedError):
            pass  # Windows: chmod is largely a no-op
        print(f"  write  {dst_rel}")
        written += 1

    for d in _DIRS:
        (target / d).mkdir(parents=True, exist_ok=True)

    attempted = target / "perf" / "attempted.md"
    if not attempted.exists():
        attempted.write_text(_ATTEMPTED_HEADER)
        print(f"  write  perf/attempted.md")
        written += 1

    print(f"\nDone. {written} written, {skipped} skipped.")
    print("Next: read .claude/skills/perf-harness/SKILL.md and tell Claude what to optimize.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    print("Tool availability:\n")
    missing_required = 0
    width = max(len(t[0]) for t in _TOOLS)
    for name, hint, optional in _TOOLS:
        path = shutil.which(name)
        tag = "ok " if path else ("opt" if optional else "MISS")
        marker = "✓" if path else ("·" if optional else "✗")
        location = path or hint
        print(f"  {marker} {name.ljust(width)}  [{tag}]  {location}")
        if not path and not optional:
            missing_required += 1

    print()
    if missing_required:
        print(f"{missing_required} required tool(s) missing.")
        return 1
    print("Required tools present. (Optional ones can be installed as needed.)")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Thin pass-through to scripts/compare.py so the CLI works without bash."""
    script = _repo_root() / "scripts" / "compare.py"
    cmd = [sys.executable, str(script), *args.passthrough]
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="perf-harness",
        description="Scaffolding + tool checks for the perf-harness skill.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="scaffold ./perf, ./scripts, and the skill into a project")
    p_init.add_argument("path", nargs="?", default=".", help="target directory (default: cwd)")
    p_init.add_argument("--force", action="store_true", help="overwrite existing files")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="check that required perf tools are installed")
    p_check.set_defaults(func=cmd_check)

    p_compare = sub.add_parser(
        "compare",
        help="run scripts/compare.py (pass --help for its arguments)",
    )
    p_compare.add_argument("passthrough", nargs=argparse.REMAINDER,
                           help="arguments forwarded to compare.py")
    p_compare.set_defaults(func=cmd_compare)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
