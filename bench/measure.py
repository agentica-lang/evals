"""Runs inside the evaluation image (bench/run.py starts it): builds the Go twins and compiles the Agentica programs,
then times each program on four runners and checks that they print the same.

The runners: `agentica` runs the compiled bytecode (`agentica run -- FILE.agcb`, the compile is not timed), as
agentica's own benchmarks do; `agentica cold` is `agentica FILE.agc`, which runs the front end every time (the cold
start a user sees); `python` is python3 on the twin; `go` is the built twin (the build is not timed). Each run of a
program goes through the four runners in turn, so a change in the machine's load hits them alike."""

import argparse
import os
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BENCH = Path("/bench")
BUILT = Path("/tmp/bench-build")
AGENTICA = str(BENCH / "bin" / "agentica")
RUNNERS = ["agentica", "agentica cold", "python", "go"]
HELLO = "hello"
# A one-minute load average above this makes the numbers rough; the report says so.
BUSY_LOAD = 2.0


@dataclass
class Result:
    status: str = "ok"  # ok, mismatch, failed
    times: list[float] = field(default_factory=list)
    note: str = ""

    @property
    def median(self) -> float:
        return statistics.median(self.times) if self.times else 0.0


def timed(command: list[str]) -> tuple[float, str, str, int]:
    """Wall seconds, stdout, stderr and the exit status of one run."""
    began = time.perf_counter()
    done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True)
    seconds = time.perf_counter() - began
    return seconds, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace"), done.returncode


def command_of(runner: str, name: str, size: int) -> list[str]:
    if runner == "agentica":
        return [AGENTICA, "run", "--", str(BUILT / f"{name}.agcb")]
    if runner == "agentica cold":
        return [AGENTICA, str(BENCH / "programs" / f"{name}.agc")]
    if runner == "python":
        return ["python3", "-I", str(BENCH / "python" / f"{name.replace('-', '_')}.py"), str(size)]
    return [str(BUILT / name), str(size)]


def last_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[-1][:120] if lines else "no output"


def measure(name: str, size: int, runs: int) -> dict[str, Result]:
    """One run of each runner that is not timed (it warms the caches and gives the outputs to compare), then `runs`
    rounds that go through the runners in turn."""
    results = {runner: Result() for runner in RUNNERS}
    expected = None
    for round_ in range(runs + 1):
        for runner, result in results.items():
            if result.status != "ok":
                continue
            seconds, stdout, stderr, code = timed(command_of(runner, name, size))
            if code != 0:
                result.status, result.note = "failed", last_line(stderr or stdout)
            elif round_ == 0:
                if expected is None:
                    expected = stdout
                elif stdout != expected:
                    result.status, result.note = "mismatch", last_line(stdout)
            else:
                result.times.append(seconds)
    return results


def prepare(names: list[str]) -> dict[str, str]:
    """Builds every Go twin and compiles every Agentica program; the failures by name. The image's Go build cache is
    read-only, so the build gets a copy."""
    BUILT.mkdir(parents=True, exist_ok=True)
    cache = Path("/tmp/go-cache")
    if not cache.exists() and Path("/opt/go-cache").is_dir():
        shutil.copytree("/opt/go-cache", cache)
    env = dict(os.environ, GOCACHE=str(cache))
    failures = {}
    for name in names:
        built = subprocess.run(["go", "build", "-o", str(BUILT / name), str(BENCH / "go" / f"{name}.go")],
                               capture_output=True, text=True, env=env)
        compiled = subprocess.run([AGENTICA, "compile", str(BENCH / "programs" / f"{name}.agc"), "-o",
                                   str(BUILT / f"{name}.agcb")], capture_output=True, text=True)
        for step, done in (("go build", built), ("agentica compile", compiled)):
            if done.returncode != 0:
                failures[name] = f"{step}: {last_line(done.stderr)}"
    return failures


def version(command: list[str]) -> str:
    try:
        done = subprocess.run(command, capture_output=True, text=True)
    except OSError:
        return "-"
    return (done.stdout.strip() or done.stderr.strip()).splitlines()[0]


def load() -> str:
    one, five, fifteen = os.getloadavg()
    note = f"load average {one:.2f} {five:.2f} {fifteen:.2f}"
    return note + (" (busy: the numbers are rough)" if one > BUSY_LOAD else "")


def cell(result: Result) -> str:
    return f"{result.median:.3f}" if result.status == "ok" else result.status


def against(agentica: Result, other: Result) -> str:
    """How Agentica's time compares with another runner's: `2.0x faster` or `3.5x slower`."""
    if agentica.status != "ok" or other.status != "ok" or min(agentica.median, other.median) <= 0:
        return "-"
    if agentica.median <= other.median:
        return f"{other.median / agentica.median:.1f}x faster"
    return f"{agentica.median / other.median:.1f}x slower"


def table(rows: dict[str, dict[str, Result]]) -> list[str]:
    lines = ["| program | agentica s | agentica cold s | python s | go s | agentica vs python | agentica vs go | note |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for name, results in rows.items():
        agentica, cold, python, go = (results[runner] for runner in RUNNERS)
        note = "; ".join(f"{runner}: {result.note}" for runner, result in results.items() if result.note)
        lines.append(f"| {name} | {cell(agentica)} | {cell(cold)} | {cell(python)} | {cell(go)} | "
                     f"{against(agentica, python)} | {against(agentica, go)} | {note} |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--size", type=int, default=1)
    parser.add_argument("--check", action="store_true", help="one run each: report whether the outputs match")
    parser.add_argument("--python-version", default="")
    parser.add_argument("--go-version", default="")
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    python, go = version(["python3", "--version"]), version(["go", "version"])
    if not python.startswith(f"Python {args.python_version}.") or f"go{args.go_version} " not in go:
        raise SystemExit(f"the image has {python} and {go}, not Python {args.python_version} and "
                         f"go{args.go_version}: rebuild it (make image)")
    names = [HELLO, *args.names]
    print(f"agentica {version([AGENTICA, '--version'])}, {python}, {go}; {os.cpu_count()} cores")
    print(f"start: {load()}", flush=True)
    began = time.perf_counter()
    failures = prepare(names)
    print(f"go build and agentica compile of {len(names)} programs: {time.perf_counter() - began:.1f} s",
          flush=True)
    rows: dict[str, dict[str, Result]] = {}
    for name in names:
        if name in failures:
            rows[name] = {runner: Result("failed", note=failures[name]) for runner in RUNNERS}
        else:
            rows[name] = measure(name, args.size, 0 if args.check else args.runs)
        print(f"{name}: " + ", ".join(f"{runner} {cell(rows[name][runner])}" for runner in RUNNERS),
              file=sys.stderr, flush=True)
    bad = {name: results for name, results in rows.items() if any(r.status != "ok" for r in results.values())}
    if args.check:
        for name, results in rows.items():
            problems = "; ".join(f"{runner} {r.status}: {r.note}" for runner, r in results.items() if r.status != "ok")
            print(f"{name}: {problems or 'same output'}")
    else:
        print(f"end: {load()}\n")
        print(f"## Programs (size {args.size}, median of {args.runs} runs after one warm-up run)\n")
        print("\n".join(table(rows)))
    if bad:
        print(f"\nnot ok: {', '.join(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
