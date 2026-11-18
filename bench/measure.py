"""Runs inside the evaluation image (bench/run.py starts it): builds the Go twins, then times each program on
agentica, python3 and the Go binary, and checks that the three print the same."""

import argparse
import os
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

BENCH = Path("/bench")
BUILT = Path("/tmp/bench-bin")
RUNNERS = ["agentica", "python", "go"]
# A one-minute load average above this makes the numbers rough; the report says so.
BUSY_LOAD = 2.0


@dataclass
class Result:
    status: str  # ok, mismatch, failed
    median: float = 0.0
    note: str = ""


def timed(command: list[str]) -> tuple[float, str, str, int]:
    """Wall seconds, stdout, stderr and the exit status of one run."""
    began = time.perf_counter()
    done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True)
    seconds = time.perf_counter() - began
    return seconds, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace"), done.returncode


def command_of(runner: str, name: str, size: int) -> list[str]:
    if runner == "agentica":
        return [str(BENCH / "bin" / "agentica"), str(BENCH / "programs" / f"{name}.agc")]
    if runner == "python":
        return ["python3", "-I", str(BENCH / "python" / f"{name.replace('-', '_')}.py"), str(size)]
    return [str(BUILT / name), str(size)]


def measure(command: list[str], runs: int, expected: str | None) -> tuple[Result, str]:
    """A first run that is not timed (it warms the caches and gives the output), then `runs` timed ones."""
    times, output = [], None
    for index in range(runs + 1):
        seconds, stdout, stderr, code = timed(command)
        if code != 0:
            last = (stderr.strip() or stdout.strip()).splitlines()
            return Result("failed", note=last[-1][:120] if last else f"exit {code}"), ""
        if output is None:
            output = stdout
            if expected is not None and stdout != expected:
                return Result("mismatch", note=(stdout.strip().splitlines() or ["no output"])[-1][:120]), stdout
        if index > 0 or runs == 0:
            times.append(seconds)
    return Result("ok", statistics.median(times)), output or ""


def build(names: list[str]) -> dict[str, str]:
    """Builds every Go twin; the failures by name. The image's build cache is read-only, so the build gets a copy."""
    BUILT.mkdir(parents=True, exist_ok=True)
    cache = Path("/tmp/go-cache")
    if not cache.exists() and Path("/opt/go-cache").is_dir():
        shutil.copytree("/opt/go-cache", cache)
    env = dict(os.environ, GOCACHE=str(cache))
    failures = {}
    for name in names:
        done = subprocess.run(["go", "build", "-o", str(BUILT / name), str(BENCH / "go" / f"{name}.go")],
                              capture_output=True, text=True, env=env)
        if done.returncode != 0:
            failures[name] = (done.stderr.strip().splitlines() or ["build failed"])[-1][:120]
    return failures


def version(command: list[str]) -> str:
    try:
        done = subprocess.run(command, capture_output=True, text=True)
    except OSError:
        return "-"
    return (done.stdout.strip() or done.stderr.strip()).splitlines()[0]


def cell(result: Result) -> str:
    return f"{result.median:.3f}" if result.status == "ok" else result.status


def ratio(numerator: Result, denominator: Result) -> str:
    if numerator.status != "ok" or denominator.status != "ok" or denominator.median <= 0:
        return "-"
    return f"{numerator.median / denominator.median:.1f}x"


def table(rows: dict[str, dict[str, Result]]) -> list[str]:
    lines = ["| program | agentica s | python s | go s | python / agentica | agentica / go | note |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for name, results in rows.items():
        agentica, python, go = (results[runner] for runner in RUNNERS)
        note = "; ".join(f"{runner}: {results[runner].note}" for runner in RUNNERS if results[runner].note)
        lines.append(f"| {name} | {cell(agentica)} | {cell(python)} | {cell(go)} | {ratio(python, agentica)} | "
                     f"{ratio(agentica, go)} | {note} |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--size", type=int, default=1)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    one, five, fifteen = os.getloadavg()
    print(f"agentica {version([str(BENCH / 'bin' / 'agentica'), '--version'])}, {version(['python3', '--version'])}, "
          f"{version(['go', 'version'])}")
    print(f"load average {one:.2f} {five:.2f} {fifteen:.2f}, {os.cpu_count()} cores"
          + ("; measured under load, the numbers are rough" if one > BUSY_LOAD else ""))
    began = time.perf_counter()
    failures = build(args.names)
    print(f"go build of {len(args.names)} twins: {time.perf_counter() - began:.1f} s\n", flush=True)
    rows: dict[str, dict[str, Result]] = {}
    for name in args.names:
        results: dict[str, Result] = {}
        expected = None
        for runner in RUNNERS:
            if runner == "go" and name in failures:
                results[runner] = Result("failed", note=failures[name])
                continue
            result, output = measure(command_of(runner, name, args.size), 0 if args.check else args.runs, expected)
            if result.status == "ok" and expected is None:
                expected = output
            results[runner] = result
        rows[name] = results
        print(f"{name}: " + ", ".join(f"{runner} {cell(results[runner])}" for runner in RUNNERS),
              file=sys.stderr, flush=True)
    title = "outputs" if args.check else f"size {args.size}, median of {args.runs} runs after one warm-up run"
    print(f"## Programs ({title})\n")
    print("\n".join(table(rows)))
    bad = [name for name, results in rows.items() if any(r.status != "ok" for r in results.values())]
    if bad:
        print(f"\nnot ok: {', '.join(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
