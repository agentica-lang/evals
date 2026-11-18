#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

EVAL = Path(__file__).resolve().parent
TASKS = EVAL / "tasks"
CACHE = EVAL / ".cache"
# The pinned Agentica: the release binary the agentica arms run, and the commit of its tag, which gives the skill,
# the grammar, the library pages and the examples. --agentica and --agentica-src replace them.
AGENTICA_VERSION = "0.34.1"
AGENTICA_ARCHIVE = f"agentica-{AGENTICA_VERSION}-linux-x86_64.tar.gz"
AGENTICA_ARCHIVE_SHA256 = "f1c7caa3947ac5947a87566febb1c4b06f05793bd4f03752b21fd416b44b73db"
AGENTICA_COMMIT = "d73c9dc5b69e813e783b006fff203760488f3f47"
AGENTICA_REPO = "https://github.com/agentica-lang/agentica"
SOURCE_PATHS = [".agents/skills/agentica-programming", "docs/grammar", "site/content/library", "examples"]
# The Agentica sources and the runtime folder (bin/agentica) copied into each agentica workspace.
ROOT = CACHE / f"agentica-{AGENTICA_COMMIT[:12]}"
RUNTIME = CACHE / "runtime"
# The packages of the ecosystem tasks: agentica.toml and agentica.lock (Bond, agentica-db), go.mod and go.sum
# (modernc.org/sqlite, which the image carries). The online docs follow the latest releases, which the lock pins.
ECOSYSTEM = EVAL / "ecosystem"
# The docs of the pinned releases only: Bond's versioned llms.txt, and agentica-db's site pages at the locked commit
# (it has no versioned llms.txt), copied into docs/agentica-db/. Not the site's root llms.txt, which links a Bond and
# agentica-db tutorial that is nearly an ecosystem task.
BOND_DOCS = "https://www.agentica-lang.com/bond/0.15.1/llms.txt"
ARMS = {"skill": "agc", "grammar": "agc", "binary": "agc", "python": "py", "typed-python": "py", "skill-nocli": "agc",
        "go": "go"}
TYPED_ARMS = {"typed-python"}
SKILL_ARMS = {"skill", "skill-nocli"}
# Arms that run only when asked for with --arms: the default is the five arms of the early rounds.
OPT_IN_ARMS = {"skill-nocli", "go"}
NOCLI_NOTE = "agentica --help and agentica help still name the four query commands; the wrapper only refuses them"
REFERENCE_ARMS = ["binary", "python", "typed-python", "go"]
CHECKER = ["mypy", "--strict", "--cache-dir=/dev/null"]
CHECK_TIMEOUT = 90
# The go arm checks with `go vet` and then `go build`, in file mode: start.go sits next to solution.go, and both are
# package main.
GO_VET = ["go", "vet", "solution.go"]
# -gcflags=-e lists every compile error, not the first ten.
GO_BUILD = ["go", "build", "-gcflags=-e", "-o", "solution", "solution.go"]
GO_FILE_ERROR = re.compile(r"^(?:vet: )?\S+\.go:\d+(?::\d+)?: ", re.MULTILINE)
NET_STRONG = re.compile(r"\bwget\b|\bgit\s+clone\b|github\.com|\bpip3?\s+install\b|\bnpm\b|\bapt(?:-get)?\b"
                        r"|\bgo\s+(?:-C\s+\S+\s+)?(?:get|install|mod\s+(?:download|tidy))\b|\bGOPROXY=|golang\.org"
                        r"|\S+@(?:v\d|latest\b)")
NET_WEAK = re.compile(r"\bcurl\b|\burllib\b")
LOOPBACK = re.compile(r"\blocalhost\b|127\.0\.0\.1")
# A segment may open with a keyword, a group or a substitution, then wrappers: `env` (options, NAME=value),
# `time -p`, `timeout` (options, then the duration), `nohup`, `xargs` (options), `uv run` and NAME=value.
SEGMENT_OPENER = r"(?:(?:do|then|else)\s+|[!{(]\s*|\$\(\s*|`\s*|\w+=(?:\$\(|`)\s*)*"
WRAPPER = (r"(?:(?:\S*/)?env(?:\s+(?:-u\s+\S+|-\S+|\w+=\S*))*|time(?:\s+-p)?"
           r"|timeout(?:\s+(?:-[sk]\s+\S+|-\S+))*\s+\d\S*|nohup|xargs(?:\s+(?:-[nILPdsE]\s*\S+|-\S+))*"
           r"|uv\s+run|\w+=\S*)")
COMMAND_PREFIX = rf"^\s*{SEGMENT_OPENER}(?:{WRAPPER}\s+)*"
# The go command, also with `-C DIR` before the subcommand.
GO = r"(?:\S*/)?go\s+(?:-C\s+\S+\s+)?"
CHECK_COMMAND = re.compile(COMMAND_PREFIX + r"(?:(?:python3?\s+-m\s+)?(?:\S*/)?mypy|(?:\S*/)?agentica\s+check"
                           rf"|{GO}(?:vet|build))\b")
VET_COMMAND = re.compile(COMMAND_PREFIX + GO + r"vet\b")
BUILD_COMMAND = re.compile(COMMAND_PREFIX + GO + r"build\b(?P<args>.*)")
MYPY_COMMAND = re.compile(COMMAND_PREFIX + r"(?:python3?\s+-m\s+)?(?:\S*/)?mypy\b")
# A check or run call starts a shell segment with the program; a path that names it (`cat skills/agentica-programming/x`)
# is no call.
RUN_COMMAND = re.compile(COMMAND_PREFIX + r"(?:\S*/)?(?:agentica(?:-real)?|python3?(?:\.\d+)?|mypy"
                         rf"|{GO}(?:vet|build|run|test))(?=\s|$)")
SHELL_SCRIPT = re.compile(COMMAND_PREFIX + r"(?:\S*/)?(?:ba)?sh\s+(?:-[a-z]+\s+)*?-[a-z]*c[a-z]*\s+"
                          r"(?:'([^']*)'|\"((?:[^\"\\]|\\.)*)\")")
GO_COMMAND = re.compile(COMMAND_PREFIX + GO + r"(?:vet|build|run|test)\b")
# `go vet` puts "vet: " before the first type error of a file it cannot load.
GO_ERROR = re.compile(r"^\s*(?:vet: )?\S+\.go:\d+(?::\d+)?: |^panic: |^fatal error: |^\s*--- FAIL", re.MULTILINE)
# The common shell forms that write the solution: a redirection (a `cat` heredoc too), `tee`, `sed -i`, `cp` or `mv`
# onto it, and `open('solution.py', 'w')` in a `python -c`. Other forms (a script, `dd`, `install`) are not seen.
SOLUTION = r"['\"]?(?:\S*/)?solution\.(?:agc|py|go)(?![\w.])"
SHELL_EDIT = re.compile(rf">>?\s*{SOLUTION}|\btee\s+(?:-a\s+)?{SOLUTION}|^\s*sed\s+-i.*\s{SOLUTION}"
                        rf"|^\s*(?:cp|mv)\s.*\s{SOLUTION}['\"]?\s*$|\bopen\(\s*{SOLUTION}['\"]?\s*,\s*['\"][wa]")
# The same forms as SHELL_EDIT for any source file path (a tree task): `open(...)` counts only in a write mode.
TREE_EDIT = re.compile(r"(?P<how>>>?\s*|\btee\s+(?:-a\s+)?|^\s*sed\s+-i.*\s|^\s*(?:cp|mv)\s.*\s|\bopen\(\s*)['\"]?"
                       r"(?P<path>(?:\S*/)?[\w.-]+\.(?:agc|py|go))(?![\w.])(?P<mode>['\"]?\s*,\s*['\"][wa])?")
EDIT_TOOLS = {"edit", "write"}
DROPPED_EVENTS = {"message_update", "tool_execution_update"}
# `agentica [--json|--ai|--partial] outline|type-at|symbol|refs ...`, also through a path (`dist/agentica`) or the
# renamed binary of the skill-nocli arm (`agentica-real`).
# Global options may come first: flags, `--` and the four that take a value.
QUERY_COMMAND = re.compile(COMMAND_PREFIX + r"(?:\S*/)?agentica(?:-real)?\s+"
                           r"(?:(?:--(?:json|ai|partial|deny-run|deny-native|dump|dump-ir)|--)\s+"
                           r"|--(?:max-steps|seed|flush-timeout|schedulers|steps)\s+\S+\s+)*"
                           r"(?:outline|type-at|symbol|refs)(?=\s|$)")
READ_COMMAND = re.compile(COMMAND_PREFIX + r"(?:\S*/)?(?:cat|rg|sed|head|grep|tail)(?=\s|$)")
REFUSED_LOG = ".refused-queries"
REAL_BINARY = "agentica-real"
# The wrapper of the skill-nocli arm. It refuses the first word that is not an option (or the value of one) when it
# names a query command (exit 2, a short stderr line, one line in REFUSED_LOG so the runner can count refusals) and
# hands everything else to the real binary, with exec so the exit status and the signals are the binary's.
QUERY_WRAPPER = """#!/bin/sh
case $0 in */*) here=${0%/*} ;; *) here=. ;; esac
skip=0
for word in "$@"; do
  if [ "$skip" = 1 ]; then skip=0; continue; fi
  case $word in
    --max-steps|--seed|--flush-timeout|--schedulers|--steps) skip=1 ;;
    -*) ;;
    outline|type-at|symbol|refs)
      echo "$word" >> "$here/@LOG@"
      echo "agentica: '$word' is not available in this evaluation arm" >&2
      exit 2 ;;
    *) break ;;
  esac
done
exec "$here/@REAL@" "$@"
""".replace("@LOG@", REFUSED_LOG).replace("@REAL@", REAL_BINARY)
# What the skill copy of the skill-nocli arm must not name any more.
# A run of the agent's own tests: a test runner, or a test file run directly.
SPEC_COMMAND = re.compile(COMMAND_PREFIX + r"(?:(?:\S*/)?agentica(?:-real)?\s+test\b|python3?\s+-m\s+(?:unittest|pytest)\b"
                          r"|(?:\S*/)?pytest\b|" + GO + r"test\b|(?:\S*/)?(?:agentica(?:-real)?|python3?)\s+(?:\S+\s+)*?"
                          r"(?:\S*/)?(?:test_[\w-]*|[\w-]*_test)\.(?:py|agc)\b)")
QUERY_MENTION = re.compile(r"queries\.md|analysis\.md|QUERY-|std/analysis|`type-at`|agentica\s+(?:outline|type-at|symbol|refs)\b")
TYPE_SILENCE = re.compile(r"#\s*mypy:|#\s*type:\s*ignore")
TYPE_ESCAPE = re.compile(r"\bAny\b|\bcast\(|\bno_type_check\b|\bTYPE_CHECKING\b")
MISSING_COMMAND = (126, 127)
AGENT_NETWORK = True
CASE_TIMEOUT = 10
# A tree task's solution is every file of the arm's language in the workspace, outside the folders the harness puts
# there (the prompt names them as reserved) and outside test files.
TREE_SKIP = {"bin", "skills", "deps", "docs", "examples"}
TREE_LIMIT = 200
TREE_FILE_LIMIT = 1 << 20
TEST_FILE = re.compile(r"(?:^|/)(?:tests/|test_[^/]*\.py$|[^/]*_test\.(?:py|go|agc)$)")
# The tree build writes a hidden name, which no source folder can take (hidden folders are not graded).
GO_TREE_BINARY = ".solution-bin"
GO_TREE_VET = ["go", "vet", "./..."]
GO_TREE_BUILD = ["go", "build", "-gcflags=-e", "-o", GO_TREE_BINARY, "."]
# Hidden case tiers, by file name prefix: adversarial cases are reported apart and do not decide the status.
ADVERSARIAL, REGRESSION, HYGIENE = "adv-", "reg-", "hyg-"
WRITE_LOCK = threading.Lock()
WORKSPACE = Path("/workspace")
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
ROOTFS_PATH = f"/workspace/bin:{SYSTEM_PATH}"
SAFE_ENV = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONUTF8": "1", "TMPDIR": "/tmp"}
DEFAULT_IMAGE = "agentica-eval:local"
# Pi locks auth.json in its own folder, so a read-only file there stops it: the container gets the file read-only at
# PI_AUTH_MOUNT and copies it into its HOME (a tmpfs that goes with the container) before Pi starts.
PI_AUTH_MOUNT = "/run/pi-auth.json"
PI_AUTH_COPY = (f'mkdir -p "$HOME/.pi/agent" && cp {PI_AUTH_MOUNT} "$HOME/.pi/agent/auth.json" '
                '&& chmod 600 "$HOME/.pi/agent/auth.json" && exec "$@"')
