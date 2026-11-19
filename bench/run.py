"""Times the Agentica benchmark programs against their Python and Go twins, in the evaluation image.

The Agentica programs and the Python twins come from agentica's benchmarks/ at the pinned commit (AGENTICA_COMMIT,
the 0.35.0 tag), the binary is the pinned release, and the Go twins are in bench/go/. Every runner runs in one
container of the evaluation image with no network, so all of them see the same machine. The table is printed;
--check runs each program once and only reports whether the outputs match."""

import argparse
import re
import shutil
import uuid
import subprocess
import sys
import tempfile
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH.parent))

import run  # noqa: E402  (the runner of the evals, for the pinned Agentica)

BENCH_PATHS = ["benchmarks/programs", "benchmarks/python"]
# The versions the numbers are for: Go is pinned by the Dockerfile (GO_VERSION, with its checksum); Python is the
# python3 of the base image, pinned by digest (Debian trixie).
PYTHON_VERSION = "3.13"
GO_VERSION = re.search(r"^ARG GO_VERSION=(\S+)$", (BENCH.parent / "Dockerfile").read_text(encoding="utf-8"),
                       re.MULTILINE)[1]
# A start-up baseline: the smallest program in each language.
HELLO = {"programs/hello.agc": 'def main() -> Void\n  puts("hello")\nend\n', "python/hello.py": 'print("hello")\n',
         "go/hello.go": 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("hello")\n}\n'}
# The work size of a program: `def scale() -> Int` returning 1, in its block or its one-line form.
SCALE_DEF = re.compile(r"^def scale\(\) -> Int(?:\n  (?:return )?1\nend| = 1)$", re.MULTILINE)


def stage(directory: Path, names: list[str], size: int) -> None:
    """The files the container reads: the scaled Agentica programs, the Python and Go twins, the binary and
    measure.py."""
    sources = run.fetch_sources(run.AGENTICA_COMMIT, BENCH_PATHS, "bench")
    for folder in ("programs", "python", "go", "bin"):
        (directory / folder).mkdir()
    for name in names:
        text = (sources / "benchmarks" / "programs" / f"{name}.agc").read_text(encoding="utf-8")
        scaled, found = SCALE_DEF.subn(f"def scale() -> Int = {size}", text)
        if found != 1:
            raise SystemExit(f"{name}.agc has no `def scale` returning 1")
        (directory / "programs" / f"{name}.agc").write_text(scaled, encoding="utf-8")
        twin = f"{name.replace('-', '_')}.py"
        shutil.copyfile(sources / "benchmarks" / "python" / twin, directory / "python" / twin)
        shutil.copyfile(BENCH / "go" / f"{name}.go", directory / "go" / f"{name}.go")
    for path, text in HELLO.items():
        (directory / path).write_text(text, encoding="utf-8")
    shutil.copyfile(run.release_binary(), directory / "bin" / "agentica")
    (directory / "bin" / "agentica").chmod(0o755)
    shutil.copyfile(BENCH / "measure.py", directory / "measure.py")
    directory.chmod(0o755)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=5, help="timed runs per program and runner (default 5)")
    parser.add_argument("--size", type=int, default=5, help="work multiplier for every program (default 5)")
    parser.add_argument("--only", nargs="*", default=[], help="program names (default: every one with a Go twin)")
    parser.add_argument("--check", action="store_true", help="one run each: compare the outputs only")
    parser.add_argument("--image", default=run.DEFAULT_IMAGE)
    parser.add_argument("--tmpfs", default="1g", help="size of the container's /tmp, where the file programs write "
                        "(default 1g; raise it with --size above 20)")
    args = parser.parse_args()
    if args.runs < 1 or args.size < 1:
        parser.error("--runs and --size must be at least 1")
    names = args.only or sorted(path.stem for path in (BENCH / "go").glob("*.go"))
    unknown = [name for name in names if not (BENCH / "go" / f"{name}.go").is_file()]
    if unknown:
        parser.error(f"no Go twin for {', '.join(unknown)}")
    run.require_docker()
    if not run.image_exists(args.image):
        run.build_image(args.image)
    size = 1 if args.check else args.size
    with tempfile.TemporaryDirectory(prefix="agentica-bench-") as directory:
        stage(Path(directory), names, size)
        # Every core of the machine, as a user's program would get; the files the programs write go to the tmpfs.
        command = ["docker", "run", "--rm", "--init", "--name", f"agentica-bench-{uuid.uuid4().hex[:12]}",
                   "--network=none", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=512",
                   "--tmpfs", f"/tmp:rw,exec,size={args.tmpfs}",
                   "--mount", f"type=bind,src={directory},dst=/bench,readonly", args.image,
                   "python3", "-I", "/bench/measure.py", "--runs", str(args.runs), "--size", str(size),
                   "--python-version", PYTHON_VERSION, "--go-version", GO_VERSION,
                   *(["--check"] if args.check else []), *names]
        return subprocess.run(command).returncode


if __name__ == "__main__":
    sys.exit(main())
