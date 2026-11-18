"""Times the Agentica benchmark programs against their Python and Go twins, in the evaluation image.

The Agentica programs and the Python twins come from agentica's benchmarks/ at the pinned commit (AGENTICA_COMMIT,
the 0.34.1 tag), the binary is the pinned release, and the Go twins are in bench/go/. Every runner runs in one
container of the evaluation image with no network, so all three see the same machine. The table is printed;
--check runs each program once and only compares the outputs."""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH.parent))

import run  # noqa: E402  (the runner of the evals, for the pinned Agentica)

BENCH_PATHS = ["benchmarks/programs", "benchmarks/python"]
SCALE_DEF = re.compile(r"^def scale\(\) -> Int\n  (?:return )?1\nend\n", re.MULTILINE)


def stage(directory: Path, names: list[str], size: int) -> None:
    """The files the container reads: the scaled Agentica programs, the Python and Go twins, the binary and
    measure.py."""
    sources = run.fetch_sources(run.AGENTICA_COMMIT, BENCH_PATHS, "bench")
    for folder in ("programs", "python", "go", "bin"):
        (directory / folder).mkdir()
    for name in names:
        text = (sources / "benchmarks" / "programs" / f"{name}.agc").read_text(encoding="utf-8")
        scaled, found = SCALE_DEF.subn(f"def scale() -> Int\n  {size}\nend\n", text)
        if found != 1:
            raise SystemExit(f"{name}.agc has no `def scale` returning 1")
        (directory / "programs" / f"{name}.agc").write_text(scaled, encoding="utf-8")
        twin = f"{name.replace('-', '_')}.py"
        shutil.copyfile(sources / "benchmarks" / "python" / twin, directory / "python" / twin)
        shutil.copyfile(BENCH / "go" / f"{name}.go", directory / "go" / f"{name}.go")
    shutil.copyfile(run.release_binary(), directory / "bin" / "agentica")
    (directory / "bin" / "agentica").chmod(0o755)
    shutil.copyfile(BENCH / "measure.py", directory / "measure.py")
    directory.chmod(0o755)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=5, help="timed runs per program and runner (default 5)")
    parser.add_argument("--size", type=int, default=1, help="work multiplier for every program (default 1)")
    parser.add_argument("--only", nargs="*", default=[], help="program names (default: every one with a Go twin)")
    parser.add_argument("--check", action="store_true", help="one run each: compare the outputs only")
    parser.add_argument("--image", default=run.DEFAULT_IMAGE)
    args = parser.parse_args()
    names = args.only or sorted(path.stem for path in (BENCH / "go").glob("*.go"))
    unknown = [name for name in names if not (BENCH / "go" / f"{name}.go").is_file()]
    if unknown:
        parser.error(f"no Go twin for {', '.join(unknown)}")
    run.require_docker()
    with tempfile.TemporaryDirectory(prefix="agentica-bench-") as directory:
        stage(Path(directory), names, args.size)
        command = ["docker", "run", "--rm", "--network=none", "--tmpfs", "/tmp:rw,exec,size=1g",
                   "--mount", f"type=bind,src={directory},dst=/bench,readonly", args.image,
                   "python3", "-I", "/bench/measure.py", "--runs", str(1 if args.check else args.runs),
                   "--size", str(args.size), *(["--check"] if args.check else []), *names]
        return subprocess.run(command).returncode


if __name__ == "__main__":
    sys.exit(main())