DEFAULT_ARMS = [arm for arm in ARMS if arm not in OPT_IN_ARMS]
# Prices in USD per million tokens (input, cache read, cache write, output): the opencode-go catalog of Pi 1.3.0
# (pi-ai/dist/providers/data/opencode-go.json), which matches https://opencode.ai/inference/go/v1/models on 2026-11-18.
# Used only when Pi reports no cost.
PRICES = {
    "opencode-go/deepseek-v4.1-flash": (0.15, 0.003, 0.0, 0.6),
    "opencode-go/deepseek-v4-pro": (0.66, 0.022, 0.0, 1.98),
    "opencode-go/glm-5.3-flash": (0.15, 0.03, 0.0, 0.5),
    "opencode-go/glm-5.3": (1.4, 0.26, 0.0, 4.4),
    "opencode-go/qwen3.8-flash": (0.15, 0.016, 0.2, 0.47),
    "opencode-go/kimi-k2.7-code": (0.95, 0.19, 0.0, 4.0),
}


def skill_dir() -> Path:
    return ROOT / ".agents" / "skills" / "agentica-programming"


def git(*command: str, cwd: Path) -> str:
    return subprocess.run(["git", *command], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fetch_sources(commit: str, paths: list[str] = SOURCE_PATHS, name: str = "agentica",
                  repo: str | None = None) -> Path:
    """A sparse, shallow checkout of `paths` of a commit of `repo` under .cache; git checks the commit hash."""
    target = CACHE / f"{name}-{commit[:12]}"
    try:
        if (target / ".git").is_dir() and git("rev-parse", "HEAD", cwd=target) == commit:
            return target
    except subprocess.CalledProcessError:
        pass  # a fetch that failed leaves a repository with no commit: clone again

    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    git("init", "-q", cwd=target)
    git("sparse-checkout", "set", *paths, cwd=target)
    git("fetch", "-q", "--depth", "1", "--filter=blob:none", repo or AGENTICA_REPO, commit, cwd=target)
    git("checkout", "-q", "--detach", "FETCH_HEAD", cwd=target)
    return target


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def release_binary() -> Path:
    """The agentica binary of the pinned release, downloaded once and checked against its SHA-256."""
    archive = CACHE / AGENTICA_ARCHIVE
    if not archive.is_file() or sha256_of(archive) != AGENTICA_ARCHIVE_SHA256:
        CACHE.mkdir(parents=True, exist_ok=True)
        url = f"{AGENTICA_REPO}/releases/download/{AGENTICA_VERSION}/{AGENTICA_ARCHIVE}"
        with tempfile.NamedTemporaryFile(dir=CACHE, prefix=f".{AGENTICA_ARCHIVE}.", delete=False) as handle:
            partial = Path(handle.name)
        try:
            with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as out:
                shutil.copyfileobj(response, out)
            if sha256_of(partial) != AGENTICA_ARCHIVE_SHA256:
                raise SystemExit(f"{url} does not match its pinned SHA-256")
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    binary = CACHE / f"agentica-{AGENTICA_VERSION}-{AGENTICA_ARCHIVE_SHA256[:12]}" / "agentica"
    if not binary.is_file():
        member = f"agentica-{AGENTICA_VERSION}-linux-x86_64/bin/agentica"
        with tarfile.open(archive) as bundle:
            source = bundle.extractfile(member)
            if source is None:
                raise SystemExit(f"{archive} has no {member}")
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(source.read())
    return binary


def install_runtime(binary: Path | None) -> None:
    """Put the agentica binary (the pinned release, or --agentica PATH) in RUNTIME/bin."""
    source = binary or release_binary()
    if not source.is_file():
        raise SystemExit(f"--agentica: no such file: {source}")
    shutil.rmtree(RUNTIME, ignore_errors=True)
    (RUNTIME / "bin").mkdir(parents=True)
    shutil.copyfile(source, RUNTIME / "bin" / "agentica")
    (RUNTIME / "bin" / "agentica").chmod(0o755)


def clone_rootfs(template: Path, destination: Path) -> Path:
    if not template.is_dir():
        raise SystemExit(f"chroot root filesystem not found: {template}")
    shutil.copytree(template, destination, symlinks=True)
    workspace = destination / "workspace"
    if workspace.is_symlink() or workspace.is_file():
        workspace.unlink()
    elif workspace.exists():
        shutil.rmtree(workspace)
    home = destination / "home"
    if home.is_symlink() or home.is_file():
        home.unlink()
    home.mkdir(exist_ok=True)
    agent_home = home / "agent"
    if agent_home.is_symlink() or agent_home.is_file():
        agent_home.unlink()
    elif agent_home.exists():
        shutil.rmtree(agent_home)
    return destination


# The Go language version of the image (`1.27`), set by ensure_go.
GO_LANGUAGE: str | None = None


def go_mod(ecosystem: bool = False) -> str:
    """The go.mod of a workspace: module `solution`, at the Go version of the image; an ecosystem task also requires
    the modules of ecosystem/go.mod."""
    if GO_LANGUAGE is None:
        raise SystemExit("the go arm needs the image's Go version: validate the image first")
    if ecosystem:
        return re.sub(r"(?m)^go \S+$", f"go {GO_LANGUAGE}", (ECOSYSTEM / "go.mod").read_text(encoding="utf-8"))
    return f"module solution\n\ngo {GO_LANGUAGE}\n"


def ecosystem_task(task: str) -> bool:
    """A task built on packages: Bond and agentica-db in Agentica, modernc.org/sqlite in Go (its start imports a
    package, or the task has an `ecosystem` file)."""
    start = TASKS / task / "start.agc"
    return (TASKS / task / "ecosystem").is_file() or (
        start.is_file() and 'from "pkg/' in start.read_text(encoding="utf-8"))


# The installed packages of ecosystem/agentica.lock, set by ecosystem_deps.
ECOSYSTEM_DEPS: Path | None = None


def ecosystem_deps() -> Path:
    """The `deps/` of ecosystem/agentica.lock, installed under .cache by the Agentica under test, which checks each
    package's commit and hash. `agentica install` runs every time (it is cheap when the packages are there), so a
    partial `deps/` is never used. The docs of agentica-db come along (`docs/` next to `deps/`)."""
    global ECOSYSTEM_DEPS
    binary = RUNTIME / "bin" / "agentica"
    lock = ECOSYSTEM / "agentica.lock"
    project = CACHE / f"ecosystem-{sha256_of(lock)[:12]}-{sha256_of(binary)[:12]}"
    project.mkdir(parents=True, exist_ok=True)
    for name in ("agentica.toml", "agentica.lock"):
        shutil.copyfile(ECOSYSTEM / name, project / name)
    done = subprocess.run([str(binary), "install"], cwd=project, capture_output=True, text=True)
    if done.returncode != 0:
        shutil.rmtree(project, ignore_errors=True)
        raise SystemExit(f"installing the ecosystem packages failed: {done.stderr.strip()[-500:]}")
    db = re.search(r'name = "db"\n(?:\w+ = .*\n)*?commit = "([0-9a-f]{40})"', lock.read_text(encoding="utf-8"))
    if db is None:
        raise SystemExit("ecosystem/agentica.lock has no commit for db")
    docs = fetch_sources(db[1], ["site/content"], "agentica-db-docs", "https://github.com/agentica-lang/agentica-db")
    shutil.rmtree(project / "docs", ignore_errors=True)
    shutil.copytree(docs / "site" / "content", project / "docs" / "agentica-db")
    ECOSYSTEM_DEPS = project / "deps"
    return ECOSYSTEM_DEPS


def project_files(work: Path, task: str, ext: str) -> None:
    """What a workspace needs besides the program: go.mod (and go.sum) for Go; for an ecosystem task in Agentica, the
    package manifest, its lock and the installed packages."""
    ecosystem = ecosystem_task(task)
    if ext == "go":
        (work / "go.mod").write_text(go_mod(ecosystem), encoding="utf-8")
        if ecosystem:
            shutil.copyfile(ECOSYSTEM / "go.sum", work / "go.sum")
    if ext == "agc" and ecosystem:
        if ECOSYSTEM_DEPS is None:
            raise SystemExit("the ecosystem packages are not installed: run ecosystem_deps first")
        for name in ("agentica.toml", "agentica.lock"):
            shutil.copyfile(ECOSYSTEM / name, work / name)
        shutil.copytree(ECOSYSTEM_DEPS, work / "deps")
        shutil.copytree(ECOSYSTEM_DEPS.parent / "docs", work / "docs", dirs_exist_ok=True)


def start_file(task: str, arm: str) -> Path:
    ext = ARMS[arm]
    typed = TASKS / task / f"start.typed.{ext}"
    if arm in TYPED_ARMS and typed.exists():
        return typed
    return TASKS / task / f"start.{ext}"


def tree_task(task: str) -> bool:
    """A task whose solution spans several files: its references are trees under reference/<ext>/, and its start,
    when it has one, is a tree under start/<ext>/ that the workspace starts from."""
    return (TASKS / task / "reference").is_dir()


def has_reference(task: str, ext: str) -> bool:
    return (TASKS / task / "reference" / ext).is_dir() if tree_task(task) else (TASKS / task / f"reference.{ext}").is_file()


def agent_timeout(task: str, default: int) -> int:
    """The agent's time limit: a task's agent_timeout file raises the --timeout of the round for that task."""
    limit = TASKS / task / "agent_timeout"
    return max(default, int(limit.read_text(encoding="utf-8").strip())) if limit.is_file() else default


def test_file(relative: Path) -> bool:
    """A test of the agent's own (test_*.py, *_test.py, *_test.go, *_test.agc, or under a tests/ folder): never
    graded, checked or scanned."""
    return TEST_FILE.search(relative.as_posix()) is not None


def solution_files(work: Path, ext: str) -> list[Path]:
    """The source files of a tree solution, relative to the workspace and solution.<ext> first: no links (nor files
    under a linked folder), nothing outside the workspace, in TREE_SKIP or hidden, and no test files."""
    found = []
    for path in sorted(work.rglob(f"*.{ext}")):
        relative = path.relative_to(work)
        if relative.parts[0] in TREE_SKIP or any(part.startswith(".") for part in relative.parts):
            continue
        linked = any((work / Path(*relative.parts[:depth])).is_symlink() for depth in range(1, len(relative.parts)))
        if linked or path.is_symlink() or not path.is_file() or test_file(relative):
            continue
        found.append(relative)
    entry = Path(f"solution.{ext}")
    return [entry, *(relative for relative in found if relative != entry)] if entry in found else found


def tree_problem(work: Path, files: list[Path]) -> str | None:
    """Why a tree solution is not graded: too many files, or one over TREE_FILE_LIMIT bytes; None when it is fine."""
    if len(files) > TREE_LIMIT:
        return "too-many-files"
    if any((work / relative).stat().st_size > TREE_FILE_LIMIT for relative in files):
        return "too-large"
    return None


def prepare(work: Path, task: str, arm: str) -> None:
    ext = ARMS[arm]
    work.mkdir(parents=True, exist_ok=True)
    start_tree = TASKS / task / "start" / ext
    if tree_task(task) and start_tree.is_dir():
        shutil.copytree(start_tree, work, dirs_exist_ok=True)
    shutil.copy(TASKS / task / "task.md", work / "task.md")
    go_note = TASKS / task / "task.go.md"
    if ext == "go" and go_note.is_file():
        # task.md is written for Agentica and Python; a task can add what is different in Go.
        with (work / "task.md").open("a", encoding="utf-8") as handle:
            handle.write("\n" + go_note.read_text(encoding="utf-8"))
    start = start_file(task, arm)
    if start.exists():
        shutil.copy(start, work / f"start.{ext}")
    if ext == "agc":
        shutil.copytree(RUNTIME, work, dirs_exist_ok=True)
    project_files(work, task, ext)
    if arm in SKILL_ARMS:
        (work / "skills").mkdir()
        shutil.copytree(skill_dir(), work / "skills" / "agentica-programming")
    if arm == "skill-nocli":
        strip_query_docs(work / "skills" / "agentica-programming")
        install_query_wrapper(work / "bin")
    if arm == "grammar":
        (work / "docs").mkdir()
        parts = sorted((ROOT / "docs" / "grammar").glob("*.md"))
        text = "\n".join(part.read_text(encoding="utf-8") for part in parts)
        # The grammar keeps the language rules and points to the library pages for every builtin, so the arm gets the
        # pages too, next to grammar.md; the other links out of the grammar lead nowhere in the work folder.
        text = re.sub(r"\]\((?:\.\./){2}site/content/library/", "](library/", text)
        text = re.sub(r"\[([^\]]*)\]\(\.\./[^)]*\)", r"\1", text)
        (work / "docs" / "grammar.md").write_text(text, encoding="utf-8")
        copy_library(ROOT / "site" / "content" / "library", work / "docs" / "library")
        shutil.copytree(ROOT / "examples", work / "examples")


# The link text may hold one level of brackets (`[`Optional[T]`](/library/...)`).
SITE_LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\(/([^)#\s]*?)/?(#[^)\s]*)?\)")


def copy_library(source: Path, target: Path) -> None:
    """Copy the library pages and turn their site links (`/library/list/#x`) into links between the copied files.

    A link to a page outside the library (the tour, the command line) has no copy, so it becomes plain text.
    """
    shutil.copytree(source, target)

    def relink(page: Path):
        def replace(found: re.Match) -> str:
            text, path, fragment = found.group(1), found.group(2), found.group(3) or ""
            inside = path.removeprefix("library").strip("/")
            for candidate in (f"{inside}.md", f"{inside}/_index.md" if inside else "_index.md"):
                if path.startswith("library") and (target / candidate).is_file():
                    return f"[{text}]({os.path.relpath(target / candidate, page.parent)}{fragment})"
            return text

        return replace

    for page in sorted(target.rglob("*.md")):
        page.write_text(SITE_LINK.sub(relink(page), page.read_text(encoding="utf-8")), encoding="utf-8")


def strip_query_docs(skill: Path) -> None:
    """Remove the query commands from the copy of the skill the agent gets (never from the repository's skill).

    Drops queries.md and analysis.md, the lines of SKILL.md that point to them, the QUERY- codes of
    diagnostics.md and the `type-at` cache note of language-running.md. It stops the run when a
    mention is left, so a skill edit cannot leak the commands unnoticed.
    """
    for name in ("queries.md", "analysis.md"):
        (skill / "references" / name).unlink()
    core = skill / "SKILL.md"
    text = core.read_text(encoding="utf-8")
    text = re.sub(r"^\| `(?:queries|analysis)\.md` \|.*\n", "", text, flags=re.MULTILINE)
    core.write_text(text, encoding="utf-8")
    codes = skill / "references" / "diagnostics.md"
    text = codes.read_text(encoding="utf-8")
    text = re.sub(r"^- `QUERY-.*\n(?:  .*\n)*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*`QUERY-` is a\s+bad\s+question\s+to.*?`refs`\.", "", text, flags=re.DOTALL)
    codes.write_text(text, encoding="utf-8")
    running = skill / "references" / "language-running.md"
    text = running.read_text(encoding="utf-8")
    text = text.replace("`check` and `type-at` keep", "`check` keeps").replace("rules and give the", "rules and gives the")
    running.write_text(text, encoding="utf-8")
    for path in sorted(skill.rglob("*.md")):
        found = QUERY_MENTION.search(path.read_text(encoding="utf-8"))
        if found:
            raise SystemExit(f"skill-nocli: {path.relative_to(skill)} still mentions the query commands ({found.group(0)!r}); "
                             "update strip_query_docs")


def install_query_wrapper(bin_dir: Path) -> None:
    """Put the refusing `agentica` in front of the real binary, which keeps its place under another name."""
    os.replace(bin_dir / "agentica", bin_dir / REAL_BINARY)
    wrapper = bin_dir / "agentica"
    wrapper.write_text(QUERY_WRAPPER, encoding="utf-8")
    wrapper.chmod(0o755)


def refused_queries(work: Path) -> int:
    log = work / "bin" / REFUSED_LOG
    return len(log.read_text(encoding="utf-8", errors="replace").splitlines()) if log.is_file() else 0


def tree_prompt(work: Path, arm: str) -> str:
    """The prompt of a tree task: the program is solution.<ext> and any other files of its language in the
    workspace, and what is not graded."""
    ext = ARMS[arm]
    graded = (f" Only the .{ext} files are graded, so the program needs no other file (no data files"
              f"{', no go:embed' if ext == 'go' else ', no .pyi' if ext == 'py' else ''}). Your own tests are not "
              f"graded: test_*.py, *_test.{ext} and anything under a tests/ folder. The folders "
              f"{', '.join(sorted(TREE_SKIP))} and hidden folders are reserved: no program files there.")
    return tree_layout(work, arm) + graded


def tree_layout(work: Path, arm: str) -> str:
    ext = ARMS[arm]
    if ext == "agc":
        text = ("The program starts at solution.agc and may import other .agc files of this directory and its "
                "subfolders. Run programs with the `agentica` command, which is on your PATH.")
        if (work / "agentica.lock").exists():
            text += (f" The packages in deps/ are documented in docs/agentica-db/ (agentica-db) and at {BOND_DOCS} "
                     "(Bond).")
        return text + (" Use the agentica-programming skill." if arm in SKILL_ARMS else "")
    if ext == "go":
        modules = ("the standard library and modernc.org/sqlite (a database/sql driver named \"sqlite\"), which go.mod "
                   "and go.sum already require" if (work / "go.sum").exists() else "the standard library only")
        return (f"The program is a Go module named `solution` (go.mod is ready) with {modules}: package "
                "main is solution.go and any other .go files of this directory; other packages go in subfolders, "
                "imported as `solution/<folder>`. The checkers are `go vet ./...` and `go build .`, on your PATH: the "
                "solution must pass both, so do not silence them.")
    text = ("The program is a Python 3 program that starts at solution.py and may import other .py files of this "
            "directory and its packages (a subfolder with __init__.py). Run programs with `python3`.")
    if arm in TYPED_ARMS:
        text += (" Type annotations go on every function. The type checker is `mypy --strict "
                 "--explicit-package-bases solution.py`, on your PATH; the grader runs it on every graded .py file: "
                 "the solution must pass it, so do not silence it with `# type: ignore` or by weakening its options.")
    return text


def prompt(work: Path, arm: str, tree: bool = False) -> str:
    ext = ARMS[arm]
    lines = ["Read task.md in the current directory and do what it asks."]
    if (work / f"start.{ext}").exists():
        lines.append(f"The starting program is start.{ext}.")
    if tree:
        lines.append(tree_prompt(work, arm))
        lines.append("Work only inside the current directory. Test your program before you finish, then reply with "
                     "one sentence.")
        return " ".join(lines)
    if ext == "agc":
        lines.append("Write a complete Agentica program to solution.agc. Run programs with the `agentica` command, which is on your PATH.")
        if arm in SKILL_ARMS:
            lines.append("Use the agentica-programming skill.")
        elif arm == "binary":
            lines.append("The language is Agentica: Ruby-like syntax, statically typed, programs start with `def main() -> Void`. "
                         "`agentica file.agc` runs a program and `agentica check file.agc` checks it without running. "
                         "`agentica --help` lists the options.")
        else:
            lines.append("The language is described in docs/grammar.md, the builtin library in docs/library/, "
                         "and example programs are in examples/. Use `agentica help NAME` for builtin signatures.")
        if (work / "agentica.lock").exists():
            lines.append(f"The packages in deps/ are documented in docs/agentica-db/ (agentica-db) and at {BOND_DOCS} "
                         "(Bond).")
    elif arm in TYPED_ARMS:
        lines.append("Write a complete Python 3 program to solution.py, with type annotations on every function. "
                     "Run programs with `python3`. The type checker is `mypy --strict solution.py`, on your PATH: "
                     "the solution must pass it, so do not silence it with `# type: ignore` or by weakening its options.")
    elif ext == "go":
        modules = ("the standard library and modernc.org/sqlite (a database/sql driver named \"sqlite\"), which "
                   "go.mod and go.sum already require" if (work / "go.sum").exists() else "the standard library only")
        lines.append(f"Write a complete Go program to solution.go, in package main, with {modules}; "
                     "go.mod is ready. Run programs with `go run solution.go`. The checkers are "
                     "`go vet solution.go` and `go build solution.go`, on your PATH: the solution must pass both, "
                     "so do not silence them. Where the task names `sys.argv` or Python's HTTP modules, use "
                     "`os.Args` and `net/http`. Keep the whole program in solution.go; start.go, if there is one, "
                     "has `//go:build ignore`, which does not matter for your file.")
    else:
        lines.append("Write a complete Python 3 program to solution.py. Run programs with `python3`.")
    lines.append("Work only inside the current directory. Test your program before you finish, then reply with one sentence.")
    return " ".join(lines)


def agent_command(agent: str, work: Path, arm: str, model: str | None, *, in_chroot: bool,
                  text: str | None = None) -> list[str]:
    text = text or prompt(work, arm)
    workspace = WORKSPACE if in_chroot else work
    if agent == "pi":
        cmd = ["pi", "-p", "--mode", "json", "--no-session", "--no-context-files", "--no-extensions"]
        cmd += ["--skill", str(workspace / "skills" / "agentica-programming")] if arm in SKILL_ARMS else ["--no-skills"]
        if model:
            cmd += ["--model", model]
        return cmd + [text]
    if agent == "claude":
        cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence", "--dangerously-skip-permissions", "--strict-mcp-config"]
        if arm not in SKILL_ARMS:
            cmd += ["--disable-slash-commands"]
        else:
            target = work / ".claude" / "skills"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(work / "skills" / "agentica-programming", target / "agentica-programming")
        if model:
            cmd += ["--model", model]
        return cmd + [text]
    raise SystemExit(f"unknown agent {agent}")


def jail_prefix(rootfs: Path, *, network: bool) -> list[str]:
    command = [
        shutil.which("firejail") or "firejail",
        "--quiet",
        "--noprofile",
        f"--chroot={rootfs}",
        "--private-tmp",
        "--nonewprivs",
        "--caps.drop=all",
        "--seccomp",
    ]
    if not network:
        command.append("--net=none")
    return command


def docker_prefix(work: Path, image: str, name: str, *, network: bool, pass_env: list[str],
                  pi_auth: Path | None = None, writable: bool | None = None) -> list[str]:
    """`writable` is whether the workspace mount is writable; it follows `network` unless given (the Go build of the
    grader writes its binary there without a network)."""
    uid, gid = os.getuid(), os.getgid()
    command = [
        shutil.which("docker") or "docker", "run", "--rm", "--interactive",
        "--name", name, "--user", f"{uid}:{gid}",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=256", "--memory=2g", "--cpus=2",
        "--tmpfs", "/tmp:rw,nosuid,nodev,exec,size=256m",
        "--tmpfs", f"/home/agent:rw,nosuid,nodev,uid={uid},gid={gid},size=128m",
        "--mount", f"type=bind,src={work},dst=/workspace" + ("" if (network if writable is None else writable) else ",readonly"),
        "--workdir", "/workspace",
    ]
    if pi_auth is not None:
        command += ["--mount", f"type=bind,src={pi_auth},dst={PI_AUTH_MOUNT},readonly"]
    if not network:
        command.append("--network=none")
    for key in [*grader_environment(), *pass_env]:
        command += ["--env", key]
    return command + [image]


def remove_container(name: str) -> None:
    subprocess.run([shutil.which("docker") or "docker", "rm", "--force", name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


def build_image(image: str) -> None:
    try:
        subprocess.run(["docker", "build", "--tag", image, "--file", str(EVAL / "Dockerfile"), str(EVAL)], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Building the Docker image {image} failed ({exc}); check that the Docker daemon is running") from exc


def require_docker() -> None:
    if not shutil.which("docker"):
        raise SystemExit("docker is required for evaluation; alternatively select --sandbox firejail")


def image_exists(image: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0


def image_id(image: str) -> str | None:
    done = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def probe(image: str, command: list[str], work: Path, timeout: int) -> tuple[int | None, str, str]:
    name = f"agentica-probe-{uuid.uuid4().hex}"
    try:
        done = subprocess.run(docker_prefix(work, image, name, network=False, pass_env=[]) + command,
                              env=grader_environment(), capture_output=True, text=True, errors="replace",
                              timeout=timeout)
        return done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired:
        return None, "", "timeout"
    finally:
        remove_container(name)


def python_runs(image: str) -> str | None:
    with tempfile.TemporaryDirectory(prefix="agentica-docker-probe-") as directory:
        code, _, err = probe(image, ["python3", "-I", "-c", "pass"], Path(directory), 30)
    return None if code == 0 else err


def checker_probe(image: str) -> tuple[int | None, str, str]:
    with tempfile.TemporaryDirectory(prefix="agentica-checker-probe-") as directory:
        return probe(image, [CHECKER[0], "--version"], Path(directory), 60)


def checker_version(image: str) -> str | None:
    code, out, _ = checker_probe(image)
    return out.strip() if code == 0 else None


def runtime_probe(image: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="agentica-runtime-probe-") as directory:
        work = Path(directory)
        shutil.copytree(RUNTIME, work, dirs_exist_ok=True)
        (work / "hello.agc").write_text('def main() -> Void\n  puts("hello")\nend\n', encoding="utf-8")
        code, out, err = probe(image, [str(WORKSPACE / "bin" / "agentica"), "hello.agc"], work, 60)
    return code == 0 and out.strip() == "hello", err.strip() or out.strip()


def go_probe(image: str) -> tuple[int | None, str, str]:
    with tempfile.TemporaryDirectory(prefix="agentica-go-probe-") as directory:
        return probe(image, ["go", "env", "GOVERSION"], Path(directory), 60)


def ensure_tool(image: str, run_probe: Callable[[str], tuple[int | None, str, str]], command: str, arm: str) -> str:
    """The version line of a tool the arm needs. The default image is rebuilt once when the tool is missing (exit 126
    or 127); any other failure, or a missing tool in an image given with --image, stops the run."""
    code, out, err = run_probe(image)
    if code in MISSING_COMMAND and image == DEFAULT_IMAGE:
        print(f"{command.split()[0]} is missing from {image} (exit {code}): rebuilding the image from Dockerfile", flush=True)
        build_image(image)
        code, out, err = run_probe(image)
    if code != 0:
        reason = "it timed out" if code is None else f"it exited {code}: {err.strip()}"
        hint = " Rebuild the image from Dockerfile." if code in MISSING_COMMAND else ""
        raise SystemExit(f"{command} failed in the Docker image {image} ({reason}); the {arm} arm needs it.{hint}")
    return out.strip()


def ensure_checker(image: str) -> str:
    return ensure_tool(image, lambda name: checker_probe(name), f"{CHECKER[0]} --version", "typed-python")


def ensure_go(image: str) -> str:
    global GO_LANGUAGE
    version = ensure_tool(image, lambda name: go_probe(name), "go env GOVERSION", "go")
    found = re.match(r"go(\d+\.\d+)", version)
    if found is None:
        raise SystemExit(f"go env GOVERSION in {image} printed {version!r}, not a release version")
    GO_LANGUAGE = found.group(1)
    return version


def ensure_runtime(image: str) -> None:
    works, details = runtime_probe(image)
    if not works and image == DEFAULT_IMAGE:
        print(f"{image} cannot run the agentica binary ({details}): rebuilding the image from Dockerfile", flush=True)
        build_image(image)
        works, details = runtime_probe(image)
    if not works:
        raise SystemExit(f"The Docker image {image} cannot run the agentica binary ({details}). "
                         "Rebuild it from Dockerfile (docker build --tag IMAGE .); "
                         "if it still fails, the VM needs a newer libc or other libraries than the image has.")


def dockerfile_pi_version() -> str | None:
    found = re.search(r"^ARG PI_VERSION=(\S+)", (EVAL / "Dockerfile").read_text(encoding="utf-8"), re.MULTILINE)
    return found.group(1) if found else None


def ensure_pi(image: str) -> str | None:
    """The Pi version of the image. The default image must match the Dockerfile, so an image built before a bump of
    PI_VERSION stops the round; an image given with --image is only recorded."""
    with tempfile.TemporaryDirectory(prefix="agentica-pi-probe-") as directory:
        code, out, err = probe(image, ["pi", "--version"], Path(directory), 60)
    found = re.search(r"\d+\.\d+\.\d+\S*", out + err) if code == 0 else None
    version = found.group(0) if found else None
    wanted = dockerfile_pi_version()
    if image == DEFAULT_IMAGE and version != wanted:
        raise SystemExit(f"{image} has Pi {version or 'that does not run (' + err.strip() + ')'}, but Dockerfile "
                         f"pins {wanted}. Remove the stale image (docker rmi {image}) and rerun to rebuild it.")
    return version


def validate_docker(image: str, typed: bool = False, agentica: bool = False,
                    pi: bool = False, go: bool = False) -> dict[str, str | None]:
    require_docker()
    if not image_exists(image):
        if image != DEFAULT_IMAGE:
            raise SystemExit(f"Docker image not found: {image}")
        build_image(image)
    problem = python_runs(image)
    if problem is not None:
        raise SystemExit(f"Docker preflight failed: {problem}")
    checker = ensure_checker(image) if typed else None
    if agentica:
        ensure_runtime(image)
    return {"checker": checker, "go": ensure_go(image) if go else None, "image_id": image_id(image),
            "pi": ensure_pi(image) if pi else None}


def child_environment(pass_env: list[str], *, in_chroot: bool, workspace: Path) -> dict[str, str]:
    env = dict(SAFE_ENV)
    env["HOME"] = "/home/agent" if in_chroot else str(workspace.parent / "home" / "agent")
    env["PATH"] = ROOTFS_PATH if in_chroot else f"{workspace / 'bin'}:{os.environ['PATH']}"
    for name in pass_env:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise SystemExit(f"invalid environment variable name: {name}")
        if name in {"HOME", "PATH", *SAFE_ENV}:
            raise SystemExit(f"cannot pass reserved environment variable: {name}")
        if name not in os.environ:
            raise SystemExit(f"environment variable is not set: {name}")
        env[name] = os.environ[name]
    return env


def secret_forms(pass_env: list[str], secrets: list[str] | None = None) -> list[str]:
    """Each secret as it is and JSON-escaped, longest first."""
    values = [*(os.environ[name] for name in pass_env), *(secrets or [])]
    return sorted({form for value in values if value for form in (value, json.dumps(value)[1:-1])}, key=len, reverse=True)


def redact_secrets(output: str, pass_env: list[str], secrets: list[str] | None = None) -> str:
    for form in secret_forms(pass_env, secrets):
        output = output.replace(form, "[REDACTED]")
    return output


def agent_log(output: str, pass_env: list[str], secrets: list[str]) -> str:
    """The stream to keep, redacted. Pi's `message_update` and `tool_execution_update` events carry deltas, which can
    split a secret over events where no replace finds it; they go, and `message_end` and `tool_execution_end` keep
    the whole text."""
    kept = []
    for line in output.splitlines(keepends=True):
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = None
            if isinstance(event, dict) and event.get("type") in DROPPED_EVENTS:
                continue
        kept.append(line)
    return redact_secrets("".join(kept), pass_env, secrets)


def redact_file(path: Path, pass_env: list[str], secrets: list[str]) -> None:
    data = path.read_bytes()
    for form in secret_forms(pass_env, secrets):
        data = data.replace(form.encode("utf-8"), b"[REDACTED]")
    path.write_bytes(data)


def auth_secrets(path: Path | None) -> list[str]:
    """Every string of a Pi auth.json of 8 characters or more, except the credential types, to redact; nothing of it
    is ever printed."""
    if path is None:
        return []
    found: list[str] = []

    def walk(value: object, key: str = "") -> None:
        if isinstance(value, dict):
            for name, item in value.items():
                walk(item, name)
        elif isinstance(value, list):
            for item in value:
                walk(item, key)
        elif isinstance(value, str) and key != "type" and len(value) >= 8:
            found.append(value)

    try:
        walk(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"--pi-auth: cannot read {path} as JSON ({type(exc).__name__})") from None
    return found


def grader_environment() -> dict[str, str]:
    return dict(SAFE_ENV, HOME="/home/agent", PATH=ROOTFS_PATH)


def rootfs_has_executable(rootfs: Path, name: str) -> bool:
    for directory in SYSTEM_PATH.split(":"):
        candidate = rootfs / directory.lstrip("/") / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return True
    return False


def validate_sandbox(rootfs: Path, agent: str, typed: bool = False) -> None:
    if not rootfs.is_dir():
        raise SystemExit(f"chroot root filesystem not found: {rootfs}")
    if not shutil.which("firejail"):
        raise SystemExit("firejail not found; it is required to isolate grading")
    version = subprocess.run(["firejail", "--version"], capture_output=True, text=True, check=True).stdout
    if "chroot support is enabled" not in version:
        raise SystemExit("installed firejail does not support --chroot")
    if "networking support is enabled" not in version:
        raise SystemExit("installed firejail does not support network namespaces")
    if agent != "reference" and not rootfs_has_executable(rootfs, agent):
        raise SystemExit(f"{agent} executable not found in chroot system PATH ({SYSTEM_PATH})")
    if not rootfs_has_executable(rootfs, "python3"):
        raise SystemExit(f"python3 executable not found in chroot system PATH ({SYSTEM_PATH})")
    if typed and not rootfs_has_executable(rootfs, CHECKER[0]):
        raise SystemExit(f"{CHECKER[0]} executable not found in chroot system PATH ({SYSTEM_PATH})")
    smoke = jail_prefix(rootfs, network=False) + ["python3", "-I", "-c", "pass"]
    try:
        result = subprocess.run(
            smoke,
            cwd=rootfs,
            env=dict(SAFE_ENV, HOME="/", PATH=ROOTFS_PATH),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"Firejail chroot preflight failed: {exc}") from exc
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(f"Firejail chroot preflight failed: {details}")


def copy_candidate(source: Path, destination: Path) -> bool:
    if source.is_symlink() or not source.is_file():
        return False
    shutil.copyfile(source, destination)
    return True


def run_agent(
    agent: str,
    work: Path,
    rootfs: Path,
    task: str,
    arm: str,
    model: str | None,
    timeout: int,
    sandbox: str,
    pass_env: list[str],
    image: str,
    pi_auth: Path | None = None,
    text: str | None = None,
) -> tuple[str, str, bool, int | None]:
    """The agent's redacted stdout and stderr, whether it timed out, and its exit status."""
    ext = ARMS[arm]
    if agent == "reference":
        if tree_task(task):
            shutil.copytree(TASKS / task / "reference" / ext, work, dirs_exist_ok=True)
        else:
            shutil.copy(TASKS / task / f"reference.{ext}", work / f"solution.{ext}")
        return "", "", False, 0
    text = text or prompt(work, arm, tree_task(task))
    env = child_environment(pass_env, in_chroot=True, workspace=work)
    command = agent_command(agent, work, arm, model, in_chroot=True, text=text)
    container = f"agentica-agent-{uuid.uuid4().hex}"
    secrets = auth_secrets(pi_auth)
    if sandbox == "docker":
        if pi_auth is not None:
            command = ["sh", "-c", PI_AUTH_COPY, "sh", *command]
        command = docker_prefix(work, image, container, network=AGENT_NETWORK, pass_env=pass_env,
                                pi_auth=pi_auth) + command
    else:
        command = jail_prefix(rootfs, network=AGENT_NETWORK) + command
    proc = subprocess.Popen(command, cwd=work, env=env, text=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
        return agent_log(out, pass_env, secrets), redact_secrets(err, pass_env, secrets), False, proc.returncode
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
        return agent_log(out or "", pass_env, secrets), redact_secrets(err or "", pass_env, secrets), True, None
    finally:
        if sandbox == "docker":
            remove_container(container)


def command_parts(command: str, *, split_pipes: bool = True) -> list[str]:
    """split_shell, and the script of a `bash -c` or `sh -c` is split in its place."""
    parts: list[str] = []
    for part in split_shell(command, split_pipes=split_pipes):
        script = SHELL_SCRIPT.match(part)
        if script is None:
            parts.append(part)
        else:
            inner = script[1] if script[1] is not None else re.sub(r"\\(.)", r"\1", script[2])
            parts += command_parts(inner, split_pipes=split_pipes)
    return parts


def split_shell(command: str, *, split_pipes: bool = True) -> list[str]:
    """Split a shell line into its commands. With split_pipes=False a pipeline stays whole, so a `| head` filter
    is not read as a command of its own."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < len(command):
                current.append(command[index:index + 2])
                index += 2
                continue
            if char == quote:
                quote = ""
            current.append(char)
        elif char in "'\"":
            quote = char
            current.append(char)
        elif command.startswith(("&&", "||"), index):
            parts.append("".join(current))
            current = []
            index += 2
            continue
        elif char == "|" and not split_pipes:
            current.append(char)
        elif char in ";|\n":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def is_check_command(command: str) -> bool:
    return any(CHECK_COMMAND.match(part) for part in command_parts(command))


def is_query_command(command: str) -> bool:
    return any(QUERY_COMMAND.match(part) for part in command_parts(command))


def is_read_command(command: str) -> bool:
    return any(READ_COMMAND.match(part) for part in command_parts(command, split_pipes=False))


def runs_mypy(command: str) -> bool:
    return any(MYPY_COMMAND.match(part) for part in command_parts(command))


def is_net_command(command: str) -> bool:
    return any(NET_STRONG.search(part) or (NET_WEAK.search(part) and not LOOPBACK.search(part))
               for part in command_parts(command))


def runs_go(command: str) -> bool:
    return any(GO_COMMAND.match(part) for part in command_parts(command))


def runs_program(command: str) -> bool:
    """A check or run call: the interpreter, Python, a checker or the Go tool."""
    return any(RUN_COMMAND.match(part) for part in command_parts(command))


def graded_source(path: str, tree: bool) -> bool:
    """A file of the solution: solution.<ext>, or in a tree task any .agc, .py or .go file but a test file."""
    name = Path(path)
    if not tree:
        return name.name.startswith("solution.")
    return name.suffix in (".agc", ".py", ".go") and not test_file(Path(path.lstrip("./")))


def edits_solution(call: "Call", tree: bool = False) -> bool:
    path = str(call.args.get("path") or call.args.get("file_path") or "")
    return call.tool in EDIT_TOOLS and not call.failed and graded_source(path, tree)


def writes_solution(command: str, tree: bool = False) -> bool:
    """A shell command that writes the solution in a common form (see SHELL_EDIT); in a tree task, any source file
    but a test file."""
    if not tree:
        return any(SHELL_EDIT.search(part) for part in command_parts(command))
    for part in command_parts(command):
        for found in TREE_EDIT.finditer(part):
            writes = not found.group("how").startswith("open") or found.group("mode") is not None
            if writes and graded_source(found.group("path"), True):
                return True
    return False


def built_binaries(command: str) -> set[str]:
    """The programs a `go build` in the command writes: the `-o` path, or the name of the first .go file."""
    names: set[str] = set()
    for part in command_parts(command):
        build = BUILD_COMMAND.match(part)
        if build is None:
            continue
        words = build["args"].split()
        if "-o" in words[:-1]:
            names.add(words[words.index("-o") + 1])
        else:
            names.update(word.removesuffix(".go") for word in words if word.endswith(".go"))
    return {Path(name).name for name in names}


def runs_binary(command: str, binaries: set[str]) -> bool:
    """A call of a program a `go build` made, through a path (`./solution`, `/tmp/s`)."""
    return any(match and Path(match[1]).name in binaries
               for match in (re.match(COMMAND_PREFIX + r"(\S*/\S+)(?=\s|$)", part) for part in command_parts(command)))


def command_failed(command: str, text: str, binary: bool = False) -> bool:
    if "error[" in text or "Traceback" in text or "SyntaxError" in text:
        return True
    if (binary or runs_go(command)) and GO_ERROR.search(text):
        return True
    return runs_mypy(command) and ": error:" in text


@dataclass
class Call:
    """One tool call of the agent, with the text of its result."""

    tool: str
    args: dict
    output: str = ""
    failed: bool = False


def call_metrics(calls: list[Call], tree: bool = False) -> dict[str, int]:
    """The counters of a run from its tool calls, in order.

    A fix round is a failed check or run call followed by an edit (an edit tool, or a shell command that writes the
    solution) before the next check or run call. Failures that are never edited, or that another check follows
    first, are not rounds.

    A `go vet` and a `go build` in calls next to each other, in either order (no edit or other run between), are
    one check: one interpreter run, one check run, and one failure at most."""
    m = {"interpreter_runs": 0, "failing_runs": 0, "check_runs": 0, "check_failures": 0, "fix_rounds": 0,
         "outside_reads": 0, "net_commands": 0, "query_runs": 0, "read_runs": 0, "spec_runs": 0}
    awaiting_fix = False
    binaries: set[str] = set()
    open_half: tuple[str, bool] | None = None  # the `vet` or `build` call waiting for its other half, and its result
    for call in calls:
        if str(EVAL) in json.dumps(call.args):
            m["outside_reads"] += 1
        command = call.args.get("command", "") if call.tool == "bash" else ""
        m["net_commands"] += is_net_command(command)
        if call.tool == "read":
            m["read_runs"] += 1
        elif edits_solution(call, tree) or writes_solution(command, tree):
            m["fix_rounds"] += awaiting_fix
            awaiting_fix = False
            open_half = None
        if not command:
            continue
        m["query_runs"] += is_query_command(command)
        m["spec_runs"] += any(SPEC_COMMAND.match(part) for part in command_parts(command))
        m["read_runs"] += is_read_command(command)
        binary = runs_binary(command, binaries)
        if runs_program(command) or binary:
            check = is_check_command(command)
            failed = command_failed(command, call.output, binary)
            vetted = any(VET_COMMAND.match(part) for part in command_parts(command))
            built = any(BUILD_COMMAND.match(part) for part in command_parts(command))
            half = "vet" if vetted and not built else "build" if built and not vetted else None
            first_failed = open_half is not None and open_half[1]
            merged = half is not None and open_half is not None and open_half[0] != half
            ran_failed = failed
            if merged:
                check = False
                m["check_failures"] += failed and not first_failed
                failed = failed and not first_failed
            m["interpreter_runs"] += not merged
            m["check_runs"] += check
            m["failing_runs"] += failed
            m["check_failures"] += failed and check
            awaiting_fix = failed or (merged and first_failed and awaiting_fix)
            open_half = (half, ran_failed) if half is not None and not merged else None
            binaries |= built_binaries(command)
    return m


def pi_metrics(out: str, tree: bool = False) -> dict[str, int | float]:
    """Counters from Pi's JSON stream: usage from the `message_end` events of the assistant, calls from the
    `tool_execution_start` and `_end` events.

    `tokens_in` is the uncached input only, `tokens_cached` the cache reads: the context an agent read is
    `tokens_in + tokens_cached + tokens_cache_write`. The cost is split in the same way as the usage events do:
    `cost_input`, `cost_cache` (reads and writes) and `cost_output`."""
    m: dict[str, int | float] = {"tokens_in": 0, "tokens_out": 0, "tokens_cached": 0, "tokens_cache_write": 0,
                                 "cost": 0.0, "cost_input": 0.0, "cost_cache": 0.0, "cost_output": 0.0, "turns": 0}
    calls: list[Call] = []
    # Pi can repeat a call id or leave it empty, so an id maps to the calls still open under it, oldest first.
    open_calls: dict[str, list[int]] = {}
    for event in json_events(out):
        kind = event.get("type")
        if kind == "message_end" and event.get("message", {}).get("role") == "assistant":
            usage = event["message"].get("usage", {})
            m["turns"] += 1
            m["tokens_in"] += usage.get("input", 0)
            m["tokens_out"] += usage.get("output", 0)
            m["tokens_cached"] += usage.get("cacheRead", 0)
            usage_cost = usage.get("cost", {})
            m["tokens_cache_write"] += usage.get("cacheWrite", 0)
            m["cost"] += usage_cost.get("total", 0.0)
            m["cost_input"] += usage_cost.get("input", 0.0)
            m["cost_cache"] += usage_cost.get("cacheRead", 0.0) + usage_cost.get("cacheWrite", 0.0)
            m["cost_output"] += usage_cost.get("output", 0.0)
        elif kind == "tool_execution_start":
            open_calls.setdefault(str(event.get("toolCallId", "")), []).append(len(calls))
            calls.append(Call(event.get("toolName", ""), event.get("args", {})))
        elif kind == "tool_execution_end" and open_calls.get(str(event.get("toolCallId", ""))):
            call = calls[open_calls[str(event.get("toolCallId", ""))].pop(0)]
            call.output = result_text(event.get("result", {}))
            call.failed = bool(event.get("isError"))
    return {**m, **call_metrics(calls, tree)}


def result_text(result: object) -> str:
    """The text of a Pi tool result, so line-anchored patterns (Go's `file.go:N:M:`) can match."""
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return json.dumps(result)


def json_events(out: str) -> list[dict]:
    events = []
    for line in out.splitlines():
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def spend(row: dict) -> dict[str, float | str]:
    """The cost of a run and where it comes from: the agent's figure when it reports one above 0, else the token
    counts at the list prices of PRICES, else none (0)."""
    if row.get("cost", 0) > 0:
        return {"cost_source": "agent"}
    prices = PRICES.get(row.get("model", ""))
    if prices is None or not any(row.get(key) for key in ("tokens_in", "tokens_out", "tokens_cached")):
        return {"cost": 0.0, "cost_source": "none"}
    price_in, price_read, price_write, price_out = (price / 1_000_000 for price in prices)
    split = {"cost_input": row.get("tokens_in", 0) * price_in,
             "cost_cache": row.get("tokens_cached", 0) * price_read + row.get("tokens_cache_write", 0) * price_write,
             "cost_output": row.get("tokens_out", 0) * price_out}
    return {**split, "cost": sum(split.values()), "cost_source": "table"}


def claude_metrics(out: str) -> dict[str, int | float]:
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {}
    usage = data.get("usage", {})
    return {"tokens_in": usage.get("input_tokens", 0), "tokens_out": usage.get("output_tokens", 0),
            "tokens_cached": usage.get("cache_read_input_tokens", 0),
            "tokens_cache_write": usage.get("cache_creation_input_tokens", 0), "cost": data.get("total_cost_usd", 0.0),
            "turns": data.get("num_turns", 0), "check_runs": 0, "check_failures": 0,
            "query_runs": 0, "read_runs": 0}


def hidden_driver(task: str) -> str | None:
    driver = TASKS / task / "hidden" / "driver.py"
    return driver.read_text(encoding="utf-8") if driver.is_file() else None


def case_timeout(task: str) -> int:
    limit = TASKS / task / "hidden" / "timeout"
    return int(limit.read_text(encoding="utf-8").strip()) if limit.is_file() else CASE_TIMEOUT


def case_invocation(ext: str, driver: str | None, case: str, tree: bool = False) -> tuple[list[str], str]:
    """The command of one hidden case. A tree solution in Python imports its own modules, so it runs with the script's
    folder on sys.path (-s -E, not -I)."""
    if ext == "go":
        binary = f"/workspace/{GO_TREE_BINARY if tree else 'solution'}"
        return ([binary], case) if driver is None else (["python3", "-I", "-", case, binary], driver)
    if ext == "agc":
        command = ["/workspace/bin/agentica", "solution.agc"]
    else:
        command = ["python3", "-s", "-E", "solution.py"] if tree else ["python3", "-I", "solution.py"]
    if driver is None:
        return command, case
    return ["python3", "-I", "-", case, command[0], *command[1:-1], f"/workspace/{command[-1]}"], driver


def contained_run(args: argparse.Namespace, grade_root: Path, work: Path, command: list[str],
                  stdin: str, timeout: int, writable: bool = False) -> tuple[str | None, str, int | None]:
    container = f"agentica-grade-{uuid.uuid4().hex}"
    try:
        prefix = (docker_prefix(work, args.image, container, network=False, pass_env=[], writable=writable)
                  if args.sandbox == "docker" else jail_prefix(grade_root, network=False))
        done = subprocess.run(prefix + command, cwd=work, env=grader_environment(), input=stdin,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return done.stdout, done.stderr, done.returncode
    except subprocess.TimeoutExpired:
        return None, "timeout", None
    finally:
        if args.sandbox == "docker":
            remove_container(container)


def classify_check(output: str) -> tuple[str, str]:
    found = re.search(r"^.*: error: .*?(?:\s+\[([a-z0-9-]+)\])?$", output, re.MULTILINE)
    code = found.group(1) if found and found.group(1) else "mypy"
    if code == "syntax":
        return "syntax", "SyntaxError"
    return "check", code


Contained = Callable[[list[str], str, int], tuple[str | None, str, int | None]]


def type_escapes(text: str) -> dict[str, int]:
    return {"type_ignores": len(TYPE_SILENCE.findall(text)), "type_escapes": len(TYPE_ESCAPE.findall(text))}


def type_check(contained: Contained, total: int, files: list[str] | None = None) -> dict | None:
    """mypy on solution.py, or on every file of a tree solution (with the workspace as the base of its packages)."""
    command = CHECKER + (["--explicit-package-bases", "--", *files] if files else ["solution.py"])
    out, err, returncode = contained(command, "", CHECK_TIMEOUT)
    if returncode == 0:
        return None
    if out is None:
        return {"status": "fail", "passed": 0, "total": total, "failure": "check-timeout", "code": None, "check_errors": 0}
    kind, code = classify_check(out + err)
    return {"status": "fail", "passed": 0, "total": total, "failure": kind, "code": code,
            "check_errors": len(re.findall(r": error: ", out))}


def go_failure(step: str, text: str, total: int) -> dict:
    kind, code = ("syntax", "syntax") if "syntax error" in text else ("check", step)
    return {"status": "fail", "passed": 0, "total": total, "failure": kind, "code": code,
            "check_errors": len(GO_FILE_ERROR.findall(text))}


def go_check(contained: Contained, built: Contained, total: int, tree: bool = False) -> dict | None:
    """`go vet`, then `go build` into the workspace; None when both pass, else the failing row.

    `go vet` type-checks first and stops at the first type or syntax error (its `vet: ` line); then the class and
    the count come from `go build -gcflags=-e`, which lists them all. A vet failure records `build_ok`, so a
    failure of vet's other analyses alone (the build passes) shows."""
    out, err, returncode = contained(GO_TREE_VET if tree else GO_VET, "", CHECK_TIMEOUT)
    if out is None:
        return {"status": "fail", "passed": 0, "total": total, "failure": "check-timeout", "code": "vet",
                "check_errors": 0}
    vet_text = out + err if returncode != 0 else ""
    build_out, build_err, build_code = built(GO_TREE_BUILD if tree else GO_BUILD, "", CHECK_TIMEOUT)
    if build_out is None:
        return {"status": "fail", "passed": 0, "total": total, "failure": "check-timeout", "code": "build",
                "check_errors": 0}
    if returncode == 0:
        return None if build_code == 0 else go_failure("build", build_out + build_err, total)
    typed = re.search(r"^vet: ", vet_text, re.MULTILINE) and build_code != 0
    return {**go_failure("vet", build_out + build_err if typed else vet_text, total), "build_ok": build_code == 0}


def case_tier(case: Path) -> str:
    for tier in (ADVERSARIAL, REGRESSION, HYGIENE):
        if case.name.startswith(tier):
            return tier
    return ""


def grade(solution: Path, task: str, arm: str, args: argparse.Namespace, scratch: Path, name: str) -> dict:
    """The outcome of a solution on the hidden cases. `solution` is solution.<ext>; for a tree task, every file of its
    language in that workspace goes along (solution_files).

    The status and `passed`/`total` cover every case but the adversarial ones (`adv-*`), which count apart
    (`adversarial_passed` of `adversarial_total`). `regressions` and `hygiene_failed` count the failed `reg-*` and
    `hyg-*` cases, and `crash_cases` the crashed cases of any tier (crashed).

    A tree solution that is too big, or a file that cannot be read, fails with failure `size` or `copy` before any
    case runs."""
    ext = ARMS[arm]
    tree = tree_task(task)
    cases = sorted((TASKS / task / "hidden").glob("*.in"))
    main_total = sum(case_tier(case) != ADVERSARIAL for case in cases)
    if solution.is_symlink() or not solution.is_file():
        return {"status": "no-file", "passed": 0, "total": main_total, "failure": None, "code": None}
    grade_root = (clone_rootfs(args.chroot_root, scratch / f"{name}-grader-root")
                  if args.sandbox == "firejail" else scratch / f"{name}-grader-root")
    work = grade_root / WORKSPACE.relative_to("/")
    work.mkdir(parents=True)
    files = solution_files(solution.parent, ext) if tree else [Path(solution.name)]
    try:
        problem = tree_problem(solution.parent, files) if tree else None
        if problem is not None:
            return {"status": "fail", "passed": 0, "total": main_total, "failure": "size", "code": problem}
        for relative in files:
            (work / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(solution.parent / relative, work / relative)
    except OSError:
        return {"status": "fail", "passed": 0, "total": main_total, "failure": "copy", "code": None}
    if ext == "agc":
        shutil.copytree(RUNTIME, work, dirs_exist_ok=True)
    project_files(work, task, ext)

    def contained(command: list[str], stdin: str, timeout: int) -> tuple[str | None, str, int | None]:
        return contained_run(args, grade_root, work, command, stdin, timeout)

    def built(command: list[str], stdin: str, timeout: int) -> tuple[str | None, str, int | None]:
        return contained_run(args, grade_root, work, command, stdin, timeout, writable=True)

    extra: dict[str, int] = {}
    if arm in TYPED_ARMS:
        extra = type_escapes("\n".join((work / relative).read_text(encoding="utf-8", errors="replace")
                                       for relative in files))
        if extra["type_ignores"]:
            return {"status": "fail", "passed": 0, "total": main_total, "failure": "check", "code": "ignore",
                    "check_errors": 0, **extra}
        found = type_check(contained, main_total, [str(relative) for relative in files] if tree else None)
        if found is not None:
            return {**found, **extra}
        extra["check_errors"] = 0
    if ext == "go":
        found = go_check(contained, built, main_total, tree)
        if found is not None:
            return found
        extra["check_errors"] = 0
    driver = hidden_driver(task)
    timeout = case_timeout(task)
    passed, failure, code = 0, None, None
    counts = {"adversarial_passed": 0, "adversarial_total": 0, "regressions": 0, "hygiene_failed": 0,
              "crash_cases": 0}
    failed_cases: list[str] = []
    for case in cases:
        tier = case_tier(case)
        expected = case.with_suffix(".out").read_text(encoding="utf-8").rstrip("\n")
        command, stdin = case_invocation(ext, driver, case.read_bytes().decode("utf-8"), tree)
        out, err, returncode = contained(command, stdin, timeout)
        actual = None if out is None else out.rstrip("\n")
        ok = actual == expected and returncode == 0
        counts["adversarial_total"] += tier == ADVERSARIAL
        if ok:
            counts["adversarial_passed"] += tier == ADVERSARIAL
            passed += tier != ADVERSARIAL
            continue
        failed_cases.append(case.stem)
        kind, kind_code = classify(err, ext)
        counts["crash_cases"] += crashed(kind, returncode, driver is not None)
        counts["regressions"] += tier == REGRESSION
        counts["hygiene_failed"] += tier == HYGIENE
        if failure is None and tier != ADVERSARIAL:
            failure, code = kind, kind_code
    return {"status": "pass" if passed == main_total else "fail", "passed": passed, "total": main_total,
            "failure": failure, "code": code, **counts, "failed_cases": failed_cases, **extra}


def crashed(kind: str, returncode: int | None, driven: bool) -> bool:
    """A failed case crashed when its stderr shows a crash (classify gives `runtime`: a traceback, `panic:`,
    `fatal error:` or `error[RUNTIME-`) and the program exited non-zero. Under a driver the exit status is the
    driver's, and the program's stderr is what the driver passes on, so the marker alone counts."""
    return kind == "runtime" and (driven or returncode not in (0, None))


def classify(err: str, ext: str) -> tuple[str, str | None]:
    if err == "timeout":
        return "timeout", None
    if ext == "agc":
        for stage, kind in (("LEX-", "syntax"), ("PARSE-", "syntax"), ("CHECK-", "check"), ("RUNTIME-", "runtime")):
            if f"error[{stage}" in err:
                start = err.index(f"error[{stage}") + 6
                return kind, err[start:err.index("]", start)]
        return "logic", None
    if ext == "go":
        if "panic:" in err:
            return "runtime", "panic"
        return ("runtime", "fatal") if re.search(r"^fatal error: ", err, re.MULTILINE) else ("logic", None)
    if "SyntaxError" in err:
        return "syntax", "SyntaxError"
    if "Traceback" in err:
        return "runtime", err.strip().splitlines()[-1].split(":")[0]
    return "logic", None


def case_counts(task: str) -> dict[str, int]:
    """The tier counters of a run whose cases did not run (no file, or a failed check): every regression and hygiene
    case failed, and none passed or crashed."""
    tiers = Counter(case_tier(case) for case in (TASKS / task / "hidden").glob("*.in"))
    return {"adversarial_passed": 0, "adversarial_total": tiers[ADVERSARIAL], "regressions": tiers[REGRESSION],
            "hygiene_failed": tiers[HYGIENE], "crash_cases": 0}


def one_run(args: argparse.Namespace, results: Path, scratch: Path, task: str, arm: str, rep: int) -> dict:
    name = f"{task}-{arm}-{rep}"
    agent_root = (clone_rootfs(args.chroot_root, scratch / f"{name}-agent-root")
                  if args.sandbox == "firejail" else scratch / f"{name}-agent-root")
    work = agent_root / WORKSPACE.relative_to("/")
    prepare(work, task, arm)
    (agent_root / "home" / "agent").mkdir(parents=True, exist_ok=True)
    began = time.time()
    tree = tree_task(task)
    out, err, timed_out, _ = run_agent(
        args.agent, work, agent_root, task, arm, args.model, agent_timeout(task, args.timeout), args.sandbox,
        args.pass_env, args.image, args.pi_auth,
    )
    seconds = round(time.time() - began, 1)
    row = {"task": task, "arm": arm, "rep": rep, "agent": args.agent, "model": args.model or "default",
           "seconds": seconds, "agent_timeout": timed_out, "sandbox": args.sandbox, "image": args.image}
    if args.agent == "pi":
        row.update(pi_metrics(out, tree))
    elif args.agent == "claude":
        row.update(claude_metrics(out))
    row.update(spend(row))
    row["refused_queries"] = refused_queries(work)
    solution = work / f"solution.{ARMS[arm]}"
    row.update(grade(solution, task, arm, args, scratch, name))
    row = {**case_counts(task), **row}
    if timed_out:
        # The cost counts the turns Pi finished; a request still open when it was killed never reports one.
        row.update(status="timeout", failure="agent-timeout", code=None, cost_source=f"{row['cost_source']}-partial")
    run_dir = results / name
    run_dir.mkdir(parents=True)
    (run_dir / "agent.jsonl").write_text(out, encoding="utf-8")
    (run_dir / "agent.stderr").write_text(err, encoding="utf-8")
    kept = [Path(solution.name)] if not tree else [
        Path("solution") / relative for relative in solution_files(work, ARMS[arm])[:TREE_LIMIT]
        if (work / relative).stat().st_size <= TREE_FILE_LIMIT]
    for relative in kept:
        source = work / relative.relative_to("solution") if tree else solution
        (run_dir / relative).parent.mkdir(parents=True, exist_ok=True)
        if copy_candidate(source, run_dir / relative):
            redact_file(run_dir / relative, args.pass_env, auth_secrets(args.pi_auth))
    with WRITE_LOCK:
        with (results / "results.jsonl").open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        print(f"{name}: {row['status']} {row['passed']}/{row['total']} {seconds}s", flush=True)
    return row


PREFLIGHT_PROMPT = "Reply with the word pong."
PREFLIGHT_TIMEOUT = 120
UNKNOWN_MODEL = re.compile(r'Model "[^"]*" not found for provider "[^"]*"')


def preflight_result(out: str, err: str, timed_out: bool, returncode: int | None, model: str) -> dict:
    """Check one tiny Pi call: it ended, the provider took the key and the model, the answer has tokens, the stream
    parses, and the run has a cost source. Stops the round with a message otherwise. Pi exits 0 on a provider
    error, so the error comes from the assistant's `message_end`."""
    if timed_out:
        raise SystemExit(f"preflight: Pi did not answer in {PREFLIGHT_TIMEOUT} s")
    unknown = UNKNOWN_MODEL.search(err)
    if unknown:
        raise SystemExit(f"preflight: Pi does not know the model {model}: {unknown.group(0)}")
    replies = [event["message"] for event in json_events(out) if event.get("type") == "message_end"
               and isinstance(event.get("message"), dict) and event["message"].get("role") == "assistant"]
    for reply in replies:
        if reply.get("stopReason") == "error":
            raise SystemExit(f"preflight: the provider refused the call (auth or model?): "
                             f"{str(reply.get('errorMessage', ''))[:120]}")
    if returncode != 0:
        raise SystemExit(f"preflight: Pi exited {returncode}: {err.strip()[-300:]}")
    row = {"model": model, **pi_metrics(out)}
    tokens = row["tokens_in"] + row["tokens_out"] + row["tokens_cached"]
    answered = any(part.get("type") == "text" and str(part.get("text", "")).strip()
                   for reply in replies for part in reply.get("content", []) if isinstance(part, dict))
    if row["turns"] < 1 or tokens <= 0 or not answered:
        raise SystemExit(f"preflight: no answer with tokens from {model} (turns {row['turns']}, tokens {tokens})")
    row.update(spend(row))
    if row["cost_source"] == "none":
        raise SystemExit(f"no cost source for {model}: Pi reported a cost of 0 and PRICES in run.py has no price for it")
    return {"ok": True, "cost_source": row["cost_source"], "tokens": tokens, "turns": row["turns"],
            "cost": round(row["cost"], 6)}


def run_preflight(args: argparse.Namespace) -> dict:
    """One tiny call in the agent image, with the round's model, mounts, auth and network."""
    with tempfile.TemporaryDirectory(prefix="agentica-preflight-") as directory:
        work = Path(directory) / "workspace"
        work.mkdir()
        out, err, timed_out, returncode = run_agent(
            "pi", work, Path(directory), "preflight", "typed-python", args.model, PREFLIGHT_TIMEOUT, args.sandbox,
            args.pass_env, args.image, args.pi_auth, text=PREFLIGHT_PROMPT)
    result = preflight_result(out, err, timed_out, returncode, args.model or "default")
    print(f"preflight: ok, {result['tokens']} tokens, ${result['cost']:.6f} ({result['cost_source']})", flush=True)
    return result


class Budget:
    """The `--max-cost` cap, a soft one. A run starts only when the cost so far, plus the estimate for this run and
    for every run in flight, stays under the cap; the first refusal is final, so the round stops starting runs and
    the ones in flight finish. Those runs, and a run dearer than the estimate, can still pass the cap: by up to
    `--jobs` times the costliest run.

    The estimate is the highest cost seen so far (which is never below the mean), and never below `floor`. A run
    that reports no cost (no usage at all, or a cost of 0: a timeout, a 429, an auth error) says nothing about what
    a run costs, so it is charged the estimate and kept out of that figure."""

    def __init__(self, cap: float | None, floor: float) -> None:
        self.cap, self.floor = cap, floor
        self.spent, self.finished, self.in_flight, self.skipped = 0.0, 0, 0, 0
        self.highest = 0.0
        self.stopped = False
        self.lock = threading.Lock()

    def charge(self, cost: float) -> None:
        """Add a cost outside the runs (the preflight)."""
        with self.lock:
            self.spent += cost

    def estimate(self) -> float:
        return max(self.floor, self.highest)

    def begin(self) -> bool:
        with self.lock:
            if self.cap is not None and (self.stopped or self.spent + self.estimate() * (self.in_flight + 1) > self.cap):
                self.stopped = True
                self.skipped += 1
                return False
            self.in_flight += 1
            return True

    def end(self, cost: float | None) -> tuple[float, bool]:
        """Add the cost of a finished run. Returns the total and whether the run was charged the estimate because it
        reported no usable cost (None or not above 0)."""
        with self.lock:
            unknown = cost is None or cost <= 0
            charged = self.estimate() if unknown else cost
            if not unknown:
                self.highest = max(self.highest, charged)
            self.in_flight -= 1
            self.finished += 1
            self.spent += charged
            return self.spent, unknown


def budgeted_run(args: argparse.Namespace, budget: Budget, results: Path, scratch: Path,
                 task: str, arm: str, rep: int) -> None:
    if not budget.begin():
        return
    cost = None
    try:
        cost = one_run(args, results, scratch, task, arm, rep).get("cost")
    finally:
        total, unknown = budget.end(cost)
        if unknown and budget.cap is not None:
            print(f"warning: {task}-{arm}-{rep} reported no cost; charged the estimate "
                  f"${budget.estimate():.4f}", flush=True)
        cap = f" of the ${budget.cap:.2f} cap" if budget.cap is not None else ""
        print(f"cost so far: ${total:.4f}{cap}", flush=True)


def read_rows(results: Path) -> list[dict]:
    return [json.loads(line) for line in (results / "results.jsonl").read_text(encoding="utf-8").splitlines()]


def git_output(*command: str, cwd: Path = EVAL) -> str:
    try:
        return git(*command, cwd=cwd)
    except (OSError, subprocess.CalledProcessError):
        return ""


def agentica_version() -> str:
    try:
        done = subprocess.run([str(RUNTIME / "bin" / "agentica"), "--version"], capture_output=True, text=True,
                              timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def agentica_info(args: argparse.Namespace, used: bool) -> dict:
    """What run.json records of the Agentica under test; nothing when no arm runs Agentica."""
    binary = RUNTIME / "bin" / "agentica"
    return {"agentica_version": agentica_version() if used else None,
            "agentica_commit": git_output("rev-parse", "HEAD", cwd=ROOT) if used else None,
            "agentica_binary_sha256": sha256_of(binary) if used and binary.is_file() else None,
            "agentica_override": args.agentica is not None, "agentica_src_override": args.agentica_src is not None}


def run_info(args: argparse.Namespace, image_info: dict[str, str | None], agentica: dict | None = None) -> dict:
    return {"commit": git_output("rev-parse", "HEAD"), "dirty": bool(git_output("status", "--porcelain")),
            **(agentica or {}),
            "agent": args.agent, "model": args.model or "default", "arms": args.arms, "tasks": args.tasks,
            "reps": args.reps, "timeout": args.timeout, "sandbox": args.sandbox, "image": args.image,
            "image_id": image_info["image_id"], "checker": image_info["checker"], "go": image_info.get("go"),
            "pi_version": image_info.get("pi"), "pass_env": args.pass_env,
            "agent_network": AGENT_NETWORK and args.agent != "reference", "arm_tasks": args.arm_tasks,
            "max_cost": args.max_cost, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pi_auth_file": args.pi_auth is not None,
            "arm_notes": {arm: NOCLI_NOTE for arm in args.arms if arm == "skill-nocli"}}


def start_outcome(args: argparse.Namespace, scratch: Path, task: str, arm: str) -> tuple:
    work = scratch / f"{task}-{arm}-start"
    work.mkdir()
    solution = work / f"solution.{ARMS[arm]}"
    if tree_task(task):
        start = TASKS / task / "start" / ARMS[arm]
        if not start.is_dir():
            raise SystemExit(f"{task}: no start tree for {arm} (start/{ARMS[arm]}/); every language needs one")
        shutil.copytree(start, work, dirs_exist_ok=True)
    else:
        shutil.copyfile(start_file(task, arm), solution)
    row = grade(solution, task, arm, args, scratch, f"{task}-{arm}-start")
    return row["status"], row["passed"], row["failure"]


def check_starts(args: argparse.Namespace) -> int:
    """Each start.go must grade like the typed Python start: the same status, passed cases and failure kind. A tree
    task's start trees (start/<ext>/) must grade alike in all three languages."""
    tasks = [task for task in args.tasks if (TASKS / task / "start.go").is_file() or (TASKS / task / "start" / "go").is_dir()]
    arms = {task: ("typed-python", "go", "binary") if tree_task(task) else ("typed-python", "go") for task in tasks}
    with tempfile.TemporaryDirectory(prefix="agentica-eval-starts-") as directory, \
            ThreadPoolExecutor(max_workers=args.jobs) as pool:
        scratch = Path(directory)
        futures = {(task, arm): pool.submit(start_outcome, args, scratch, task, arm)
                   for task in tasks for arm in arms[task]}
        outcomes = {key: future.result() for key, future in futures.items()}
    differ = []
    for task in tasks:
        found = {arm: outcomes[task, arm] for arm in arms[task]}
        same = len(set(found.values())) == 1
        print(f"{task}: " + ", ".join(f"{arm} {outcome}" for arm, outcome in found.items()) + ("" if same else "  DIFFER"))
        if not same:
            differ.append(task)
    if differ:
        print("starts that differ: " + ", ".join(differ))
        return 1
    return 0


def use_sources(checkout: Path | None) -> None:
    global ROOT
    ROOT = checkout.resolve() if checkout is not None else fetch_sources(AGENTICA_COMMIT)
    missing = [path for path in SOURCE_PATHS if not (ROOT / path).is_dir()]
    if missing:
        raise SystemExit(f"{ROOT} is not an agentica checkout: it has no {', '.join(missing)}")


def mean_known(rows: list[dict], keys: tuple[str, ...], places: int) -> str:
    """The mean over `rows` of the sum of `keys`, or `-` when any row lacks a key: results files from before a
    field existed have no value for it, which is unknown, not 0."""
    if any(key not in row for row in rows for key in keys):
        return "-"
    total = sum(row[key] for row in rows for key in keys) / len(rows)
    return f"{total:.{places}f}"


def summarize(results: Path) -> None:
    rows = read_rows(results)
    info_file = results / "run.json"
    info = json.loads(info_file.read_text(encoding="utf-8")) if info_file.is_file() else {}
    groups = {}
    for row in rows:
        groups.setdefault((row["task"], row["arm"]), []).append(row)
    out = ["| task | arm | runs | pass | cases | tokens | context | spend $ | cost in $ | cost cache $ | cost out $ | seconds | failing runs | fix rounds | check runs | query runs | refused | read runs | type escapes | failures |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (task, arm), rs in sorted(groups.items()):
        n = len(rs)
        mean = lambda key: round(sum(r.get(key, 0) for r in rs) / n, 1)
        tokens = round(sum(r.get("tokens_in", 0) + r.get("tokens_out", 0) for r in rs) / n)
        # The context is what the agent read: uncached input, cache reads and cache writes. Older rows have no
        # `tokens_cache_write`; it counts only when present.
        context = "-" if any("tokens_in" not in r or "tokens_cached" not in r for r in rs) else str(round(
            sum(r["tokens_in"] + r["tokens_cached"] + r.get("tokens_cache_write", 0) for r in rs) / n))
        passes = sum(r["status"] == "pass" for r in rs)
        cases = round(sum(r["passed"] / r["total"] if r["total"] else 1 for r in rs) / n * 100)
        kinds = ", ".join(sorted({f"{r['failure']}:{r['code']}" if r["code"] else str(r["failure"]) for r in rs if r["failure"]})) or "-"
        out.append(f"| {task} | {arm} | {n} | {passes}/{n} | {cases}% | {tokens} | {context} | {mean_known(rs, ('cost',), 4)} | {mean_known(rs, ('cost_input',), 4)} | {mean_known(rs, ('cost_cache',), 4)} | {mean_known(rs, ('cost_output',), 4)} | {mean('seconds')} | {mean('failing_runs')} | {mean_known(rs, ('fix_rounds',), 1)} | {mean('check_runs')} | {mean('query_runs')} | {mean('refused_queries')} | {mean('read_runs')} | {mean_known(rs, ('type_escapes',), 1)} | {kinds} |")
    out += ["", *arm_totals(rows)]
    if info.get("cost") is not None:
        out += ["", f"cost: ${info['cost']:.4f}" + (f" (cap ${info['max_cost']:.2f})" if info.get("max_cost") is not None else "")]
    out += ["", f"stopped_for_budget: {str(bool(info.get('stopped_for_budget'))).lower()}"
            + (f" ({info['runs_skipped']} runs not started)" if info.get("stopped_for_budget") else "")]
    if info.get("stopped_for_budget"):
        out += reps_completed(rows, info)
    text = "\n".join(out) + "\n"
    (results / "summary.md").write_text(text, encoding="utf-8")
    print(text)


def arm_totals(rows: list[dict]) -> list[str]:
    """One line per arm over the tasks every arm ran, so arms with different task sets (the go arm skips a task
    without Go files) compare on the same tasks: the spend in total and per run, and the fix rounds per run. A row
    without the field (an older results file) makes that figure unknown (`-`). Each arm's tasks follow the table,
    and the go arm's runs that failed `go vet` alone (the build passed)."""
    by_arm: dict[str, list[dict]] = {}
    for row in rows:
        by_arm.setdefault(row["arm"], []).append(row)
    common = set.intersection(*({row["task"] for row in rs} for rs in by_arm.values())) if by_arm else set()
    arms = {arm: [row for row in rs if row["task"] in common] for arm, rs in by_arm.items()}
    out = [f"Totals over the {len(common)} tasks every arm ran:", "",
           "| arm | runs | pass | spend $ | spend $ per run | fix rounds per run | spend from |",
           "|---|---|---|---|---|---|---|"]
    for arm, rs in sorted(arms.items()):
        total = "-" if any("cost" not in r for r in rs) else f"{sum(r['cost'] for r in rs):.4f}"
        sources = ", ".join(f"{source} {count}" for source, count in
                            sorted(Counter(r.get("cost_source", "-") for r in rs).items()))
        out.append(f"| {arm} | {len(rs)} | {sum(r['status'] == 'pass' for r in rs)}/{len(rs)} | {total} | "
                   f"{mean_known(rs, ('cost',), 4)} | {mean_known(rs, ('fix_rounds',), 2)} | {sources} |")
    out += ["", *quality_totals(arms)]
    out.append("")
    for arm, rs in sorted(by_arm.items()):
        out.append(f"{arm} tasks: {' '.join(sorted({row['task'] for row in rs}))}")
    go = by_arm.get("go", [])
    if go:
        out.append(f"go runs that failed go vet alone (the build passed): {sum(bool(r.get('build_ok')) for r in go)} "
                   f"of {len(go)}")
    return out


def summed(rows: list[dict], key: str) -> str:
    return "-" if any(key not in row for row in rows) else str(sum(row[key] for row in rows))


def quality_totals(arms: dict[str, list[dict]]) -> list[str]:
    """Beyond pass or fail, per arm over the same tasks: the share of main cases passed, the adversarial cases passed,
    the failed cases that crashed, the regression and hygiene cases failed, the spec runs, and the spend per passing
    run (`-` when no run passed). Rows from before a field existed make it unknown (`-`)."""
    out = ["| arm | cases passed | adversarial | crash cases | regressions | hygiene failed | spec runs | $ per pass |",
           "|---|---|---|---|---|---|---|---|"]
    for arm, rs in sorted(arms.items()):
        passed, total = sum(r["passed"] for r in rs), sum(r["total"] for r in rs)
        cases = f"{passed}/{total}" if total else "-"
        adversarial = ("-" if any("adversarial_total" not in r for r in rs) else
                       f"{sum(r['adversarial_passed'] for r in rs)}/{sum(r['adversarial_total'] for r in rs)}")
        passes = sum(r["status"] == "pass" for r in rs)
        per_pass = "-" if not passes or any("cost" not in r for r in rs) else f"{sum(r['cost'] for r in rs) / passes:.4f}"
        out.append(f"| {arm} | {cases} | {adversarial} | {summed(rs, 'crash_cases')} | {summed(rs, 'regressions')} | "
                   f"{summed(rs, 'hygiene_failed')} | {summed(rs, 'spec_runs')} | {per_pass} |")
    return out


def run_order(tasks: list[str], arms: list[str], arm_tasks: dict[str, list[str]], reps: int) -> list[tuple[str, str, int]]:
    """The queue: rep by rep, and inside a rep task by task, then arm by arm. A budget stop then
    leaves every (task, arm) with the same number of reps, give or take one, instead of dropping a whole task or
    arm block. With --jobs above 1 the pool starts the runs in this order."""
    pairs = [(task, arm) for task in tasks for arm in arms if task in arm_tasks.get(arm, tasks)]
    return [(task, arm, rep) for rep in range(1, reps + 1) for task, arm in pairs]


def reps_completed(rows: list[dict], info: dict) -> list[str]:
    """Lines saying how many reps each (task, arm) of the round finished, grouped by that count, most reps first.
    Needs the planned grid in run.json; older files without it give no lines."""
    if not all(key in info for key in ("tasks", "arms", "reps")):
        return []
    done: dict[tuple[str, str], int] = {}
    for row in rows:
        done[(row["task"], row["arm"])] = done.get((row["task"], row["arm"]), 0) + 1
    planned = [(task, arm) for task, arm, _ in run_order(info["tasks"], info["arms"], info.get("arm_tasks") or {}, 1)]
    by_count: dict[int, list[str]] = {}
    for task, arm in planned:
        by_count.setdefault(done.get((task, arm), 0), []).append(f"{task}/{arm}")
    return [f"reps completed (of {info['reps']}): {count}: " + ", ".join(names)
            for count, names in sorted(by_count.items(), reverse=True)]


def parse_arm_tasks(specs: list[str], arms: list[str], tasks: list[str]) -> dict[str, list[str]]:
    """`ARM=TASK,TASK` options to {arm: [task, ...]}; an unknown arm, or a task outside --tasks, stops the run."""
    chosen: dict[str, list[str]] = {}
    for spec in specs:
        arm, _, names = spec.partition("=")
        if arm not in arms or not names:
            raise SystemExit(f"--arm-tasks {spec!r}: expected ARM=TASK,TASK with an ARM in --arms ({' '.join(arms)})")
        listed = names.split(",")
        unknown = [name for name in listed if name not in tasks]
        if unknown:
            raise SystemExit(f"--arm-tasks {spec!r}: not in --tasks (use full task names): {' '.join(unknown)}")
        chosen[arm] = listed
    return chosen


def limit_go_tasks(arms: list[str], tasks: list[str], arm_tasks: dict[str, list[str]]) -> dict[str, list[str]]:
    """A task without a reference.go is not available in Go yet: the go arm skips it, with a note."""
    if "go" not in arms:
        return arm_tasks
    chosen = arm_tasks.get("go", tasks)
    available = [task for task in chosen if has_reference(task, "go")]
    skipped = [task for task in chosen if task not in available]
    if skipped:
        print(f"go: not available in Go yet (no reference.go), skipped: {' '.join(skipped)}", flush=True)
    return {**arm_tasks, "go": available}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=["pi", "claude", "reference"], default="pi")
    parser.add_argument("--model")
    parser.add_argument("--pi-auth", type=Path, metavar="PATH",
                        help="a Pi auth.json (such as .secrets/pi-auth.json), mounted read-only in the agent "
                             "container and copied to its ~/.pi/agent/auth.json; its keys are redacted from the logs")
    parser.add_argument("--tasks", nargs="*", default=sorted(p.name for p in TASKS.iterdir() if p.is_dir()))
    parser.add_argument("--arms", nargs="*", help=f"default: {' '.join(DEFAULT_ARMS)}; opt-in: {' '.join(sorted(OPT_IN_ARMS))}")
    parser.add_argument("--arm-tasks", action="append", default=[], metavar="ARM=TASK,TASK",
                        help="run ARM only on these tasks (full names, all in --tasks); repeat for several arms")
    parser.add_argument("--max-cost", type=float, metavar="USD",
                        help="soft cap: stop starting new runs when the cost so far plus the estimate of the runs "
                             "in flight and of the next one would pass USD. Runs already going and outlier runs "
                             "can go past it by up to --jobs x the costliest run (default: no cap)")
    parser.add_argument("--run-cost-estimate", type=float, default=0.01, metavar="USD",
                        help="lowest estimate of one run for --max-cost; the highest cost seen so far replaces it "
                             "when higher (default: %(default)s)")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--jobs", type=int, default=1, help="runs in parallel")
    parser.add_argument("--agentica", type=Path, metavar="PATH",
                        help=f"the agentica binary to test, built for Linux x86_64 (default: the {AGENTICA_VERSION} "
                             "release, downloaded and checked)")
    parser.add_argument("--agentica-src", type=Path, metavar="PATH",
                        help="an agentica checkout for the skill, the grammar, the library pages and the examples "
                             f"(default: commit {AGENTICA_COMMIT[:12]}, the {AGENTICA_VERSION} tag)")
    parser.add_argument("--chroot-root", type=Path,
                        help="prepared minimal Firejail root filesystem; its glibc must run the agentica binary")
    parser.add_argument("--pass-env", action="append", default=[], metavar="NAME",
                        help="pass one provider-auth environment variable to the agent; repeat as needed")
    parser.add_argument("--sandbox", choices=["docker", "firejail"], default="docker",
                        help="firejail runs the agentica binary on the chroot's glibc")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Docker image; the default is built when missing")
    parser.add_argument("--summarize", metavar="RESULTS_DIR")
    parser.add_argument("--no-preflight", action="store_true",
                        help="skip the preflight: one tiny Pi call with the round's model, auth and image that "
                             "checks the auth, the model, the tokens and the cost source before any task runs")
    parser.add_argument("--preflight-only", action="store_true", help="run the preflight alone and exit")
    parser.add_argument("--check-starts", action="store_true",
                        help="grade each start.go and its typed Python start as solutions and exit 1 when their "
                             "status, passed cases or failure kind differ (no model, no credentials)")
    parser.add_argument("--check-references", action="store_true",
                        help="grade every reference solution (no model, no credentials) and exit 1 if one fails; "
                             f"arms default to {' '.join(REFERENCE_ARMS)}")
    args = parser.parse_args()
    if args.summarize:
        summarize(Path(args.summarize))
        return 0
    if args.check_references or args.check_starts:
        args.agent = "reference"
        args.pass_env = []
    if args.check_starts:
        trees = any(tree_task(task) and (TASKS / task / "start").is_dir() for task in args.tasks)
        args.arms = ["typed-python", "go", *(["binary"] if trees else [])]
    args.arms = args.arms or (REFERENCE_ARMS if args.check_references else DEFAULT_ARMS)
    args.arm_tasks = limit_go_tasks(args.arms, args.tasks, parse_arm_tasks(args.arm_tasks, args.arms, args.tasks))
    if not args.check_starts and not run_order(args.tasks, args.arms, args.arm_tasks, 1):
        raise SystemExit("nothing to run: every selected task is skipped by every selected arm "
                         "(the go arm runs only the tasks with a Go reference)")
    if args.max_cost is not None and args.max_cost <= 0:
        raise SystemExit("--max-cost must be more than 0")
    if args.agent == "reference":
        args.pi_auth = None
    if args.pi_auth is not None:
        if args.agent != "pi" or args.sandbox != "docker":
            raise SystemExit("--pi-auth is for --agent pi in the Docker sandbox")
        args.pi_auth = args.pi_auth.resolve()
        if "," in str(args.pi_auth):
            raise SystemExit("--pi-auth: the path cannot hold a comma (Docker's --mount splits on it)")
        if not args.pi_auth.is_file():
            raise SystemExit(f"--pi-auth: no such file: {args.pi_auth}")
        if args.pi_auth.stat().st_mode & 0o077:
            print(f"warning: --pi-auth {args.pi_auth} can be read by other users; chmod 600 it", flush=True)
        auth_secrets(args.pi_auth)
    typed = any(arm in TYPED_ARMS for arm in args.arms)
    agentica = any(ARMS[arm] == "agc" for arm in args.arms)
    child_environment(args.pass_env, in_chroot=True, workspace=WORKSPACE)
    if args.sandbox == "docker":
        require_docker()
    else:
        if args.chroot_root is None:
            raise SystemExit("--sandbox firejail requires --chroot-root")
        if "go" in args.arms:
            raise SystemExit("the go arm runs only in the Docker sandbox (its Go settings come from the image)")
        args.chroot_root = args.chroot_root.resolve()
        validate_sandbox(args.chroot_root, args.agent, typed)
    preflight = args.agent == "pi" and args.sandbox == "docker" and not args.no_preflight
    if args.preflight_only:
        if not preflight:
            raise SystemExit("--preflight-only needs --agent pi in the Docker sandbox, without --no-preflight")
        validate_docker(args.image, pi=True)
        print(json.dumps(run_preflight(args)))
        return 0
    if agentica:
        use_sources(args.agentica_src)
        install_runtime(args.agentica)
        if any(ecosystem_task(task) for task in args.tasks):
            ecosystem_deps()
    image_info: dict[str, str | None] = {"checker": None, "go": None, "image_id": None, "pi": None}
    if args.sandbox == "docker":
        image_info = validate_docker(args.image, typed, agentica, args.agent == "pi", "go" in args.arms)
    if args.check_starts:
        return check_starts(args)
    checked = run_preflight(args) if preflight else None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = EVAL / "results" / f"{stamp}-{args.agent}"
    results.mkdir(parents=True)
    (results / "run.json").write_text(json.dumps({**run_info(args, image_info, agentica_info(args, agentica)), "preflight": checked}, indent=2) + "\n",
                                      encoding="utf-8")
    jobs = run_order(args.tasks, args.arms, args.arm_tasks, args.reps)
    budget = Budget(args.max_cost, args.run_cost_estimate)
    if checked:
        budget.charge(checked["cost"])
    with tempfile.TemporaryDirectory(prefix="agentica-eval-") as scratch_dir:
        scratch = Path(scratch_dir)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for future in [pool.submit(budgeted_run, args, budget, results, scratch, *job) for job in jobs]:
                future.result()
    info = json.loads((results / "run.json").read_text(encoding="utf-8"))
    info.update(cost=round(budget.spent, 6), stopped_for_budget=budget.stopped, runs_skipped=budget.skipped)
    (results / "run.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    summarize(results)
    print(f"results: {results}")
    failed = [row for row in read_rows(results) if row["status"] != "pass"]
    if args.agent == "reference" and failed:
        print("reference solutions that failed: " + ", ".join(
            f"{row['task']}/{row['arm']} ({row['failure']}: {' '.join(row.get('failed_cases', [])) or '-'})"
            for row in failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
