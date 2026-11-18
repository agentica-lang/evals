import contextlib
import functools
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import uuid
from argparse import Namespace
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import run


def require_docker_image(*, checker: bool = False) -> None:
    if not shutil.which("docker"):
        raise unittest.SkipTest("Docker is unavailable")
    image = subprocess.run(
        ["docker", "image", "inspect", run.DEFAULT_IMAGE], capture_output=True
    )
    if image.returncode:
        raise unittest.SkipTest("evaluation image has not been built")
    if checker and run.checker_version(run.DEFAULT_IMAGE) is None:
        raise unittest.SkipTest("evaluation image has no type checker")


class ChildEnvironmentTests(unittest.TestCase):
    def test_only_allowlisted_environment_is_passed(self) -> None:
        with patch.dict(os.environ, {"PROVIDER_TOKEN": "secret", "OTHER_SECRET": "hidden"}, clear=True):
            env = run.child_environment(["PROVIDER_TOKEN"], in_chroot=True, workspace=Path("/tmp/work"))

        self.assertEqual(env["PROVIDER_TOKEN"], "secret")
        self.assertNotIn("OTHER_SECRET", env)
        self.assertEqual(env["PATH"], run.ROOTFS_PATH)
        self.assertEqual(env["HOME"], "/home/agent")

    def test_rejects_invalid_reserved_and_unset_names(self) -> None:
        for name, variables in (
            ("BAD-NAME", {}),
            ("HOME", {"HOME": "/host/home"}),
            ("TMPDIR", {"TMPDIR": "/host/tmp"}),
            ("MISSING_TOKEN", {}),
        ):
            with self.subTest(name=name), patch.dict(os.environ, variables, clear=True):
                with self.assertRaises(SystemExit):
                    run.child_environment([name], in_chroot=True, workspace=Path("/tmp/work"))

    def test_redacts_allowlisted_values(self) -> None:
        with patch.dict(os.environ, {"PROVIDER_TOKEN": "secret-value"}, clear=True):
            output = run.redact_secrets("logged secret-value", ["PROVIDER_TOKEN"])

        self.assertEqual(output, "logged [REDACTED]")

    def test_the_pi_auth_file_is_mounted_read_only_and_its_keys_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / "pi-auth.json"
            auth.write_text(json.dumps({"opencode-go": {"type": "api_key", "key": "sk-test-0123456789"}}))
            secrets = run.auth_secrets(auth)
            command = run.docker_prefix(Path(directory), "image", "name", network=True, pass_env=[], pi_auth=auth)
            auth.write_text("{not json")
            with self.assertRaises(SystemExit) as raised:
                run.auth_secrets(auth)
            auth.write_bytes(b"\xff\xfe{")
            with self.assertRaises(SystemExit):
                run.auth_secrets(auth)

        self.assertEqual(secrets, ["sk-test-0123456789"])
        self.assertIn(f"type=bind,src={auth},dst={run.PI_AUTH_MOUNT},readonly", command)
        self.assertEqual(run.redact_secrets("key sk-test-0123456789", [], secrets), "key [REDACTED]")
        self.assertNotIn("not json", str(raised.exception))

    def test_a_secret_split_over_stream_deltas_or_json_escaped_never_reaches_the_log(self) -> None:
        key = 'sk-"split\\0123456789'
        escaped = json.dumps(key)[1:-1]
        events = [{"type": "message_update", "assistantMessageEvent": {"type": "toolcall_delta", "delta": escaped[:6]}},
                  {"type": "message_update", "assistantMessageEvent": {"type": "toolcall_delta", "delta": escaped[6:]}},
                  {"type": "tool_execution_update", "toolCallId": "1", "partialResult": {"content": [
                      {"type": "text", "text": key[:5]}]}},
                  {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": key}]}},
                  {"type": "tool_execution_end", "toolCallId": "1", "result": {"content": [{"type": "text", "text": key}]}}]
        log = run.agent_log("not json " + key + "\n" + "\n".join(json.dumps(event) for event in events) + "\n", [], [key])

        self.assertNotIn("sk-", log)
        self.assertNotIn("message_update", log)
        self.assertNotIn("tool_execution_update", log)
        self.assertEqual(log.count("[REDACTED]"), 3)
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "solution.py"
            copy.write_bytes(b"\xff key = '" + key.encode() + b"'\n")
            run.redact_file(copy, [], [key])
            self.assertEqual(copy.read_bytes(), b"\xff key = '[REDACTED]'\n")


class JailCommandTests(unittest.TestCase):
    def test_agent_has_chroot_and_network_access(self) -> None:
        command = run.jail_prefix(Path("/tmp/rootfs"), network=True)

        self.assertIn("--chroot=/tmp/rootfs", command)
        self.assertIn("--private-tmp", command)
        self.assertIn("--nonewprivs", command)
        self.assertIn("--caps.drop=all", command)
        self.assertIn("--seccomp", command)
        self.assertNotIn("--net=none", command)

    def test_grader_has_no_network(self) -> None:
        command = run.jail_prefix(Path("/tmp/rootfs"), network=False)

        self.assertIn("--net=none", command)


class CandidateBoundaryTests(unittest.TestCase):
    def test_copies_regular_candidate_and_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "solution.py"
            destination = root / "copy.py"
            source.write_text("print('ok')\n")
            self.assertTrue(run.copy_candidate(source, destination))
            self.assertEqual(destination.read_text(), "print('ok')\n")

            link = root / "linked.py"
            link.symlink_to(source)
            self.assertFalse(run.copy_candidate(link, root / "linked-copy.py"))

    def test_rootfs_clone_clears_agent_writable_and_home_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template"
            (template / "workspace").mkdir(parents=True)
            (template / "workspace" / "leftover.txt").write_text("old workspace")
            outside_home = root / "outside-home"
            (outside_home / "agent").mkdir(parents=True)
            (outside_home / "agent" / "credentials").write_text("old credentials")
            (template / "home").symlink_to(outside_home, target_is_directory=True)
            clone = run.clone_rootfs(template, root / "clone")

            self.assertFalse((clone / "workspace").exists())
            self.assertFalse((clone / "home" / "agent").exists())
            self.assertEqual((outside_home / "agent" / "credentials").read_text(), "old credentials")


@functools.cache
def fetched_sources() -> Path | None:
    try:
        return run.fetch_sources(run.AGENTICA_COMMIT)
    except (OSError, subprocess.CalledProcessError):
        return None


def real_sources() -> Path:
    """The pinned Agentica sources, fetched once into .cache; the test is skipped when they cannot be fetched
    (offline)."""
    sources = fetched_sources()
    if sources is None:
        raise unittest.SkipTest(f"cannot fetch {run.AGENTICA_REPO} at {run.AGENTICA_COMMIT[:12]} (offline?)")
    return sources


def real_skill() -> Path:
    return real_sources() / ".agents" / "skills" / "agentica-programming"


def release_archive(binary: bytes) -> bytes:
    """A release archive with bin/agentica, in the layout of the real one."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo(f"agentica-{run.AGENTICA_VERSION}-linux-x86_64/bin/agentica")
        info.size = len(binary)
        bundle.addfile(info, io.BytesIO(binary))
    return buffer.getvalue()


def git_in(path: Path, *command: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *command], cwd=path,
                          check=True, capture_output=True, text=True).stdout.strip()


class SupplyChainTests(unittest.TestCase):
    """The pinned Agentica: the release download and the source checkout, served locally (no network)."""

    def download(self, cache: Path, payload: bytes, sha: str) -> Path:
        with (patch.object(run, "CACHE", cache), patch.object(run, "AGENTICA_ARCHIVE_SHA256", sha),
              patch("urllib.request.urlopen", lambda url, timeout: io.BytesIO(payload))):
            return run.release_binary()

    def test_a_wrong_sha_stops_and_leaves_nothing_and_the_right_one_extracts_the_binary(self) -> None:
        payload = release_archive(b"#!/bin/sh\necho 0.34.1\n")
        right = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with self.assertRaises(SystemExit) as raised:
                self.download(cache, payload, "0" * 64)
            left_after_failure = sorted(path.name for path in cache.iterdir())
            binary = self.download(cache, payload, right)

            self.assertIn("does not match its pinned SHA-256", str(raised.exception))
            self.assertEqual(left_after_failure, [])
            self.assertEqual(binary, cache / f"agentica-{run.AGENTICA_VERSION}-{right[:12]}" / "agentica")
            self.assertEqual(binary.read_bytes(), b"#!/bin/sh\necho 0.34.1\n")
            self.assertEqual(sorted(path.name for path in cache.iterdir()),
                             sorted([run.AGENTICA_ARCHIVE, binary.parent.name]))

    def test_fetch_sources_checks_out_the_pinned_commit_and_recovers_from_a_failed_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory) / "agentica"
            for path in run.SOURCE_PATHS:
                (upstream / path).mkdir(parents=True)
                (upstream / path / "README.md").write_text("pinned\n")
            (upstream / "vm").mkdir()
            (upstream / "vm" / "big.c").write_text("not wanted\n")
            git_in(upstream, "init", "-q")
            git_in(upstream, "config", "uploadpack.allowAnySHA1InWant", "true")
            git_in(upstream, "add", ".")
            git_in(upstream, "commit", "-q", "-m", "pinned")
            pinned = git_in(upstream, "rev-parse", "HEAD")
            (upstream / "examples" / "README.md").write_text("later\n")
            git_in(upstream, "commit", "-q", "-am", "later")
            cache = Path(directory) / "cache"
            broken = cache / f"agentica-{pinned[:12]}"
            cache.mkdir()
            git_in(cache, "init", "-q", broken.name)
            with patch.object(run, "CACHE", cache), patch.object(run, "AGENTICA_REPO", upstream.as_uri()):
                checkout = run.fetch_sources(pinned)
                again = run.fetch_sources(pinned)

            self.assertEqual((checkout, again), (broken, broken))
            self.assertEqual(git_in(checkout, "rev-parse", "HEAD"), pinned)
            self.assertEqual((checkout / "examples" / "README.md").read_text(), "pinned\n")
            self.assertFalse((checkout / "vm").exists())

    def test_run_json_records_the_agentica_under_test_only_when_an_arm_runs_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime"
            (runtime / "bin").mkdir(parents=True)
            (runtime / "bin" / "agentica").write_bytes(b"binary")
            args = Namespace(agentica=Path("/x/agentica"), agentica_src=None)
            with (patch.object(run, "RUNTIME", runtime), patch.object(run, "agentica_version", return_value="0.34.1"),
                  patch.object(run, "git_output", return_value="abc123")):
                used = run.agentica_info(args, True)
                unused = run.agentica_info(args, False)

        self.assertEqual(used, {"agentica_version": "0.34.1", "agentica_commit": "abc123",
                                "agentica_binary_sha256": hashlib.sha256(b"binary").hexdigest(),
                                "agentica_override": True, "agentica_src_override": False})
        self.assertEqual((unused["agentica_version"], unused["agentica_binary_sha256"]), (None, None))


class TaskFaultTests(unittest.TestCase):
    """Each fault of the t22 start, put back into the Python reference one at a time, fails a hidden case: the cases
    see every fault the task asks to fix."""

    FAULTS = {
        "201 answered as 200": ("self.send_json(201, order(", "self.send_json(200, order("),
        "a quantity of 0": ('whole(body.get("quantity"), 1)', 'whole(body.get("quantity"), 0)'),
        "a decimal accepted": ("return type(value) is int and value >= least",
                               "return isinstance(value, (int, float)) and not isinstance(value, bool) "
                               "and value >= least"),
        "SQL built from text": ('db.execute("select id from customers where name = ?", (body["customer"],))',
                                "db.execute(f\"select id from customers where name = '{body['customer']}'\")"),
        "totals without the quantity": ("sum(row[3] * row[4] for row in rows)", "sum(row[4] for row in rows)"),
        "the report by name": ("order by total desc, c.name", "order by c.name"),
    }

    def failing_cases(self, source: str) -> list[str]:
        task = run.TASKS / "t22-orders-api"
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "solution.py"
            program.write_text(source, encoding="utf-8")
            failing = []
            for case in sorted((task / "hidden").glob("*.in")):
                done = subprocess.run([sys.executable, "-I", str(task / "hidden" / "driver.py"),
                                       case.read_text(encoding="utf-8"), sys.executable, "-I", str(program)],
                                      capture_output=True, text=True, timeout=120)
                if done.stdout != case.with_suffix(".out").read_text(encoding="utf-8"):
                    failing.append(case.stem)
        return failing

    def test_every_fault_of_the_t22_start_fails_a_case(self) -> None:
        reference = (run.TASKS / "t22-orders-api" / "reference.py").read_text(encoding="utf-8")
        self.assertEqual(self.failing_cases(reference), [])
        for fault, (right, wrong) in self.FAULTS.items():
            with self.subTest(fault=fault):
                self.assertEqual(reference.count(right), 1)
                self.assertNotEqual(self.failing_cases(reference.replace(right, wrong)), [])


class FanoutFaultTests(unittest.TestCase):
    """Each fault put into the t25 Python reference fails the cases meant to see it, and the reference passes them."""

    FAULTS = {
        "no hedge": ("fetch.py", "if job.hedge_ms > 0:", "if False:", ["05", "hyg-03"]),
        "the loser not cancelled": ("fetch.py", "        for request in requests:\n            request.cancel()",
                                    "        pass", ["hyg-03"]),
        "no deadline": ("fetch.py", "await asyncio.wait(tasks, timeout=max(0.0, ends_at - time.monotonic()))",
                        "await asyncio.wait(tasks)", ["06", "hyg-02"]),
        "one at a time": ("fetch.py", "asyncio.Semaphore(job.concurrency)", "asyncio.Semaphore(1)", ["hyg-01"]),
        "4xx retried": ("fetch.py", "not 500 <= answer[0] <= 599", "answer[0] == 200", ["02"]),
        "a boolean value": ("fetch.py", "type(value) is not int", "not isinstance(value, int)", ["adv-05"]),
        "a boolean field": ("job.py", "type(value) is not int", "not isinstance(value, int)", ["adv-03"]),
    }

    def failing_cases(self, tree: Path, names: list[str]) -> list[str]:
        hidden = run.TASKS / "t25-fanout-deadlines" / "hidden"
        failing = []
        for name in names:
            case = hidden / f"{name}.in"
            done = subprocess.run([sys.executable, "-I", str(hidden / "driver.py"), case.read_text(encoding="utf-8"),
                                   sys.executable, "-s", "-E", str(tree / "solution.py")],
                                  capture_output=True, text=True, timeout=120)
            if done.stdout != case.with_suffix(".out").read_text(encoding="utf-8"):
                failing.append(name)
        return failing

    def test_every_fault_fails_its_cases(self) -> None:
        reference = run.TASKS / "t25-fanout-deadlines" / "reference" / "py"
        targets = sorted({name for *_, names in self.FAULTS.values() for name in names})
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory) / "tree"
            shutil.copytree(reference, tree)
            self.assertEqual(self.failing_cases(tree, targets), [])
            for fault, (module, right, wrong, names) in self.FAULTS.items():
                with self.subTest(fault=fault):
                    source = (reference / "fetcher" / module).read_text(encoding="utf-8")
                    self.assertEqual(source.count(right), 1)
                    (tree / "fetcher" / module).write_text(source.replace(right, wrong), encoding="utf-8")
                    self.assertEqual(self.failing_cases(tree, names), names)
                    (tree / "fetcher" / module).write_text(source, encoding="utf-8")


class PrepareTests(unittest.TestCase):
    def test_grammar_arm_writes_the_whole_specification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dist" / "runtime").mkdir(parents=True)
            (root / "examples").mkdir()
            shutil.copytree(real_sources() / "docs" / "grammar", root / "docs" / "grammar")
            shutil.copytree(real_sources() / "site" / "content" / "library", root / "site" / "content" / "library")
            task = root / "tasks" / "sample"
            task.mkdir(parents=True)
            (task / "task.md").write_text("Sample task.\n", encoding="utf-8")
            work = root / "work"
            with patch.object(run, "ROOT", root), patch.object(run, "RUNTIME", root / "dist" / "runtime"), patch.object(run, "TASKS", root / "tasks"):
                run.prepare(work, "sample", "grammar")

            grammar = (work / "docs" / "grammar.md").read_text(encoding="utf-8")
            markers = ("# Agentica", "\n## 1. What we want", "\n## 4. Lexical", "\n## 7. Diagnostics",
                       "\n## 8. Examples", "\n### Programs that must be rejected")
            positions = [grammar.find(marker) for marker in markers]
            self.assertTrue(all(position >= 0 for position in positions), positions)
            self.assertEqual(positions, sorted(positions))
            self.assertNotIn("](../", grammar)
            self.assertNotIn("site/content", grammar)
            self.assertNotIn("[agentica-link-", grammar)
            self.assertIn("](library/data-structures/list.md)", grammar)
            self.assertTrue((work / "docs" / "library" / "data-structures" / "list.md").is_file())
            library = work / "docs" / "library"
            self.assertIn("[List](list.md)", (library / "data-structures" / "lazy.md").read_text(encoding="utf-8"))
            for page in library.rglob("*.md"):
                self.assertNotIn("](/", page.read_text(encoding="utf-8"), page)

    def test_grammar_arm_prompt_names_agentica_help(self) -> None:
        self.assertIn("agentica help NAME", run.prompt(Path("/tmp/work"), "grammar"))

    def test_typed_python_prompt_names_the_checker_and_forbids_silencing_it(self) -> None:
        text = run.prompt(Path("/tmp/work"), "typed-python")

        self.assertIn("mypy --strict solution.py", text)
        self.assertIn("# type: ignore", text)
        self.assertNotIn("mypy", run.prompt(Path("/tmp/work"), "python"))

    def test_typed_arm_gets_the_typed_start_and_no_agentica_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dist" / "runtime" / "bin").mkdir(parents=True)
            (root / "dist" / "runtime" / "bin" / "agentica").write_text("binary")
            task = root / "tasks" / "sample"
            task.mkdir(parents=True)
            (task / "task.md").write_text("Sample task.\n", encoding="utf-8")
            (task / "start.py").write_text("untyped\n", encoding="utf-8")
            (task / "start.typed.py").write_text("typed\n", encoding="utf-8")
            (task / "start.agc").write_text("agentica\n", encoding="utf-8")
            (task / "start.go").write_text("go\n", encoding="utf-8")
            with (patch.object(run, "ROOT", root), patch.object(run, "RUNTIME", root / "dist" / "runtime"),
                  patch.object(run, "TASKS", root / "tasks"), patch.object(run, "GO_LANGUAGE", "1.27")):
                for arm, start, runtime in (("typed-python", "typed\n", False), ("python", "untyped\n", False),
                                            ("binary", "agentica\n", True), ("go", "go\n", False)):
                    work = root / f"work-{arm}"
                    run.prepare(work, "sample", arm)
                    ext = run.ARMS[arm]
                    with self.subTest(arm=arm):
                        self.assertEqual((work / f"start.{ext}").read_text(encoding="utf-8"), start)
                        self.assertEqual((work / "bin" / "agentica").exists(), runtime)
                        self.assertFalse((work / "start.typed.py").exists())
                        self.assertEqual((work / "go.mod").exists(), arm == "go")
            self.assertEqual((root / "work-go" / "go.mod").read_text(encoding="utf-8"), "module solution\n\ngo 1.27\n")

    def test_the_go_version_comes_from_the_image(self) -> None:
        with patch.object(run, "GO_LANGUAGE", None), patch.object(run, "probe", return_value=(0, "go1.27.4\n", "")):
            self.assertEqual(run.ensure_go("custom:1"), "go1.27.4")
            self.assertEqual(run.go_mod(), "module solution\n\ngo 1.27\n")
        with (patch.object(run, "GO_LANGUAGE", None), patch.object(run, "probe", return_value=(0, "devel x\n", "")),
              self.assertRaises(SystemExit)):
            run.ensure_go("custom:1")

    def test_go_files_come_as_a_reference_and_a_start_where_python_has_one(self) -> None:
        for task in sorted(run.TASKS.iterdir()):
            if not (task / "reference.go").is_file():
                continue
            with self.subTest(task=task.name):
                self.assertEqual((task / "start.go").is_file(), (task / "start.py").is_file())

    def test_a_round_where_every_task_is_skipped_stops_with_a_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "t10").mkdir()
            with (patch("sys.argv", ["run.py", "--agent", "reference", "--arms", "go", "--tasks", "t10"]),
                  patch.object(run, "TASKS", Path(directory)), contextlib.redirect_stdout(io.StringIO()),
                  self.assertRaises(SystemExit) as raised):
                run.main()
        self.assertIn("nothing to run", str(raised.exception))

    def test_an_ecosystem_task_brings_its_packages_to_each_arm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "tasks" / "shop"
            task.mkdir(parents=True)
            (task / "task.md").write_text("Shop.\n", encoding="utf-8")
            (task / "start.agc").write_text('import Bond from "pkg/bond/bond"\n', encoding="utf-8")
            deps = root / "deps"
            (deps / "bond").mkdir(parents=True)
            (deps / "bond" / "bond.agc").write_text("# bond\n", encoding="utf-8")
            (root / "docs" / "agentica-db").mkdir(parents=True)
            (root / "docs" / "agentica-db" / "_index.md").write_text("# db\n", encoding="utf-8")
            runtime = root / "runtime"
            (runtime / "bin").mkdir(parents=True)
            with (patch.object(run, "TASKS", root / "tasks"), patch.object(run, "RUNTIME", runtime),
                  patch.object(run, "ECOSYSTEM_DEPS", deps), patch.object(run, "GO_LANGUAGE", "1.27")):
                for arm in ("binary", "go", "python"):
                    run.prepare(root / arm, "shop", arm)
                prompts = {arm: run.prompt(root / arm, arm) for arm in ("binary", "go", "python")}
            files = {arm: sorted(path.name for path in (root / arm).iterdir()) for arm in ("binary", "go", "python")}
            go_mod = (root / "go" / "go.mod").read_text(encoding="utf-8")
            installed = (root / "binary" / "deps" / "bond" / "bond.agc").is_file()
            documented = (root / "binary" / "docs" / "agentica-db" / "_index.md").is_file()

        self.assertTrue(documented)
        self.assertEqual(files, {"binary": ["agentica.lock", "agentica.toml", "bin", "deps", "docs", "start.agc",
                                            "task.md"],
                                 "go": ["go.mod", "go.sum", "task.md"], "python": ["task.md"]})
        self.assertTrue(installed)
        self.assertIn("go 1.27\n", go_mod)
        self.assertIn("require modernc.org/sqlite v", go_mod)
        self.assertIn("agentica-lang.com/bond/0.15.1/llms.txt", prompts["binary"])
        self.assertIn("docs/agentica-db/", prompts["binary"])
        self.assertNotIn("agentica-lang.com/llms.txt", prompts["binary"])
        self.assertIn("modernc.org/sqlite", prompts["go"])
        self.assertNotIn("llms.txt", prompts["python"] + prompts["go"])

    def test_the_ecosystem_packages_are_installed_from_the_lock_on_every_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agentica = root / "runtime" / "bin" / "agentica"
            agentica.parent.mkdir(parents=True)
            agentica.write_text("#!/bin/sh\n[ -f agentica.lock ] && mkdir -p deps/bond && echo run >> ../installs\n",
                                encoding="utf-8")
            agentica.chmod(0o755)
            docs = root / "db-docs"
            (docs / "site" / "content").mkdir(parents=True)
            (docs / "site" / "content" / "_index.md").write_text("# db\n", encoding="utf-8")
            fetched = []
            cache = root / "cache"
            with (patch.object(run, "CACHE", cache), patch.object(run, "RUNTIME", root / "runtime"),
                  patch.object(run, "ECOSYSTEM_DEPS", None),
                  patch.object(run, "fetch_sources", lambda commit, *rest: fetched.append(commit) or docs)):
                first = run.ecosystem_deps()
                second = run.ecosystem_deps()
            installs = (cache / "installs").read_text(encoding="utf-8")
            copied = (first.parent / "docs" / "agentica-db" / "_index.md").is_file()
            binary_sha = run.sha256_of(agentica)

        lock = (run.ECOSYSTEM / "agentica.lock").read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertEqual(first.parent.name, f"ecosystem-{run.sha256_of(run.ECOSYSTEM / 'agentica.lock')[:12]}-"
                                            f"{binary_sha[:12]}")
        self.assertEqual(installs, "run\nrun\n")
        self.assertTrue(copied)
        self.assertEqual(len(set(fetched)), 1)
        self.assertIn(f'commit = "{fetched[0]}"', lock.split('name = "db"')[1].split("[[package]]")[0])

    def test_the_tasks_available_in_go(self) -> None:
        # Each part of the Go arm adds its tasks here.
        available = sorted((task.name for task in run.TASKS.iterdir() if (task / "reference.go").is_file()),
                           key=lambda name: int(name[1:].split("-")[0]))
        self.assertEqual(available, ["t1-stats", "t2-fix-types", "t3-struct-change", "t4-word-count",
                                     "t5-scope-return", "t6-json-catalog", "t7-json-stream", "t8-enum-ledger",
                                     "t9-inventory-orders", "t10-calc-extend", "t11-gradebook",
                                     "t12-member-ids", "t13-transfer-variant", "t14-price-lookup",
                                     "t15-robust-ledger", "t16-robust-csv", "t17-quote-client",
                                     "t18-stats-server", "t19-orders-report", "t20-big-log",
                                     "t21-notes-api", "t22-orders-api",
                                     "t23-todo-priority"])

    def test_a_go_note_is_added_to_the_task_of_the_go_arm_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "tasks" / "sample"
            task.mkdir(parents=True)
            (task / "task.md").write_text("Sample task.\n", encoding="utf-8")
            (task / "task.go.md").write_text("In Go, return `(int, bool)`.\n", encoding="utf-8")
            with patch.object(run, "TASKS", root / "tasks"), patch.object(run, "GO_LANGUAGE", "1.27"):
                run.prepare(root / "work-go", "sample", "go")
                run.prepare(root / "work-py", "sample", "typed-python")
            go_task = (root / "work-go" / "task.md").read_text(encoding="utf-8")
            python_task = (root / "work-py" / "task.md").read_text(encoding="utf-8")

        self.assertEqual(go_task, "Sample task.\n\nIn Go, return `(int, bool)`.\n")
        self.assertEqual(python_task, "Sample task.\n")

    def test_a_task_without_go_files_is_skipped_by_the_go_arm_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tasks = Path(directory)
            for name in ("t1", "t2", "t3"):
                (tasks / name).mkdir()
            (tasks / "t1" / "reference.go").write_text("package main\n")
            (tasks / "t3" / "reference.go").write_text("package main\n")
            with patch.object(run, "TASKS", tasks), contextlib.redirect_stdout(io.StringIO()) as printed:
                limited = run.limit_go_tasks(["python", "go"], ["t1", "t2", "t3"], {"python": ["t2"]})
                untouched = run.limit_go_tasks(["python"], ["t1", "t2"], {})

        self.assertEqual(limited, {"python": ["t2"], "go": ["t1", "t3"]})
        self.assertEqual(untouched, {})
        self.assertIn("not available in Go yet (no reference.go), skipped: t2", printed.getvalue())
        self.assertEqual(run.run_order(["t1", "t2", "t3"], ["python", "go"], limited, 1),
                         [("t1", "go", 1), ("t2", "python", 1), ("t3", "go", 1)])

    def test_go_prompt_names_both_checkers_in_file_mode_and_the_go_arm_is_opt_in(self) -> None:
        text = run.prompt(Path("/tmp/work"), "go")

        self.assertIn("`go vet solution.go` and `go build solution.go`", text)
        self.assertIn("standard library only", text)
        self.assertNotIn("go", run.DEFAULT_ARMS)
        self.assertIn("go", run.REFERENCE_ARMS)

    def test_missing_typed_start_falls_back_and_a_task_without_a_start_gets_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / "tasks"
            for name in ("plain", "nostart"):
                (tasks / name).mkdir(parents=True)
                (tasks / name / "task.md").write_text("Sample task.\n", encoding="utf-8")
            (tasks / "plain" / "start.py").write_text("untyped\n", encoding="utf-8")
            with patch.object(run, "ROOT", root), patch.object(run, "RUNTIME", root / "dist" / "runtime"), patch.object(run, "TASKS", tasks):
                self.assertEqual(run.start_file("plain", "typed-python"), tasks / "plain" / "start.py")
                run.prepare(root / "work-plain", "plain", "typed-python")
                run.prepare(root / "work-nostart", "nostart", "typed-python")
            self.assertEqual((root / "work-plain" / "start.py").read_text(encoding="utf-8"), "untyped\n")
            self.assertFalse((root / "work-nostart" / "start.py").exists())
            self.assertNotIn("starting program", run.prompt(root / "work-nostart", "typed-python"))


class NoCliArmTests(unittest.TestCase):
    def fake_runtime(self, root: Path) -> None:
        shutil.copytree(real_skill(), root / ".agents" / "skills" / "agentica-programming")
        binary = root / "dist" / "runtime" / "bin" / "agentica"
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\necho "real $*"\nexit 3\n')
        binary.chmod(0o755)
        task = root / "tasks" / "sample"
        task.mkdir(parents=True)
        (task / "task.md").write_text("Sample task.\n", encoding="utf-8")

    def prepare_in(self, root: Path, *arms: str) -> None:
        """Prepare work-ARM for each arm in a fake root with a fake runtime."""
        self.fake_runtime(root)
        with patch.object(run, "ROOT", root), patch.object(run, "RUNTIME", root / "dist" / "runtime"), patch.object(run, "TASKS", root / "tasks"):
            for arm in arms:
                run.prepare(root / f"work-{arm}", "sample", arm)

    def test_the_agent_gets_a_skill_without_the_query_commands_and_the_repository_skill_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_in(root, "skill-nocli", "skill")
            skill = root / "work-skill-nocli" / "skills" / "agentica-programming"

            self.assertFalse((skill / "references" / "queries.md").exists())
            self.assertFalse((skill / "references" / "analysis.md").exists())
            self.assertTrue((skill / "SKILL.md").is_file())
            for path in skill.rglob("*.md"):
                self.assertIsNone(run.QUERY_MENTION.search(path.read_text(encoding="utf-8")), path)
            self.assertTrue((real_skill() / "references" / "queries.md").is_file())
            self.assertTrue((root / "work-skill" / "skills" / "agentica-programming" / "references" / "queries.md").is_file())
            self.assertIn("Use the agentica-programming skill.", run.prompt(root / "work-skill-nocli", "skill-nocli"))

    def test_a_skill_that_still_names_the_commands_stops_the_arm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "skill"
            shutil.copytree(real_skill(), skill)
            (skill / "references" / "files.md").write_text("Try `agentica refs NAME`.\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                run.strip_query_docs(skill)

        self.assertIn("files.md", str(raised.exception))

    def test_the_wrapper_refuses_the_four_commands_and_passes_the_rest_to_the_real_binary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_in(root, "skill-nocli")
            wrapper = str(root / "work-skill-nocli" / "bin" / "agentica")

            def call(*words: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run([wrapper, *words], capture_output=True, text=True)

            for words in (("outline", "a.agc"), ("type-at", "a.agc:1:1"), ("--json", "symbol", "x"), ("refs", "x", "."),
                          ("--ai", "--json", "refs", "x")):
                with self.subTest(words=words):
                    done = call(*words)
                    self.assertEqual(done.returncode, 2)
                    self.assertIn("not available", done.stderr)
                    self.assertEqual(done.stdout, "")
            for words in (("--max-steps", "5", "outline", "a.agc"), ("--seed", "3", "--json", "refs", "X"),
                          ("--flush-timeout", "10", "--schedulers", "2", "symbol", "X"),
                          ("--steps", "s.agc", "refs", "X"), ("--", "type-at", "a.agc:1:1")):
                with self.subTest(words=words):
                    self.assertEqual(call(*words).returncode, 2)
            for words in (("check", "a.agc"), ("a.agc", "outline"), ("help", "outline"), ("--help",),
                          ("--seed", "5", "a.agc"), ("run", "--", "a.agcb", "refs")):
                with self.subTest(words=words):
                    done = call(*words)
                    self.assertEqual((done.returncode, done.stdout), (3, "real " + " ".join(words) + "\n"))
            self.assertEqual(run.refused_queries(root / "work-skill-nocli"), 10)
            self.assertEqual(run.refused_queries(root / "work-skill"), 0)


def bash_events(call: str, command: str, output: str) -> list[str]:
    return [
        json.dumps({"type": "tool_execution_start", "toolCallId": call, "toolName": "bash",
                    "args": {"command": command}}),
        json.dumps({"type": "tool_execution_end", "toolCallId": call, "toolName": "bash",
                    "result": {"content": [{"type": "text", "text": output}]}}),
    ]


LEGACY_KEYS = ("interpreter_runs", "failing_runs", "check_runs", "check_failures", "outside_reads", "net_commands",
               "query_runs", "read_runs")


def legacy_pi_metrics(out: str) -> dict[str, int]:
    """The call counters of pi_metrics before the call list (commit e31975ee9), the model of the differential test."""
    m = dict.fromkeys(LEGACY_KEYS, 0)
    pending: dict[str, str] = {}
    for line in out.splitlines():
        event = json.loads(line)
        kind = event.get("type")
        if kind == "tool_execution_start":
            command = event.get("args", {}).get("command", "")
            m["outside_reads"] += str(run.EVAL) in json.dumps(event.get("args", {}))
            m["net_commands"] += run.is_net_command(command)
            if event.get("toolName") == "bash":
                m["query_runs"] += run.is_query_command(command)
                m["read_runs"] += run.is_read_command(command)
            elif event.get("toolName") == "read":
                m["read_runs"] += 1
            if event.get("toolName") == "bash" and ("agentica" in command or "python" in command or run.runs_mypy(command)):
                m["interpreter_runs"] += 1
                m["check_runs"] += run.is_check_command(command)
                pending[event["toolCallId"]] = command
        elif kind == "tool_execution_end" and event.get("toolCallId") in pending:
            command = pending.pop(event["toolCallId"])
            if run.command_failed(command, json.dumps(event.get("result", {}))):
                m["failing_runs"] += 1
                m["check_failures"] += run.is_check_command(command)
    return m


class MetricsTests(unittest.TestCase):
    def test_checker_runs_count_as_check_runs_and_failures_as_repairs(self) -> None:
        mypy_error = "solution.py:3: error: Incompatible types in assignment  [assignment]\nFound 1 error in 1 file"
        events = (bash_events("1", "mypy --strict solution.py", mypy_error)
                  + bash_events("2", "mypy --strict solution.py", "Success: no issues found in 1 source file")
                  + bash_events("3", "python3 solution.py < in.txt", "Traceback (most recent call last):\nValueError")
                  + bash_events("4", "agentica check solution.agc", "solution.agc:1:1 error[CHECK-UNKNOWN-NAME]")
                  + bash_events("5", "python3 solution.py", "ok")
                  + bash_events("6", "cat task.md", "error: not a check"))

        metrics = run.pi_metrics("\n".join(events))

        self.assertEqual(metrics["interpreter_runs"], 5)
        self.assertEqual(metrics["check_runs"], 3)
        self.assertEqual(metrics["check_failures"], 2)
        self.assertEqual(metrics["failing_runs"], 3)

    def test_mypy_error_text_is_not_a_failure_for_other_commands(self) -> None:
        self.assertFalse(run.command_failed("python3 solution.py", "x.py:1: error: not from mypy"))
        self.assertTrue(run.command_failed("mypy --strict solution.py && python3 solution.py", "a.py:1: error: bad"))
        self.assertFalse(run.command_failed("pip install mypy", "x.py:1: error: not from mypy"))

    def test_only_running_the_checker_is_a_check_run(self) -> None:
        for command in ("mypy --strict solution.py", "python3 -m mypy solution.py", "cd /workspace && mypy solution.py",
                        "mypy solution.py | tail -3", "agentica check solution.agc", "./bin/agentica check x.agc",
                        "timeout 60 mypy --strict solution.py", "time mypy solution.py", "env MYPYPATH=. mypy solution.py"):
            with self.subTest(command=command):
                self.assertTrue(run.is_check_command(command))
        for command in ("pip install mypy", "cat solution.py", "grep mypy notes.txt", "python3 solution.py",
                        "python3 -c 'print(1); mypy x'"):
            with self.subTest(command=command):
                self.assertFalse(run.is_check_command(command))
        metrics = run.pi_metrics("\n".join(bash_events("1", "pip install mypy", "Successfully installed mypy")))
        self.assertEqual((metrics["interpreter_runs"], metrics["check_runs"], metrics["net_commands"]), (0, 0, 1))

    def test_network_commands_ignore_loopback_curl_and_urllib(self) -> None:
        for command in ("curl https://example.com/x", "wget x", "git clone x", "pip install requests", "npm install x",
                        "apt-get install x", "python3 -c 'import urllib.request'", "curl localhost:1 && pip install x",
                        "curl https://x.com && curl localhost:1"):
            with self.subTest(command=command):
                self.assertTrue(run.is_net_command(command))
        for command in ("curl -s http://localhost:8080/stats", "curl 127.0.0.1:9", "cat adapter.py", "python3 solution.py",
                        "curl localhost:1 && curl 127.0.0.1:2",
                        "python3 -c 'import urllib.request as u; u.urlopen(\"http://127.0.0.1:80\")'"):
            with self.subTest(command=command):
                self.assertFalse(run.is_net_command(command))

    def test_pi_usage_gives_the_context_tokens_and_the_cost_split(self) -> None:
        def message_end(role: str, usage: dict) -> str:
            return json.dumps({"type": "message_end", "message": {"role": role, "usage": usage}})

        def usage(input: int, cache_read: int, cache_write: int, output: int, cost: tuple[float, ...]) -> dict:
            names = ("input", "cacheRead", "cacheWrite", "output", "total")
            return {"input": input, "cacheRead": cache_read, "cacheWrite": cache_write, "output": output,
                    "cost": dict(zip(names, cost))}

        events = [message_end("assistant", usage(100, 400, 50, 10, (0.5, 0.25, 0.125, 1.0, 1.875))),
                  message_end("user", usage(7, 7, 7, 7, (9.0, 9.0, 9.0, 9.0, 9.0))),
                  message_end("assistant", usage(20, 480, 0, 5, (0.25, 0.25, 0.0, 0.5, 1.0)))]

        metrics = run.pi_metrics("\n".join(events))

        self.assertEqual((metrics["tokens_in"], metrics["tokens_cached"], metrics["tokens_cache_write"],
                          metrics["tokens_out"], metrics["turns"]), (120, 880, 50, 15, 2))
        self.assertEqual((metrics["cost_input"], metrics["cost_cache"], metrics["cost_output"], metrics["cost"]),
                         (0.75, 0.625, 1.5, 2.875))

    def test_claude_metrics_have_the_check_counters(self) -> None:
        metrics = run.claude_metrics(json.dumps({"usage": {"input_tokens": 3, "output_tokens": 4}, "num_turns": 2}))

        self.assertEqual((metrics["check_runs"], metrics["check_failures"], metrics["turns"]), (0, 0, 2))
        self.assertEqual((metrics["query_runs"], metrics["read_runs"]), (0, 0))

    def test_query_calls_are_counted_next_to_file_reads_and_checks(self) -> None:
        queries = ("agentica outline a.agc", "agentica --json type-at a.agc:3:5", "dist/agentica symbol Item",
                   "./bin/agentica refs Item src", "agentica --max-steps 5 outline a.agc",
                   "agentica --seed 1 --flush-timeout 5 --schedulers 2 --json refs X", "agentica -- symbol X",
                   "agentica --dump --steps s.agc outline a.agc", "agentica --dump-ir type-at a.agc:1:1",
                   "cd /workspace && /workspace/bin/agentica refs Item",
                   "printf x | agentica outline --stdin a.agc", "agentica-real outline a.agc", "time agentica symbol X")
        others = ("agentica check a.agc", "agentica help outline", "agentica a.agc outline", "rg outline a.agc",
                  "agentica outlines", "echo agentica outline")
        events: list[str] = []
        for number, command in enumerate((*queries, *others, "cat a.agc", "agentica check a.agc | head -5",
                                          "rg -n Item . | head", "head -3 a.agc && sed -n 1,5p a.agc")):
            events += bash_events(str(number), command, "ok")
        events.append(json.dumps({"type": "tool_execution_start", "toolCallId": "r", "toolName": "read",
                                  "args": {"path": "a.agc"}}))

        metrics = run.pi_metrics("\n".join(events))

        self.assertEqual(metrics["query_runs"], len(queries))
        # cat; `rg ... | head` (the filter after the pipe is no read of its own); `head && sed` (one call); the
        # read tool; `rg outline` among the others
        self.assertEqual(metrics["read_runs"], 5)
        self.assertEqual(metrics["check_runs"], 2)

    def test_a_fix_round_is_a_failed_call_then_an_edit_before_the_next_check(self) -> None:
        error = "solution.py:3: error: Incompatible types  [assignment]"
        events = (bash_events("1", "mypy --strict solution.py", error)
                  + [json.dumps({"type": "tool_execution_start", "toolCallId": "e1", "toolName": "edit",
                                 "args": {"path": "solution.py"}})]
                  + bash_events("2", "mypy --strict solution.py", error)
                  + bash_events("3", "mypy --strict solution.py", error)
                  + bash_events("4", "cat > solution.py <<'EOF'\nx = 1\nEOF\nmypy --strict solution.py", "Success")
                  + bash_events("5", "go build solution.go", "./solution.go:4:2: undefined: x")
                  + [json.dumps({"type": "tool_execution_start", "toolCallId": "w1", "toolName": "write",
                                 "args": {"path": "solution.go"}})]
                  + bash_events("6", "python3 solution.py", "Traceback (most recent call last):"))

        metrics = run.pi_metrics("\n".join(events))

        # 1 then the edit: a round; 2 then 3 with no edit between: not one; 3 then the heredoc: a round;
        # 5 then the write: a round; 6 is never edited: not one
        self.assertEqual((metrics["failing_runs"], metrics["check_failures"], metrics["fix_rounds"]), (5, 4, 3))
        for command in ("echo x > solution.agc", "tee -a solution.go < x", "sed -i 's/a/b/' solution.py",
                        "cp /tmp/x.py solution.py", "cd w && cat >> ./solution.py",
                        "python3 -c \"open('solution.py', 'w').write(x)\""):
            with self.subTest(command=command):
                self.assertTrue(run.writes_solution(command))
        for command in ("cat solution.py", "cp solution.py backup.py", "python3 solution.py > out.txt",
                        "diff solution.py start.py", "python3 solution.py > solution.py.out",
                        "python3 -c \"open('solution.py').read()\""):
            with self.subTest(command=command):
                self.assertFalse(run.writes_solution(command))

    def test_only_a_successful_edit_of_the_solution_ends_a_round(self) -> None:
        def edit(call: str, path: str, error: bool) -> list[str]:
            return [json.dumps({"type": "tool_execution_start", "toolCallId": call, "toolName": "edit",
                                "args": {"path": path}}),
                    json.dumps({"type": "tool_execution_end", "toolCallId": call, "isError": error,
                                "result": {"content": [{"type": "text", "text": "ok"}]}})]

        failing = bash_events("1", "python3 solution.py", "Traceback (most recent call last):")
        events = (failing + edit("e1", "notes.md", False) + edit("e2", "/workspace/solution.py", True)
                  + bash_events("2", "python3 solution.py", "Traceback (most recent call last):")
                  + edit("e3", "/workspace/solution.py", False))

        self.assertEqual(run.pi_metrics("\n".join(events))["fix_rounds"], 1)

    def test_a_path_that_names_a_program_is_no_run(self) -> None:
        diagnostics = "error[CHECK-UNKNOWN-NAME] in the examples"
        for command in ("sed -n 1,80p skills/agentica-programming/references/diagnostics.md",
                        "ls /workspace/skills/agentica-programming", "cat python_notes.txt", "rg mypy ."):
            with self.subTest(command=command):
                metrics = run.pi_metrics("\n".join(bash_events("1", command, diagnostics)))
                self.assertEqual((metrics["interpreter_runs"], metrics["failing_runs"]), (0, 0))
        for command in ("python3.13 solution.py", "./bin/agentica solution.agc", "go run solution.go",
                        "cd w && env X=1 python solution.py"):
            with self.subTest(command=command):
                self.assertTrue(run.runs_program(command))

    def test_calls_that_share_an_id_or_have_none_keep_their_own_results(self) -> None:
        traceback = "Traceback (most recent call last):"
        events = (bash_events("", "python3 solution.py", traceback) + bash_events("", "python3 solution.py", "ok")
                  + bash_events("same", "mypy solution.py", "a.py:1: error: x") + bash_events("same", "cat a", "x"))
        overlapping = [json.loads(line) for line in bash_events("x", "python3 a.py", traceback)
                       + bash_events("x", "python3 b.py", "ok")]
        events += [json.dumps(event) for event in (overlapping[0], overlapping[2], overlapping[1], overlapping[3])]

        metrics = run.pi_metrics("\n".join(events))

        self.assertEqual((metrics["interpreter_runs"], metrics["check_runs"], metrics["failing_runs"],
                          metrics["read_runs"]), (5, 1, 3, 1))

    def test_unique_ids_give_the_counts_of_the_runner_before_the_call_list(self) -> None:
        # No command names a program outside the call position: the old runner counted any command that holds
        # "agentica" or "python" (`cat skills/agentica-programming/SKILL.md`) as a run.
        commands = ["python3 solution.py", "mypy --strict solution.py", "agentica check s.agc", "agentica s.agc",
                    "cat task.md", "curl https://x.y", "agentica outline s.agc", "cat /etc/hosts", "rg x . | head",
                    "cd /workspace && printf '1' | agentica s.agc", "timeout 5 python3 -m mypy s.py",
                    "for f in a b; do python3 s.py < $f; done", "if true; then agentica s.agc; else python3 s.py; fi",
                    "! agentica check s.agc", "{ python3 s.py; }", "(cd w && python3 s.py)", "out=$(python3 s.py)",
                    "`python3 s.py`", "bash -c 'cd w && python3 s.py'", 'sh -lc "agentica check \\"s.agc\\""',
                    "env -i X=1 python3 s.py", "/usr/bin/env python3 s.py", "timeout -s KILL 5 agentica s.agc",
                    "time -p python3 s.py", "nohup python3 s.py", "echo in | xargs -n 1 python3 s.py",
                    "uv run python s.py", "uv run mypy --strict s.py", "go env GOPATH", "go mod tidy"]
        outputs = ["ok", "Traceback (most recent call last):\nValueError", "a.py:1: error: bad", "error[CHECK-X]",
                   "SyntaxError: x", "plain"]
        rng = random.Random(1843)
        for trial in range(200):
            events: list[str] = []
            for number in range(rng.randrange(1, 12)):
                if rng.random() < 0.1:
                    events.append(json.dumps({"type": "tool_execution_start", "toolCallId": f"r{number}",
                                              "toolName": "read", "args": {"path": "a"}}))
                else:
                    events += bash_events(f"c{number}", rng.choice(commands), rng.choice(outputs))
            with self.subTest(trial=trial):
                new = run.pi_metrics("\n".join(events))
                self.assertEqual({key: new[key] for key in LEGACY_KEYS}, legacy_pi_metrics("\n".join(events)))

    def test_a_go_vet_and_a_go_build_next_to_each_other_in_either_order_are_one_check(self) -> None:
        vet_error = "# command-line-arguments\nvet: ./solution.go:3:5: undefined: x"
        build_error = "# command-line-arguments\n./solution.go:3:5: undefined: x"
        vet, build = "go vet solution.go", "go build solution.go"
        # (interpreter_runs, check_runs, check_failures, failing_runs)
        rows = {
            "both pass": ([(vet, "ok"), (build, "")], (1, 1, 0, 0)),
            "build first": ([(build, ""), (vet, "")], (1, 1, 0, 0)),
            "one command": ([(f"{vet} && {build}", vet_error)], (1, 1, 1, 1)),
            "vet fails": ([(vet, vet_error), (build, build_error)], (1, 1, 1, 1)),
            "build fails": ([(vet, ""), (build, build_error)], (1, 1, 1, 1)),
            "build first fails": ([(build, build_error), (vet, vet_error)], (1, 1, 1, 1)),
            "vet fails after build": ([(build, ""), (vet, vet_error)], (1, 1, 1, 1)),
            "two vets": ([(vet, ""), (vet, "")], (2, 2, 0, 0)),
            "edit between": ([(vet, vet_error), ("sed -i s/x/y/ solution.go", ""), (build, build_error)],
                             (2, 2, 2, 2)),
        }
        for name, (calls, expected) in rows.items():
            events = [line for number, (command, output) in enumerate(calls)
                      for line in bash_events(str(number), command, output)]
            metrics = run.pi_metrics("\n".join(events))
            with self.subTest(name=name):
                self.assertEqual((metrics["interpreter_runs"], metrics["check_runs"], metrics["check_failures"],
                                  metrics["failing_runs"]), expected)

    def test_a_built_program_is_a_run_and_its_panic_a_failing_run(self) -> None:
        events = (bash_events("1", "go build -o /tmp/s solution.go", "")
                  + bash_events("2", "echo 3 | /tmp/s", "panic: runtime error: index out of range")
                  + bash_events("3", "go -C /workspace build solution.go", "")
                  + bash_events("4", "./solution < in.txt", "6")
                  + bash_events("5", "./other", "panic: x"))
        metrics = run.pi_metrics("\n".join(events))

        self.assertEqual((metrics["interpreter_runs"], metrics["failing_runs"], metrics["check_runs"]), (4, 1, 2))

    def test_go_downloads_are_net_commands(self) -> None:
        for command in ("go get golang.org/x/text", "go install example.com/x@latest", "go mod download",
                        "GOPROXY=https://proxy.golang.org go build", "go -C w get x", "go mod tidy",
                        "go -C w mod tidy", "go run example.com/tool@v1.2.0 x", "go run example.com/tool@latest"):
            with self.subTest(command=command):
                self.assertTrue(run.is_net_command(command))
        self.assertFalse(run.is_net_command("go build solution.go"))

    def test_only_the_go_run_and_check_subcommands_are_runs(self) -> None:
        for command in ("go vet solution.go", "go build solution.go", "go run solution.go", "go test ./...",
                        "bash -c 'go run solution.go'"):
            with self.subTest(command=command):
                self.assertTrue(run.runs_program(command))
        for command in ("go env GOPATH", "go mod tidy", "go version", "cat go.mod"):
            with self.subTest(command=command):
                self.assertFalse(run.runs_program(command))

    def test_go_vet_and_go_build_are_checks_and_their_errors_failures(self) -> None:
        for command in ("go vet ./...", "go build -o app solution.go", "cd w && go vet solution.go"):
            with self.subTest(command=command):
                self.assertTrue(run.is_check_command(command))
        self.assertFalse(run.is_check_command("go run solution.go"))
        self.assertTrue(run.command_failed("go build solution.go", "./solution.go:4:2: undefined: x"))
        self.assertTrue(run.command_failed("go run solution.go", "panic: runtime error: index out of range"))
        self.assertFalse(run.command_failed("go vet solution.go", ""))
        self.assertFalse(run.command_failed("cat x.go", "./solution.go:4:2: undefined: x"))
        self.assertTrue(run.command_failed("go test ./...", "    solution_test.go:12: got 3, want 4\n--- FAIL: TestX"))
        self.assertTrue(run.command_failed("go test ./...", "--- FAIL: TestX (0.00s)"))
        self.assertTrue(run.command_failed("go vet solution.go", "# command-line-arguments\n"
                                           "vet: ./solution.go:11:9: invalid operation: mismatched types"))
        self.assertFalse(run.command_failed("go build ./...", "# example.com/solution"))

    def test_spend_is_pis_cost_or_the_list_price_of_the_tokens(self) -> None:
        model = "opencode-go/deepseek-v4.1-flash"
        tokens = {"tokens_in": 1_000_000, "tokens_cached": 2_000_000, "tokens_cache_write": 0, "tokens_out": 1_000_000}
        self.assertEqual(run.spend({"model": model, "cost": 0.5, **tokens}), {"cost_source": "agent"})
        table = run.spend({"model": model, "cost": 0.0, **tokens})
        self.assertEqual(table["cost_source"], "table")
        self.assertAlmostEqual(table["cost"], 0.15 + 2 * 0.003 + 0.6)
        self.assertAlmostEqual(table["cost_input"] + table["cost_cache"] + table["cost_output"], table["cost"])
        self.assertEqual(run.spend({"model": "other/m", "cost": 0.0, **tokens}), {"cost": 0.0, "cost_source": "none"})
        self.assertEqual(run.spend({"model": model, "cost": 0.0})["cost_source"], "none")


class AgentTimeoutTests(unittest.TestCase):
    def test_a_timed_out_agent_keeps_its_transcript_and_the_spend_of_its_finished_turns(self) -> None:
        turn = json.dumps({"type": "message_end", "message": {"role": "assistant", "usage": {
            "input": 1000, "output": 200, "cost": {"total": 0.01, "input": 0.004, "output": 0.006}}}})
        agent = ["sh", "-c", f"printf '%s\\n' '{turn}'; exec sleep 30"]
        args = Namespace(agent="pi", model="opencode-go/deepseek-v4.1-flash", timeout=2, sandbox="docker",
                         pass_env=[], image="unused", pi_auth=None, chroot_root=None)
        passing = {"status": "pass", "passed": 6, "total": 6, "failure": None, "code": None}
        with (tempfile.TemporaryDirectory() as tmp,
              patch.object(run, "agent_command", return_value=agent),
              patch.object(run, "docker_prefix", return_value=[]),
              patch.object(run, "remove_container"),
              patch.object(run, "grade", return_value=passing)):
            results, scratch = Path(tmp) / "results", Path(tmp) / "scratch"
            results.mkdir()
            scratch.mkdir()
            row = run.one_run(args, results, scratch, "t1-stats", "typed-python", 1)
            transcript = (results / "t1-stats-typed-python-1" / "agent.jsonl").read_text(encoding="utf-8")
            saved = json.loads((results / "results.jsonl").read_text(encoding="utf-8"))
        self.assertTrue(row["agent_timeout"])
        self.assertEqual((row["status"], row["failure"], row["passed"]), ("timeout", "agent-timeout", 6))
        self.assertEqual((row["cost"], row["cost_source"], row["turns"]), (0.01, "agent-partial", 1))
        self.assertIn('"message_end"', transcript)
        self.assertEqual(saved, row)


class TreeTaskTests(unittest.TestCase):
    def test_a_tree_solution_is_the_source_files_outside_the_tool_folders_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name in ("solution.py", "lib/money.py", "tests/test_money.py", "skills/x/tool.py", "bin/run.py",
                         "deps/pkg/a.py", ".hidden/b.py", "notes.md", "solution.agc"):
                (work / name).parent.mkdir(parents=True, exist_ok=True)
                (work / name).write_text("", encoding="utf-8")
            (work / "linked.py").symlink_to(work / "solution.py")
            (work / "linked-dir").symlink_to(work / "lib")
            self.assertEqual(run.solution_files(work, "py"), [Path("solution.py"), Path("lib/money.py")])

    def test_a_tree_too_big_or_unreadable_fails_before_any_case_runs(self) -> None:
        args = Namespace(sandbox="docker", image=run.DEFAULT_IMAGE, chroot_root=None)
        with tempfile.TemporaryDirectory() as directory, patch.object(run, "TASKS", Path(directory) / "tasks"):
            root = Path(directory)
            (root / "tasks" / "tree" / "reference").mkdir(parents=True)
            (root / "tasks" / "tree" / "hidden").mkdir()
            (root / "tasks" / "tree" / "hidden" / "01.in").write_text("", encoding="utf-8")
            outcomes = {}
            for name, files in (("many", {f"lib/m{i:03}.py": "" for i in range(run.TREE_LIMIT)}),
                                ("large", {"lib/big.py": "#" * (run.TREE_FILE_LIMIT + 1)}),
                                ("unreadable", {"lib/secret.py": ""})):
                work = root / name
                for relative, text in {"solution.py": "", **files}.items():
                    (work / relative).parent.mkdir(parents=True, exist_ok=True)
                    (work / relative).write_text(text, encoding="utf-8")
                if name == "unreadable":
                    (work / "lib" / "secret.py").chmod(0)
                scratch = root / f"{name}-scratch"
                scratch.mkdir()
                with patch.object(run, "contained_run", side_effect=AssertionError("no case may run")):
                    row = run.grade(work / "solution.py", "tree", "python", args, scratch, name)
                outcomes[name] = (row["status"], row["failure"], row["code"], row["total"])
            (root / "unreadable" / "lib" / "secret.py").chmod(0o600)
        self.assertEqual(outcomes, {"many": ("fail", "size", "too-many-files", 1),
                                    "large": ("fail", "size", "too-large", 1),
                                    "unreadable": ("fail", "copy", None, 1)})

    def test_a_tree_runs_python_with_its_folder_on_the_path_and_go_from_a_hidden_binary(self) -> None:
        self.assertEqual(run.case_invocation("py", None, "x", tree=True), (["python3", "-s", "-E", "solution.py"], "x"))
        self.assertEqual(run.case_invocation("py", "d", "x", tree=True),
                         (["python3", "-I", "-", "x", "python3", "-s", "-E", "/workspace/solution.py"], "d"))
        self.assertEqual(run.case_invocation("go", None, "x", tree=True), (["/workspace/.solution-bin"], "x"))

    def test_a_crash_is_a_crash_marker_and_a_non_zero_exit_or_a_driver(self) -> None:
        self.assertEqual([run.crashed("runtime", 1, False), run.crashed("runtime", 0, False),
                          run.crashed("runtime", 0, True), run.crashed("logic", 1, False),
                          run.crashed("runtime", None, False)], [True, False, True, False, False])

    def test_a_missing_start_tree_stops_with_its_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(run, "TASKS", Path(directory) / "tasks"):
            (Path(directory) / "tasks" / "tree" / "reference").mkdir(parents=True)
            (Path(directory) / "tasks" / "tree" / "start" / "go").mkdir(parents=True)
            with self.assertRaisesRegex(SystemExit, r"tree: no start tree for typed-python \(start/py/\)"):
                run.start_outcome(Namespace(), Path(directory), "tree", "typed-python")

    def test_a_task_agent_timeout_only_raises_the_rounds_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(run, "TASKS", Path(directory)):
            (Path(directory) / "big").mkdir()
            (Path(directory) / "big" / "agent_timeout").write_text("2400\n", encoding="utf-8")
            (Path(directory) / "small").mkdir()
            self.assertEqual((run.agent_timeout("big", 600), run.agent_timeout("big", 3000)), (2400, 3000))
            self.assertEqual(run.agent_timeout("small", 600), 600)

    def test_spec_runs_and_edits_of_any_source_file_count_in_a_tree_task(self) -> None:
        calls = [run.Call("bash", {"command": "cd /workspace && agentica test tests/"}, "error[CHECK-TYPE-MISMATCH]"),
                 run.Call("edit", {"path": "tests/money_test.agc"}),
                 run.Call("edit", {"path": "lib/money.agc"}),
                 run.Call("bash", {"command": "python3 -m unittest discover"}, "OK"),
                 run.Call("bash", {"command": "go test ./..."}, "ok"),
                 run.Call("bash", {"command": "agentica solution.agc"}, "ok")]
        more = [run.Call("bash", {"command": "pytest -q"}), run.Call("bash", {"command": "python3 tests/test_money.py"}),
                run.Call("bash", {"command": "agentica tests/money_test.agc"})]
        self.assertEqual(run.call_metrics(calls + more, tree=True)["spec_runs"], 6)
        # An edit of a test file is no fix; a shell write of a source file is, in a tree task only.
        self.assertEqual(run.call_metrics(calls[:2], tree=True)["fix_rounds"], 0)
        shell = [calls[0], run.Call("bash", {"command": "cat > lib/money.agc <<'EOF'\nx\nEOF"})]
        self.assertEqual((run.call_metrics(shell, tree=True)["fix_rounds"], run.call_metrics(shell)["fix_rounds"]), (1, 0))
        self.assertEqual(run.call_metrics(calls, tree=True)["fix_rounds"], 1)  # lib/money.agc
        self.assertEqual(run.call_metrics(calls)["fix_rounds"], 0)

    def test_the_quality_table_sums_the_new_fields_and_shows_old_rows_as_unknown(self) -> None:
        new = {"status": "pass", "passed": 3, "total": 3, "cost": 0.02, "adversarial_passed": 1,
               "adversarial_total": 2, "crash_cases": 1, "regressions": 0, "hygiene_failed": 0, "spec_runs": 2}
        failed = {**new, "status": "fail", "passed": 1, "crash_cases": 2, "regressions": 1}
        old = {"status": "pass", "passed": 1, "total": 1, "cost": 0.01}
        lines = run.quality_totals({"skill": [new, failed], "python": [new, old]})
        self.assertEqual(lines[2], "| python | 4/4 | - | - | - | - | - | 0.0150 |")
        self.assertEqual(lines[3], "| skill | 4/6 | 2/4 | 3 | 1 | 0 | 4 | 0.0400 |")


class TreeRunTests(unittest.TestCase):
    def test_a_tree_run_starts_from_the_start_tree_and_keeps_every_source_file(self) -> None:
        agent = ["sh", "-c", "mkdir -p lib && echo 'x = 1' > lib/extra.py && cat lib/money.py > solution.py"]
        args = Namespace(agent="pi", model="opencode-go/deepseek-v4.1-flash", timeout=30, sandbox="docker",
                         pass_env=[], image="unused", pi_auth=None, chroot_root=None)
        graded: list[list[Path]] = []

        def fake_grade(solution: Path, task: str, arm: str, *rest: object) -> dict:
            graded.append(run.solution_files(solution.parent, "py"))
            return {"status": "pass", "passed": 1, "total": 1, "failure": None, "code": None}

        with (tempfile.TemporaryDirectory() as tmp,
              patch.object(run, "TASKS", Path(tmp) / "tasks"),
              patch.object(run, "agent_command", return_value=agent),
              patch.object(run, "docker_prefix", return_value=[]),
              patch.object(run, "remove_container"),
              patch.object(run, "grade", fake_grade)):
            task = Path(tmp) / "tasks" / "tree"
            (task / "start" / "py" / "lib").mkdir(parents=True)
            (task / "start" / "py" / "lib" / "money.py").write_text("print(1)\n", encoding="utf-8")
            (task / "reference" / "py").mkdir(parents=True)
            (task / "hidden").mkdir()
            (task / "task.md").write_text("task\n", encoding="utf-8")
            results, scratch = Path(tmp) / "results", Path(tmp) / "scratch"
            results.mkdir()
            scratch.mkdir()
            row = run.one_run(args, results, scratch, "tree", "python", 1)
            kept = sorted(str(path.relative_to(results / "tree-python-1")) for path in
                          (results / "tree-python-1" / "solution").rglob("*.py"))

        self.assertEqual(graded, [[Path("solution.py"), Path("lib/extra.py"), Path("lib/money.py")]])
        self.assertEqual(kept, ["solution/lib/extra.py", "solution/lib/money.py", "solution/solution.py"])
        self.assertEqual((row["status"], row["regressions"], row["crash_cases"]), ("pass", 0, 0))


class StartParityTests(unittest.TestCase):
    def test_a_go_start_that_grades_unlike_the_python_start_fails_the_check(self) -> None:
        outcomes = {("t2", "typed-python"): ("fail", 0, "check"), ("t2", "go"): ("fail", 0, "check"),
                    ("t9", "typed-python"): ("fail", 1, "logic"), ("t9", "go"): ("fail", 0, "runtime")}
        args = Namespace(tasks=["t2", "t9", "t1"], jobs=2)
        with (patch.object(run, "start_outcome", lambda args, scratch, task, arm: outcomes[task, arm]),
              patch.object(Path, "is_file", lambda path: path.parent.name != "t1"),
              contextlib.redirect_stdout(io.StringIO()) as printed):
            code = run.check_starts(args)

        self.assertEqual(code, 1)
        self.assertIn("starts that differ: t9", printed.getvalue())
        self.assertNotIn("t1:", printed.getvalue())


class GoCheckTests(unittest.TestCase):
    def check(self, vet: tuple, build: tuple = ("", "", 0)) -> dict | None:
        steps: list[list[str]] = []

        def step(result: tuple) -> run.Contained:
            return lambda command, stdin, timeout: steps.append(command) or result

        found = run.go_check(step(vet), step(build), 3)
        self.steps = steps
        return found

    # Captured from go 1.27.4 in the image.
    VET_SYNTAX = ("# command-line-arguments\n# [command-line-arguments]\nvet: ./solution.go:6:15: missing ',' before "
                  "newline in argument list (and 1 more errors)\n")
    BUILD_SYNTAX = ("# command-line-arguments\n./solution.go:6:15: syntax error: unexpected newline in argument list; "
                    "possibly missing comma or )\n")
    VET_TYPE = ("# command-line-arguments\n# [command-line-arguments]\nvet: ./solution.go:5:17: cannot use 2 (untyped "
                "int constant) as string value in variable declaration\n")
    BUILD_TYPE = ("# command-line-arguments\n./solution.go:4:2: declared and not used: x\n./solution.go:5:6: declared "
                  "and not used: y\n./solution.go:5:17: cannot use 2 (untyped int constant) as string value in "
                  "variable declaration\n")
    VET_PRINTF = "# command-line-arguments\n./solution.go:9:2: fmt.Printf format %s has arg n of wrong type int\n"

    def test_vet_then_build_and_the_class_and_count_of_a_type_or_syntax_error_come_from_the_build(self) -> None:
        self.assertIsNone(self.check(("", "", 0)))
        self.assertEqual(self.steps, [run.GO_VET, run.GO_BUILD])
        printf = self.check(("", self.VET_PRINTF, 1))
        build = self.check(("", "", 0), ("", self.BUILD_TYPE, 1))
        syntax = self.check(("", self.VET_SYNTAX, 1), ("", self.BUILD_SYNTAX, 1))
        typed = self.check(("", self.VET_TYPE, 1), ("", self.BUILD_TYPE, 1))
        slow = self.check((None, "timeout", None))
        slow_build = self.check(("", "", 0), (None, "timeout", None))

        self.assertEqual(self.steps, [run.GO_VET, run.GO_BUILD])
        self.assertEqual((printf["failure"], printf["code"], printf["check_errors"], printf["build_ok"]),
                         ("check", "vet", 1, True))
        self.assertEqual((build["failure"], build["code"], build["check_errors"]), ("check", "build", 3))
        self.assertEqual((syntax["failure"], syntax["code"], syntax["check_errors"], syntax["build_ok"]),
                         ("syntax", "syntax", 1, False))
        self.assertEqual((typed["failure"], typed["code"], typed["check_errors"]), ("check", "vet", 3))
        self.assertEqual((slow["failure"], slow["code"]), ("check-timeout", "vet"))
        self.assertEqual((slow_build["failure"], slow_build["code"]), ("check-timeout", "build"))

    def test_go_cases_run_the_built_binary(self) -> None:
        self.assertEqual(run.case_invocation("go", None, "1\n"), (["/workspace/solution"], "1\n"))
        self.assertEqual(run.case_invocation("go", "driver", "1\n"),
                         (["python3", "-I", "-", "1\n", "/workspace/solution"], "driver"))
        self.assertEqual(run.classify("panic: index out of range\n", "go"), ("runtime", "panic"))
        self.assertEqual(run.classify("", "go"), ("logic", None))
        self.assertEqual(run.classify("fatal error: all goroutines are asleep - deadlock!\n", "go"),
                         ("runtime", "fatal"))
        self.assertTrue(run.command_failed("./solution", "fatal error: all goroutines are asleep - deadlock!", True))


class CheckerGradingTests(unittest.TestCase):
    def test_classifies_mypy_output(self) -> None:
        self.assertEqual(run.classify_check('solution.py:4: error: Argument 1 has incompatible type "str"  [arg-type]\n'
                                            "Found 1 error in 1 file (checked 1 source file)\n"), ("check", "arg-type"))
        self.assertEqual(run.classify_check("solution.py:2: error: invalid syntax  [syntax]\n"), ("syntax", "SyntaxError"))
        self.assertEqual(run.classify_check("mypy: can't read file 'solution.py': No such file or directory\n"),
                         ("check", "mypy"))
        self.assertEqual(run.classify_check("solution.py:1: error: something odd\n"), ("check", "mypy"))


class CaseCommandTests(unittest.TestCase):
    def test_plain_cases_send_the_case_on_stdin_to_the_solution(self) -> None:
        self.assertEqual(run.case_invocation("py", None, "3\r\n"), (["python3", "-I", "solution.py"], "3\r\n"))
        self.assertEqual(run.case_invocation("agc", None, "x"), (["/workspace/bin/agentica", "solution.agc"], "x"))

    def test_driver_cases_send_the_driver_on_stdin_and_the_case_and_solution_in_argv(self) -> None:
        self.assertEqual(run.case_invocation("py", "print(1)", "a\r\n"),
                         (["python3", "-I", "-", "a\r\n", "python3", "-I", "/workspace/solution.py"], "print(1)"))
        self.assertEqual(run.case_invocation("agc", "print(1)", "a"),
                         (["python3", "-I", "-", "a", "/workspace/bin/agentica", "/workspace/solution.agc"], "print(1)"))

    def test_crlf_case_files_reach_the_command_unchanged(self) -> None:
        seen: list[tuple[list[str], str]] = []

        def fake(args: Namespace, grade_root: Path, work: Path, command: list[str], stdin: str,
                 timeout: int) -> tuple[str | None, str, int | None]:
            seen.append((command, stdin))
            return "ok\n", "", 0

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hidden = root / "tasks" / "sample" / "hidden"
            hidden.mkdir(parents=True)
            (hidden / "01.in").write_bytes(b"a\r\nb\r\n")
            (hidden / "01.out").write_text("ok\n", encoding="utf-8")
            solution = root / "solution.py"
            solution.write_text("pass\n", encoding="utf-8")
            scratch = root / "scratch"
            scratch.mkdir()
            args = Namespace(sandbox="docker", image=run.DEFAULT_IMAGE, chroot_root=None)
            with patch.object(run, "TASKS", root / "tasks"), patch.object(run, "contained_run", fake):
                plain = run.grade(solution, "sample", "python", args, scratch, "plain")
                (hidden / "driver.py").write_text("pass\n", encoding="utf-8")
                driven = run.grade(solution, "sample", "python", args, scratch, "driven")

        self.assertEqual((plain["status"], driven["status"]), ("pass", "pass"))
        self.assertEqual(seen[0], (["python3", "-I", "solution.py"], "a\r\nb\r\n"))
        self.assertEqual(seen[1], (["python3", "-I", "-", "a\r\nb\r\n", "python3", "-I", "/workspace/solution.py"], "pass\n"))

    def test_task_directory_supplies_driver_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hidden = Path(directory) / "tasks" / "sample" / "hidden"
            hidden.mkdir(parents=True)
            with patch.object(run, "TASKS", Path(directory) / "tasks"):
                self.assertIsNone(run.hidden_driver("sample"))
                self.assertEqual(run.case_timeout("sample"), run.CASE_TIMEOUT)
                (hidden / "driver.py").write_text("print('driver')\n", encoding="utf-8")
                (hidden / "timeout").write_text("60\n", encoding="utf-8")
                self.assertEqual(run.hidden_driver("sample"), "print('driver')\n")
                self.assertEqual(run.case_timeout("sample"), 60)

    def test_every_task_has_a_reference_per_language_and_cases(self) -> None:
        for task in sorted(path for path in run.TASKS.iterdir() if path.is_dir()):
            with self.subTest(task=task.name):
                self.assertTrue((task / "task.md").is_file())
                for ext in ("agc", "py"):
                    reference = (task / "reference" / ext / f"solution.{ext}" if run.tree_task(task.name)
                                 else task / f"reference.{ext}")
                    self.assertTrue(reference.is_file(), reference)
                cases = sorted((task / "hidden").glob("*.in"))
                self.assertTrue([case for case in cases if run.case_tier(case) != run.ADVERSARIAL])
                for case in cases:
                    self.assertTrue(case.with_suffix(".out").is_file(), case.name)


class TypedSourceTests(unittest.TestCase):
    def test_silencing_comments_and_escapes_are_counted(self) -> None:
        source = ("from typing import Any, cast\n# mypy: ignore-errors\nx = foo()  # type: ignore[attr-defined]\n"
                  "y = bar()  #type:ignore\nz: Any = cast(int, x)\nAnything = 1\n@no_type_check\nif TYPE_CHECKING:\n    pass\n")

        self.assertEqual(run.type_escapes(source), {"type_ignores": 3, "type_escapes": 5})
        self.assertEqual(run.type_escapes("import sys\nprint(sys.argv)\n"), {"type_ignores": 0, "type_escapes": 0})

    def test_a_checker_timeout_is_its_own_failure(self) -> None:
        result = run.type_check(lambda command, stdin, timeout: (None, "timeout", None), 3)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual((result["failure"], result["passed"], result["total"]), ("check-timeout", 0, 3))


class ImageDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.build = patch.object(run, "build_image").start()
        for name, value in (("require_docker", None), ("image_exists", True), ("python_runs", None),
                            ("image_id", "sha256:abc")):
            patch.object(run, name, return_value=value).start()
        self.addCleanup(patch.stopall)

    def validate(self, image: str = run.DEFAULT_IMAGE, **probes: list) -> dict[str, str | None]:
        for name, results in probes.items():
            patch.object(run, name, side_effect=results).start()
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            result = run.validate_docker(image, typed="checker_probe" in probes, agentica="runtime_probe" in probes)
        self.printed = printed.getvalue()
        return result

    def test_the_default_image_is_rebuilt_only_when_the_checker_is_missing(self) -> None:
        found = (0, "mypy 2.3.1 (compiled: yes)\n", "")
        for code in run.MISSING_COMMAND:
            self.build.reset_mock()
            with self.subTest(code=code):
                result = self.validate(checker_probe=[(code, "", "not found"), found])
                self.assertEqual(self.build.call_count, 1)
                self.assertIn("rebuilding", self.printed)
                self.assertEqual(result, {"checker": "mypy 2.3.1 (compiled: yes)", "go": None, "image_id": "sha256:abc", "pi": None})
        for first in ((1, "", "crash"), (None, "", "timeout")):
            self.build.reset_mock()
            with self.subTest(first=first), self.assertRaises(SystemExit):
                self.validate(checker_probe=[first, found])
            self.assertEqual(self.build.call_count, 0)
        with self.assertRaises(SystemExit) as raised:
            self.validate("custom:1", checker_probe=[(127, "", "not found"), found])
        self.assertEqual(self.build.call_count, 0)
        self.assertIn("Rebuild", str(raised.exception))

    def test_an_image_that_cannot_run_the_agentica_runtime_is_rebuilt_or_refused(self) -> None:
        self.validate(runtime_probe=[(False, "libgc.so.1 missing"), (True, "")])
        self.assertEqual(self.build.call_count, 1)
        self.build.reset_mock()
        with self.assertRaises(SystemExit) as raised:
            self.validate(runtime_probe=[(False, "libgc.so.1 missing"), (False, "libgc.so.1 missing")])
        self.assertEqual(self.build.call_count, 1)
        self.assertIn("Rebuild", str(raised.exception))
        self.build.reset_mock()
        with self.assertRaises(SystemExit):
            self.validate("custom:1", runtime_probe=[(False, "libgc.so.1 missing")])
        self.assertEqual(self.build.call_count, 0)
        probe = patch.object(run, "runtime_probe", side_effect=AssertionError).start()
        with contextlib.redirect_stdout(io.StringIO()):
            run.validate_docker(run.DEFAULT_IMAGE, typed=False, agentica=False)
        probe.assert_not_called()


class ImageBuildTests(unittest.TestCase):
    def test_a_failed_build_exits_with_a_message_instead_of_a_traceback(self) -> None:
        with patch.object(run, "require_docker"), patch.object(run, "image_exists", return_value=False), \
                patch.object(run.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "docker build")):
            with self.assertRaises(SystemExit) as raised:
                run.validate_docker(run.DEFAULT_IMAGE)

        self.assertIn("Docker daemon", str(raised.exception))


PREFLIGHT = {"ok": True, "cost_source": "agent", "tokens": 120, "turns": 1, "cost": 0.0}


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preflights: list = []
        self.preflight = PREFLIGHT

    def main(self, root: Path, argv: list[str], status: str,
             cost: float = 0.0) -> tuple[int, list[tuple[str, list[str], str]], list]:
        calls: list[tuple[str, list[str], str]] = []
        self.tasks_run: list[tuple[str, str]] = []

        def fake_one_run(args: Namespace, results: Path, scratch: Path, task: str, arm: str, rep: int) -> dict:
            calls.append((args.agent, list(args.pass_env), arm))
            self.tasks_run.append((task, arm))
            row = {"task": task, "arm": arm, "status": status, "passed": 1, "total": 1, "failure": None, "code": None,
                   "cost": cost}
            with (results / "results.jsonl").open("a") as handle:
                handle.write(json.dumps(row) + "\n")
            return row

        validated: list = []

        def fake_validate(image: str, typed: bool = False, agentica: bool = False,
                          pi: bool = False, go: bool = False) -> dict[str, str | None]:
            validated.append((image, typed, agentica))
            return {"checker": "mypy 9.9", "go": "go1.27.4" if go else None, "image_id": "sha256:feed",
                    "pi": "1.3.0" if pi else None}

        with (patch.object(run, "ROOT", root), patch.object(run, "RUNTIME", root / "dist" / "runtime"), patch.object(run, "EVAL", root / "eval"),
              patch.object(run, "install_runtime") as build, patch.object(run, "use_sources"),
              patch.object(run, "require_docker"),
              patch.object(run, "validate_docker", fake_validate), patch.object(run, "one_run", fake_one_run),
              patch.object(run, "run_preflight") as preflight,
              patch.dict(os.environ, {"FOO": "bar"}), patch("sys.argv", ["run.py", *argv]),
              contextlib.redirect_stdout(io.StringIO())):
            preflight.side_effect = lambda args: self.preflights.append(args.model) or self.preflight
            code = run.main()
        build.assert_called_once()
        return code, calls, validated

    def result_info(self, root: Path) -> dict:
        (directory,) = (root / "eval" / "results").iterdir()
        return json.loads((directory / "run.json").read_text(encoding="utf-8"))

    def test_check_references_runs_the_reference_arms_without_credentials_and_exits_1_on_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dist" / "runtime" / "bin").mkdir(parents=True, exist_ok=True)
            (root / "dist" / "runtime" / "bin" / "agentica").write_text("binary")
            argv = ["--check-references", "--agent", "pi", "--pass-env", "FOO", "--tasks", "t1-stats", "--image", "custom:1"]

            code, calls, validated = self.main(root, argv, "fail")
            failing = self.result_info(root)
            shutil.rmtree(root / "eval")
            ok_code, _, _ = self.main(root, argv, "pass")
            shutil.rmtree(root / "eval")
            normal_code, normal_calls, normal_validated = self.main(
                root, ["--agent", "pi", "--pass-env", "FOO", "--tasks", "t1-stats"], "pass")
            normal = self.result_info(root)

        self.assertEqual((code, ok_code, normal_code), (1, 0, 0))
        self.assertEqual(calls, [("reference", [], arm) for arm in run.REFERENCE_ARMS])
        self.assertEqual(validated, [("custom:1", True, True)])
        self.assertEqual((failing["agent"], failing["pass_env"], failing["agent_network"], failing["arms"]),
                         ("reference", [], False, run.REFERENCE_ARMS))
        self.assertEqual((failing["checker"], failing["image_id"], failing["image"]), ("mypy 9.9", "sha256:feed", "custom:1"))
        self.assertEqual([arm for _, _, arm in normal_calls], run.DEFAULT_ARMS)
        self.assertNotIn("skill-nocli", run.DEFAULT_ARMS)
        self.assertEqual({(agent, tuple(env)) for agent, env, _ in normal_calls}, {("pi", ("FOO",))})
        self.assertEqual(normal_validated, [(run.DEFAULT_IMAGE, True, True)])
        self.assertEqual((normal["agent_network"], normal["pass_env"]), (True, ["FOO"]))
        self.assertEqual((normal["pi_version"], failing["pi_version"]), ("1.3.0", None))
        self.assertLessEqual({"agentica_version", "agentica_commit", "agentica_binary_sha256", "agentica_override",
                              "agentica_src_override"}, set(normal))


    def runtime_root(self, directory: str) -> Path:
        root = Path(directory)
        (root / "dist" / "runtime" / "bin").mkdir(parents=True, exist_ok=True)
        (root / "dist" / "runtime" / "bin" / "agentica").write_text("binary")
        return root

    def test_pi_auth_is_checked_first_and_run_json_records_only_that_one_was_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.runtime_root(directory)
            auth = root / "pi-auth.json"
            auth.write_text(json.dumps({"opencode-go": {"type": "api_key", "key": "sk-test-0123456789"}}))
            comma = root / "a,b.json"
            comma.write_text("{}")
            for argv in (["--pi-auth", str(root / "missing.json")], ["--pi-auth", str(auth), "--agent", "claude"],
                         ["--pi-auth", str(comma)]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                    with patch("sys.argv", ["run.py", "--tasks", "t1", *argv]):
                        run.main()
                self.assertIn("--pi-auth", str(raised.exception))
            auth.chmod(0o644)
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                code, _, _ = self.main(root, ["--pi-auth", str(auth), "--model", "opencode-go/deepseek-v4.1-flash",
                                              "--tasks", "t1", "--arms", "skill"], "pass")
            text = (next((root / "eval" / "results").iterdir()) / "run.json").read_text(encoding="utf-8")

        self.assertEqual((code, json.loads(text)["pi_auth_file"]), (0, True))
        self.assertNotIn("sk-test", text)
        self.assertNotIn(str(auth), text)

    def test_a_pi_round_runs_the_preflight_first_records_it_and_counts_its_cost(self) -> None:
        self.preflight = dict(PREFLIGHT, cost=0.04)
        with tempfile.TemporaryDirectory() as directory:
            root = self.runtime_root(directory)
            self.main(root, ["--model", "opencode-go/m", "--tasks", "t1", "--arms", "skill", "--max-cost", "1"],
                      "pass", cost=0.5)
            info = self.result_info(root)
            shutil.rmtree(root / "eval")
            self.main(root, ["--no-preflight", "--tasks", "t1", "--arms", "skill"], "pass")
            skipped = self.result_info(root)
            shutil.rmtree(root / "eval")
            self.main(root, ["--check-references", "--tasks", "t1"], "pass")

        self.assertEqual(self.preflights, ["opencode-go/m"])
        self.assertEqual((info["preflight"], info["cost"]), (self.preflight, 0.54))
        self.assertIsNone(skipped["preflight"])

    def test_an_arm_runs_only_on_its_task_subset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.runtime_root(directory)
            self.main(root, ["--tasks", "t1", "t2", "t3", "--arms", "skill", "skill-nocli",
                             "--arm-tasks", "skill-nocli=t2,t3", "--reps", "2"], "pass")
            info = self.result_info(root)

        by_arm = {arm: sorted({task for task, name in self.tasks_run if name == arm}) for arm in ("skill", "skill-nocli")}
        self.assertEqual(by_arm, {"skill": ["t1", "t2", "t3"], "skill-nocli": ["t2", "t3"]})
        self.assertEqual(len(self.tasks_run), 3 * 2 + 2 * 2)
        self.assertEqual(info["arm_tasks"], {"skill-nocli": ["t2", "t3"]})
        self.assertIn("still name", info["arm_notes"]["skill-nocli"])

    def test_a_bad_arm_task_subset_stops_before_any_run(self) -> None:
        for bad in ("skill-nocli=t9", "python=t1", "skill-nocli=", "skill-nocli"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                root = self.runtime_root(directory)
                with self.assertRaises(SystemExit):
                    self.main(root, ["--tasks", "t1", "--arms", "skill", "skill-nocli", "--arm-tasks", bad], "pass")
                self.assertEqual(self.tasks_run, [])

    def test_the_budget_stops_new_runs_and_the_summary_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.runtime_root(directory)
            code, calls, _ = self.main(root, ["--tasks", "t1", "t2", "t3", "t4", "t5", "--arms", "skill", "--max-cost", "0.05"],
                                       "pass", cost=0.02)
            info = self.result_info(root)
            (results,) = (root / "eval" / "results").iterdir()
            summary = (results / "summary.md").read_text(encoding="utf-8")

        # 0.00 + 0.01 fits, 0.02 + 0.02 fits, 0.04 + 0.02 would pass 0.05
        self.assertEqual((code, len(calls)), (0, 2))
        self.assertEqual((info["stopped_for_budget"], info["runs_skipped"], info["cost"], info["max_cost"]),
                         (True, 3, 0.04, 0.05))
        self.assertIn("stopped_for_budget: true (3 runs not started)", summary)
        self.assertIn("cost: $0.0400 (cap $0.05)", summary)

    def test_the_queue_goes_rep_by_rep_and_a_budget_stop_keeps_every_task_and_arm_within_one_rep(self) -> None:
        grid = run.run_order(["t1", "t2"], ["skill", "typed-python"], {"typed-python": ["t2"]}, 2)

        self.assertEqual(grid, [("t1", "skill", 1), ("t2", "skill", 1), ("t2", "typed-python", 1),
                                ("t1", "skill", 2), ("t2", "skill", 2), ("t2", "typed-python", 2)])

        with tempfile.TemporaryDirectory() as directory:
            root = self.runtime_root(directory)
            self.main(root, ["--tasks", "t1", "t2", "--arms", "skill", "typed-python",
                             "--arm-tasks", "typed-python=t2", "--reps", "3", "--max-cost", "0.11"],
                      "pass", cost=0.02)
            (results,) = (root / "eval" / "results").iterdir()
            summary = (results / "summary.md").read_text(encoding="utf-8")

        # 0.08 + 0.02 fits under 0.11, 0.10 + 0.02 does not: five runs over three pairs (typed-python only runs
        # t2): all of rep 1, then rep 2 of the first two pairs.
        started = Counter(self.tasks_run)
        self.assertEqual(self.tasks_run, [("t1", "skill"), ("t2", "skill"), ("t2", "typed-python"),
                                          ("t1", "skill"), ("t2", "skill")])
        self.assertLessEqual(max(started.values()) - min(started.values()), 1)
        self.assertIn("reps completed (of 3): 2: t1/skill, t2/skill", summary)
        self.assertIn("reps completed (of 3): 1: t2/typed-python", summary)

    def test_without_a_cap_every_run_starts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.runtime_root(directory)
            self.main(root, ["--tasks", "t1", "t2", "--arms", "skill"], "pass", cost=5.0)
            info = self.result_info(root)

        self.assertEqual(len(self.tasks_run), 2)
        self.assertEqual((info["stopped_for_budget"], info["runs_skipped"], info["max_cost"]), (False, 0, None))

    def test_runs_in_flight_count_against_the_cap_and_a_failed_run_is_charged_the_estimate(self) -> None:
        budget = run.Budget(1.0, 0.4)

        self.assertEqual([budget.begin(), budget.begin(), budget.begin()], [True, True, False])
        self.assertTrue(budget.stopped)
        self.assertEqual(budget.end(None), (0.4, True))
        self.assertFalse(budget.begin())

    def test_an_outlier_raises_the_estimate_and_runs_without_a_cost_are_charged_it_but_stay_out_of_it(self) -> None:
        budget = run.Budget(1.1, 0.01)
        for _ in range(3):
            self.assertTrue(budget.begin())
            budget.end(0.01)
        self.assertEqual(budget.estimate(), 0.01)
        self.assertTrue(budget.begin())
        budget.end(0.2)
        # The highest cost seen, not the mean (0.0575), is the estimate of the next runs.
        self.assertEqual(budget.estimate(), 0.2)
        # No cost, a cost of 0 (usage missing) or no row at all: charged 0.2 each, and the estimate stays.
        for reported in (None, 0.0, -1.0):
            self.assertTrue(budget.begin())
            _, charged_estimate = budget.end(reported)
            self.assertTrue(charged_estimate)
        self.assertEqual(budget.estimate(), 0.2)
        self.assertAlmostEqual(budget.spent, 0.03 + 0.2 + 3 * 0.2)
        # 0.83 + 0.2 fits under 1.1 only once.
        self.assertEqual([budget.begin(), budget.begin()], [True, False])
        self.assertTrue(budget.stopped)

    def test_a_run_without_a_cost_prints_a_warning_when_there_is_a_cap(self) -> None:
        args = Namespace()
        for cap, warns in ((1.0, True), (None, False)):
            with self.subTest(cap=cap), patch.object(run, "one_run", return_value={"cost": 0.0}):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    run.budgeted_run(args, run.Budget(cap, 0.01), Path("r"), Path("s"), "t1", "skill", 1)
                self.assertEqual("warning: t1-skill-1 reported no cost" in out.getvalue(), warns)


def pi_reply(usage: dict | None = None, stop: str = "stop", error: str = "", text: str = "pong") -> str:
    """A Pi stream in the shape Pi 1.3.0 prints for one answer (recorded from opencode-go, trimmed)."""
    cost = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}
    usage = usage or {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0, "cost": cost}
    message = {"role": "assistant", "content": [{"type": "text", "text": text}] if text else [], "api": "openai-completions",
               "provider": "opencode-go", "model": "deepseek-v4.1-flash", "usage": usage, "stopReason": stop}
    if error:
        message["errorMessage"] = error
    events = [{"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "Reply"}]}},
              {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": text}},
              {"type": "message_end", "message": message}, {"type": "agent_end", "messages": []}]
    return "\n".join(json.dumps(event) for event in events) + "\n"


class PreflightTests(unittest.TestCase):
    MODEL = "opencode-go/deepseek-v4.1-flash"

    def usage(self, total: float) -> dict:
        cost = {"input": total * 0.8, "output": total * 0.2, "cacheRead": 0, "cacheWrite": 0, "total": total}
        return {"input": 1500, "output": 3, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 1503, "cost": cost}

    def test_a_reported_cost_is_the_source(self) -> None:
        result = run.preflight_result(pi_reply(self.usage(0.000227)), "", False, 0, self.MODEL)

        self.assertEqual(result, {"ok": True, "cost_source": "agent", "tokens": 1503, "turns": 1, "cost": 0.000227})

    def test_a_cost_of_0_falls_back_to_the_price_table_or_stops_the_round(self) -> None:
        free = self.usage(0.0)
        self.assertEqual(run.preflight_result(pi_reply(free), "", False, 0, self.MODEL)["cost_source"], "table")
        with self.assertRaises(SystemExit) as raised:
            run.preflight_result(pi_reply(free), "", False, 0, "opencode-go/unpriced")
        self.assertIn("no cost source for opencode-go/unpriced", str(raised.exception))

    def test_the_shapes_pi_wrote_offline_stop_the_round(self) -> None:
        # Recorded from Pi 1.3.0 with the network off and a dummy key: it exits 0 after its retries.
        offline = ('{"type": "message_end", "message": {"role": "assistant", "content": [], "api": '
                   '"openai-completions", "provider": "opencode-go", "model": "deepseek-v4.1-flash", "usage": '
                   '{"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0, "cost": {"input": 0, '
                   '"output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}, "stopReason": "error", "timestamp": '
                   '1794987127524, "errorMessage": "Connection error.", "durationMs": 36, "thinkingLevel": "high"}}')
        unknown = 'Warning: Model "no-such-model" not found for provider "opencode-go". Using custom model id.\n'
        for out, err, message in ((offline, "", "refused the call (auth or model?): Connection error."),
                                  (offline, unknown, "does not know the model")):
            with self.subTest(message=message), self.assertRaises(SystemExit) as raised:
                run.preflight_result(out, err, False, 0, self.MODEL)
            self.assertIn(message, str(raised.exception))

    def test_an_echoed_error_is_cut_to_120_characters(self) -> None:
        long = pi_reply(stop="error", error="401 key sk-" + "x" * 300, text="")
        with self.assertRaises(SystemExit) as raised:
            run.preflight_result(long, "", False, 0, self.MODEL)
        self.assertEqual(len(str(raised.exception).split("(auth or model?): ", 1)[1]), 120)

    def test_an_auth_error_an_unknown_model_or_no_answer_stops_the_round(self) -> None:
        refused = pi_reply(stop="error", error='401: {"type":"error","error":{"message":"Invalid API key"}}', text="")
        unknown = 'Warning: Model "no-such" not found for provider "opencode-go". Using custom model id.\n'
        for out, err, timed_out, returncode, message in (
                (refused, "", False, 0, "refused the call"),
                (pi_reply(self.usage(0.1)), unknown, False, 0, "does not know the model"),
                (pi_reply(self.usage(0.1)), "crash", False, 1, "exited 1"),
                (pi_reply(self.usage(0.1), text=""), "", False, 0, "no answer"),
                ("", "", True, None, "did not answer")):
            with self.subTest(message=message), self.assertRaises(SystemExit) as raised:
                run.preflight_result(out, err, timed_out, returncode, self.MODEL)
            self.assertIn(message, str(raised.exception))


class PiVersionTests(unittest.TestCase):
    def ensure(self, image: str, outcome: tuple[int | None, str, str]) -> str | None:
        with patch.object(run, "probe", return_value=outcome), patch.object(run, "dockerfile_pi_version", return_value="1.3.0"):
            return run.ensure_pi(image)

    def test_the_default_image_must_have_the_pinned_pi_and_another_image_is_only_recorded(self) -> None:
        self.assertEqual(self.ensure(run.DEFAULT_IMAGE, (0, "1.3.0\n", "")), "1.3.0")
        self.assertEqual(self.ensure("custom:1", (0, "pi 1.0.0\n", "")), "1.0.0")
        self.assertIsNone(self.ensure("custom:1", (127, "", "not found")))
        for outcome in ((0, "1.0.0\n", ""), (127, "", "not found")):
            with self.subTest(outcome=outcome), self.assertRaises(SystemExit) as raised:
                self.ensure(run.DEFAULT_IMAGE, outcome)
            self.assertIn("docker rmi", str(raised.exception))

    def test_the_dockerfile_pins_a_pi_version(self) -> None:
        self.assertRegex(run.dockerfile_pi_version() or "", r"^\d+\.\d+\.\d+$")


def summary_of(rows: list[dict]) -> str:
    with tempfile.TemporaryDirectory() as directory:
        results = Path(directory)
        (results / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            run.summarize(results)
        return (results / "summary.md").read_text(encoding="utf-8")


class SummaryTests(unittest.TestCase):
    def test_summary_has_a_check_runs_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory)
            rows = [{"task": "t1", "arm": "typed-python", "status": "pass", "passed": 2, "total": 2, "seconds": 3.0,
                     "failing_runs": 1, "check_runs": 2, "type_escapes": 1, "query_runs": 1, "refused_queries": 1,
                     "read_runs": 4, "failure": None, "code": None},
                    {"task": "t1", "arm": "typed-python", "status": "fail", "passed": 0, "total": 2, "seconds": 5.0,
                     "failing_runs": 3, "check_runs": 4, "type_escapes": 2, "query_runs": 2, "refused_queries": 2,
                     "read_runs": 6, "failure": "check", "code": "arg-type"}]
            (results / "results.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                run.summarize(results)
            summary = (results / "summary.md").read_text(encoding="utf-8")

        self.assertIn("check runs | query runs | refused | read runs | type escapes", summary)
        # no token or cost fields in these rows: the context and the cost split are unknown, not 0
        self.assertIn("| t1 | typed-python | 2 | 1/2 | 50% | 0 | - | - | - | - | - | 4.0 | 2.0 | - | 3.0 | 1.5 | 1.5 | 5.0 | 1.5 | check:arg-type |",
                      summary)
        self.assertIn("stopped_for_budget: false", summary)

    def test_a_task_with_no_main_cases_counts_its_runs_as_whole(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory)
            row = {"task": "t", "arm": "python", "status": "pass", "passed": 0, "total": 0, "seconds": 1.0,
                   "failing_runs": 0, "check_runs": 0, "query_runs": 0, "refused_queries": 0, "read_runs": 0,
                   "failure": None, "code": None}
            (results / "results.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                run.summarize(results)
            self.assertIn("| t | python | 1 | 1/1 | 100% |", (results / "summary.md").read_text(encoding="utf-8"))

    def test_summary_shows_the_context_and_the_cost_split(self) -> None:
        row = {"task": "t1", "arm": "skill", "status": "pass", "passed": 1, "total": 1, "seconds": 1.0,
               "failure": None, "code": None}
        rows = [dict(row, tokens_in=100, tokens_out=10, tokens_cached=400, tokens_cache_write=50,
                     cost_input=0.5, cost_cache=0.25, cost_output=1.0),
                dict(row, tokens_in=300, tokens_out=30, tokens_cached=600, cost_input=1.5, cost_cache=0.75,
                     cost_output=2.0)]
        summary = summary_of(rows)

        self.assertIn("| tokens | context | spend $ | cost in $ | cost cache $ | cost out $ |", summary)
        # tokens: (110 + 330) / 2; context: (550 + 900) / 2, the cache write counted when present
        self.assertIn("| t1 | skill | 2 | 2/2 | 100% | 220 | 725 | - | 1.0000 | 0.5000 | 1.5000 | 1.0 |", summary)

    def test_summary_shows_spend_and_fix_rounds_per_task_and_per_arm(self) -> None:
        row = {"status": "pass", "passed": 1, "total": 1, "seconds": 1.0, "failure": None, "code": None}
        rows = [dict(row, task="t1", arm="skill", cost=0.25, cost_source="agent", fix_rounds=1),
                dict(row, task="t2", arm="skill", cost=0.75, cost_source="table", fix_rounds=2),
                dict(row, task="t1", arm="typed-python", cost=0.5, cost_source="agent", fix_rounds=0, status="fail")]
        summary = summary_of(rows)

        self.assertIn("| t2 | skill | 1 | 1/1 | 100% | 0 | - | 0.7500 | - | - | - | 1.0 | 0.0 | 2.0 |", summary)
        self.assertIn("| typed-python | 1 | 0/1 | 0.5000 | 0.5000 | 0.00 | agent 1 |", summary)
        self.assertIn("| skill | 1 | 1/1 | 0.2500 | 0.2500 | 1.00 | agent 1 |", summary)
        self.assertIn("Totals over the 1 tasks every arm ran:", summary)
        self.assertIn("skill tasks: t1 t2", summary)
        self.assertIn("typed-python tasks: t1", summary)

    def test_go_rows_show_no_type_escapes_and_count_vet_only_failures(self) -> None:
        row = {"status": "fail", "passed": 0, "total": 1, "seconds": 1.0, "failure": "check", "code": "vet"}
        rows = [dict(row, task="t1", arm="go", build_ok=True), dict(row, task="t2", arm="go", build_ok=False),
                dict(row, task="t1", arm="typed-python", type_escapes=2)]
        summary = summary_of(rows)

        self.assertIn("| t1 | go | 1 | 0/1 | 0% | 0 | - | - | - | - | - | 1.0 | 0.0 | - | 0.0 | 0.0 | 0.0 | 0.0 | - |", summary)
        self.assertIn("| t1 | typed-python | 1 | 0/1 | 0% | 0 | - | - | - | - | - | 1.0 | 0.0 | - | 0.0 | 0.0 | 0.0 | 0.0 | 2.0 |", summary)
        self.assertIn("go runs that failed go vet alone (the build passed): 1 of 2", summary)


class DockerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        require_docker_image()

    def test_agent_can_write_workspace_without_host_files_or_unlisted_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "workspace"
            work.mkdir()
            canary = root / "host-secret"
            canary.write_text("host only")
            script = (
                "import json,os; from pathlib import Path; "
                "Path('/workspace/probe.txt').write_text('ok'); "
                f"print(json.dumps([Path({str(canary)!r}).exists(), "
                "os.getenv('PROVIDER_TOKEN'), os.getenv('OTHER_SECRET'), os.geteuid()]))"
            )
            name = f"agentica-test-{uuid.uuid4().hex}"
            with patch.dict(os.environ, {"PROVIDER_TOKEN": "test-token", "OTHER_SECRET": "host-secret"}):
                env = run.child_environment(["PROVIDER_TOKEN"], in_chroot=True, workspace=work)
                command = run.docker_prefix(work, run.DEFAULT_IMAGE, name, network=True, pass_env=["PROVIDER_TOKEN"])
                try:
                    result = subprocess.run(command + ["python3", "-I", "-c", script], env=env,
                                            capture_output=True, text=True, timeout=30, check=True)
                finally:
                    run.remove_container(name)
            self.assertEqual(json.loads(result.stdout), [False, "test-token", None, os.getuid()])
            self.assertEqual((work / "probe.txt").read_text(), "ok")

    def test_pi_reads_the_auth_file_copied_into_its_home_and_the_key_never_reaches_the_log(self) -> None:
        key = "sk-test-0123456789"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "workspace"
            work.mkdir()
            auth = root / "pi-auth.json"
            auth.write_text(json.dumps({"opencode-go": {"type": "api_key", "key": key}}))
            auth.chmod(0o600)
            probe = ["sh", "-c", "cat $HOME/.pi/agent/auth.json; stat -c 'mode %a' $HOME/.pi/agent/auth.json; "
                     "pi --list-models opencode-go"]
            started: list[list[str]] = []
            popen = subprocess.Popen

            def recording_popen(command: list[str], **kwargs: object) -> subprocess.Popen:
                started.append(command)
                return popen(command, **kwargs)

            with (patch.object(run, "agent_command", return_value=probe), patch.object(run, "AGENT_NETWORK", False),
                  patch.object(run.subprocess, "Popen", recording_popen)):
                out, err, timed_out, _ = run.run_agent("pi", work, root, "t1-stats", "skill", None, 60, "docker", [],
                                                    run.DEFAULT_IMAGE, auth)
            unchanged = json.loads(auth.read_text())["opencode-go"]["key"] == key
            left = list(work.iterdir())

        self.assertFalse(timed_out)
        self.assertIn("deepseek-v4.1-flash", out, err)
        self.assertIn("[REDACTED]", out)
        self.assertNotIn(key, out + err)
        self.assertIn("mode 600", out)
        self.assertNotIn(key, " ".join(started[0]))
        self.assertIn(f"type=bind,src={auth},dst={run.PI_AUTH_MOUNT},readonly", started[0])
        self.assertTrue(unchanged)
        self.assertEqual(left, [])

    def test_grader_has_no_secret_network_or_workspace_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            candidate = work / "solution.py"
            candidate.write_text("original")
            script = """import json,os,socket
from pathlib import Path
writable = False
network = False
try:
    Path('/workspace/solution.py').write_text('changed')
    writable = True
except OSError:
    pass
try:
    socket.create_connection(('1.1.1.1', 443), timeout=0.5).close()
    network = True
except OSError:
    pass
print(json.dumps([os.getenv('PROVIDER_TOKEN'), writable, network]))
"""
            name = f"agentica-test-{uuid.uuid4().hex}"
            with patch.dict(os.environ, {"PROVIDER_TOKEN": "host-secret"}):
                command = run.docker_prefix(work, run.DEFAULT_IMAGE, name, network=False, pass_env=[])
                try:
                    result = subprocess.run(command + ["python3", "-I", "-c", script],
                                            env=run.grader_environment(), capture_output=True,
                                            text=True, timeout=30, check=True)
                finally:
                    run.remove_container(name)
            self.assertEqual(json.loads(result.stdout), [None, False, False])
            self.assertEqual(candidate.read_text(), "original")


class DockerGradingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        require_docker_image(checker=True)

    def grade(self, root: Path, name: str, source: str, arm: str = "typed-python") -> dict:
        solution = root / f"solution.{run.ARMS[arm]}"
        solution.write_text(source, encoding="utf-8")
        args = Namespace(sandbox="docker", image=run.DEFAULT_IMAGE, chroot_root=None)
        scratch = root / "scratch"
        scratch.mkdir(exist_ok=True)
        with patch.object(run, "TASKS", root / "tasks"):
            return run.grade(solution, "sample", arm, args, scratch, name)

    def sample_task(self, root: Path, driver: str | None = None, case: bytes = b"3\n", expected: str = "6\n") -> None:
        hidden = root / "tasks" / "sample" / "hidden"
        hidden.mkdir(parents=True)
        (hidden / "01.in").write_bytes(case)
        (hidden / "01.out").write_text(expected, encoding="utf-8")
        if driver is not None:
            (hidden / "driver.py").write_text(driver, encoding="utf-8")

    def test_typed_arm_fails_a_type_error_before_running_any_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample_task(root)
            source = "n: int = 'three'\nprint(6)\n"

            result = self.grade(root, "bad", source)
            untyped = self.grade(root, "bad-untyped", source, arm="python")

        self.assertEqual((result["status"], result["passed"], result["failure"], result["code"]),
                         ("fail", 0, "check", "assignment"))
        self.assertEqual(result["check_errors"], 1)
        self.assertEqual((untyped["status"], untyped["passed"]), ("pass", 1))

    def test_go_arm_vets_builds_offline_and_runs_the_binary(self) -> None:
        if run.go_probe(run.DEFAULT_IMAGE)[0] != 0:
            self.skipTest("evaluation image has no Go")
        run.ensure_go(run.DEFAULT_IMAGE)
        doubled = ('package main\n\nimport (\n\t"bufio"\n\t"fmt"\n\t"os"\n\t"strconv"\n\t"strings"\n)\n\n'
                   'func main() {\n\tline, _ := bufio.NewReader(os.Stdin).ReadString(\'\\n\')\n'
                   '\tn, _ := strconv.Atoi(strings.TrimSpace(line))\n\tfmt.Println(n * 2)\n}\n')
        vet = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Printf("%s\\n", 6)\n}\n'
        unused = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tx := 1\n\tfmt.Println(6)\n}\n'
        # Packages outside the closure of the tasks' imports: the image warms the whole public std.
        wide = ('package main\n\nimport (\n\t"container/heap"\n\t"fmt"\n\t"html"\n\t"io/ioutil"\n\t"os"\n)\n\n'
                'type ints []int\n\nfunc (h ints) Len() int           { return len(h) }\n'
                'func (h ints) Less(i, j int) bool { return h[i] < h[j] }\n'
                'func (h ints) Swap(i, j int)      { h[i], h[j] = h[j], h[i] }\n'
                'func (h *ints) Push(x any)        { *h = append(*h, x.(int)) }\n'
                'func (h *ints) Pop() any          { old := *h; x := old[len(old)-1]; *h = old[:len(old)-1]; return x }\n\n'
                'func main() {\n\tdata, _ := ioutil.ReadAll(os.Stdin)\n\th := &ints{}\n\theap.Push(h, len(data)+4)\n'
                '\tfmt.Println(html.EscapeString(fmt.Sprint(heap.Pop(h))))\n}\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample_task(root)
            results = [self.grade(root, name, source, arm="go")
                       for name, source in (("go-ok", doubled), ("go-vet", vet), ("go-unused", unused),
                                            ("go-wide", wide),
                                            ("go-t2-start", (run.TASKS / "t2-fix-types" / "start.go").read_text()))]

        self.assertEqual([(r["status"], r["passed"], r["failure"], r["code"]) for r in results],
                         [("pass", 1, None, None), ("fail", 0, "check", "vet"), ("fail", 0, "check", "vet"),
                          ("pass", 1, None, None), ("fail", 0, "check", "vet")])
        # go vet stops at the first type error of the t2 start; the build lists all six.
        self.assertEqual(results[-1]["check_errors"], 6)

    def test_a_tree_solution_grades_with_its_modules_and_counts_case_tiers(self) -> None:
        if run.go_probe(run.DEFAULT_IMAGE)[0] != 0:
            self.skipTest("evaluation image has no Go")
        run.ensure_go(run.DEFAULT_IMAGE)
        python = {"solution.py": "import sys\n\nfrom calc.double import double\n\nprint(double(int(sys.stdin.read())))\n",
                  "calc/__init__.py": "",
                  "calc/double.py": "def double(n: int) -> int:\n    return n * 2\n",
                  "skills/ignored.py": "this is not python\n",
                  "tests/test_calc.py": "def check(n):\n    return n\n",
                  "calc/double_test.py": "def check(n):\n    return n  # type: ignore\n"}
        go = {"solution.go": 'package main\n\nimport (\n\t"fmt"\n\t"io"\n\t"os"\n\t"strconv"\n\t"strings"\n\n'
                             '\t"solution/calc"\n)\n\nfunc main() {\n\tdata, _ := io.ReadAll(os.Stdin)\n'
                             '\tn, err := strconv.Atoi(strings.TrimSpace(string(data)))\n\tif err != nil {\n'
                             '\t\tpanic(err)\n\t}\n\tfmt.Println(calc.Double(n))\n}\n',
              "calc/calc.go": "package calc\n\nfunc Double(n int) int { return n * 2 }\n",
              "calc/calc_test.go": 'package calc\n\nimport "fmt"\n\nfunc helper() { fmt.Printf("%d", "x") }\n'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "tasks" / "tree"
            hidden = task / "hidden"
            hidden.mkdir(parents=True)
            (task / "reference").mkdir()
            for name, case, expected in (("01", "3", "6"), ("reg-01", "4", "8"), ("hyg-01", "5", "10"),
                                         ("adv-01", "boom", "error"), ("adv-02", "7", "14")):
                (hidden / f"{name}.in").write_text(case + "\n", encoding="utf-8")
                (hidden / f"{name}.out").write_text(expected + "\n", encoding="utf-8")
            args = Namespace(sandbox="docker", image=run.DEFAULT_IMAGE, chroot_root=None)
            results = {}
            for arm, files in (("typed-python", python), ("python", python), ("go", go),
                               ("typed-python-bad", {**python, "calc/double.py": "def double(n: int) -> str:\n    return n\n"})):
                work = root / arm
                for name, text in files.items():
                    (work / name).parent.mkdir(parents=True, exist_ok=True)
                    (work / name).write_text(text, encoding="utf-8")
                scratch = root / f"{arm}-scratch"
                scratch.mkdir()
                with patch.object(run, "TASKS", root / "tasks"):
                    solution = work / f"solution.{run.ARMS[arm.removesuffix('-bad')]}"
                    results[arm] = run.grade(solution, "tree", arm.removesuffix("-bad"), args, scratch, arm)

        for arm in ("typed-python", "python", "go"):
            with self.subTest(arm=arm):
                row = results[arm]
                self.assertEqual((row["status"], row["passed"], row["total"]), ("pass", 3, 3))
                self.assertEqual((row["adversarial_passed"], row["adversarial_total"], row["crash_cases"]), (1, 2, 1))
                self.assertEqual((row["regressions"], row["hygiene_failed"]), (0, 0))
                self.assertEqual(row["failed_cases"], ["adv-01"])
        # The agent's own tests are not graded (an unannotated test, a vet error in a _test.go file); mypy checks the
        # module that solution.py imports, not only solution.py.
        self.assertEqual((results["typed-python-bad"]["status"], results["typed-python-bad"]["failure"]),
                         ("fail", "check"))

    def test_an_ecosystem_task_builds_with_the_baked_sqlite_module_offline_and_nothing_else(self) -> None:
        if run.go_probe(run.DEFAULT_IMAGE)[0] != 0:
            self.skipTest("evaluation image has no Go")
        run.ensure_go(run.DEFAULT_IMAGE)
        # It prints 6 only when the module cache is read-only and GOPROXY is off where the program runs.
        sqlite = ('package main\n\nimport (\n\t"database/sql"\n\t"fmt"\n\t"os"\n\n\t_ "modernc.org/sqlite"\n)\n\n'
                  'func main() {\n\tdb, _ := sql.Open("sqlite", ":memory:")\n\tvar n int\n'
                  '\tif err := db.QueryRow("select 3 * 2").Scan(&n); err != nil {\n\t\tpanic(err)\n\t}\n'
                  '\tif os.WriteFile("/opt/go-mod/probe", nil, 0o644) == nil || os.Getenv("GOPROXY") != "off" {\n'
                  '\t\tn = -1\n\t}\n\tfmt.Println(n)\n}\n')
        missing = 'package main\n\nimport "golang.org/x/text/language"\n\nfunc main() { println(language.English.String()) }\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample_task(root)
            (root / "tasks" / "sample" / "start.agc").write_text('import Db from "pkg/db/db"\n', encoding="utf-8")
            results = [self.grade(root, name, source, arm="go")
                       for name, source in (("go-sqlite", sqlite), ("go-missing", missing))]

        self.assertEqual([(r["status"], r["failure"], r["code"]) for r in results],
                         [("pass", None, None), ("fail", "check", "vet")])

    def test_typed_arm_passes_a_checked_solution_and_counts_type_ignores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample_task(root)
            source = "import sys\n\nn: int = int(sys.stdin.read())\nprint(n * 2)\n"

            result = self.grade(root, "good", source)

        self.assertEqual((result["status"], result["passed"], result["total"]), ("pass", 1, 1))
        self.assertEqual((result["check_errors"], result["type_ignores"], result["type_escapes"]), (0, 0, 0))

    def test_typed_arm_fails_silencing_comments_even_when_the_checker_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample_task(root)
            results = {}
            for name, header in (("directive", "# mypy: ignore-errors\n"), ("ignore", "")):
                line = "n: int = 'three'" + ("  # type: ignore" if name == "ignore" else "")
                results[name] = self.grade(root, name, f"{header}{line}\nprint(6)\n")
            checker_alone = self.grade(root, "unsilenced", "n: int = 'three'\nprint(6)\n")

        for name in ("directive", "ignore"):
            with self.subTest(name=name):
                self.assertEqual((results[name]["status"], results[name]["passed"], results[name]["failure"],
                                  results[name]["code"]), ("fail", 0, "check", "ignore"))
                self.assertGreaterEqual(results[name]["type_ignores"], 1)
        self.assertEqual(checker_alone["code"], "assignment")
        self.assertEqual(checker_alone["type_ignores"], 0)

    def test_typed_arm_counts_any_and_cast_without_failing_them(self) -> None:
        source = ("import sys\nfrom typing import Any, cast\n\nraw: Any = sys.stdin.read()\n"
                  "text = cast(str, raw)\nprint(int(text) * 2)\n")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample_task(root)

            result = self.grade(root, "escapes", source)

        self.assertEqual((result["status"], result["type_ignores"], result["type_escapes"]), ("pass", 0, 3))

    def test_crlf_case_files_reach_the_solution_and_the_driver_unchanged(self) -> None:
        reads = "import sys\nprint(sys.stdin.buffer.read())\n"
        driver = "import sys\nprint(repr(sys.argv[1]))\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample_task(root, case=b"a\r\nb\r\n", expected="b'a\\r\\nb\\r\\n'\n")
            plain = self.grade(root, "plain", reads, arm="python")
            (root / "tasks" / "sample" / "hidden" / "driver.py").write_text(driver, encoding="utf-8")
            (root / "tasks" / "sample" / "hidden" / "01.out").write_text("'a\\r\\nb\\r\\n'\n", encoding="utf-8")
            driven = self.grade(root, "driven", "pass\n", arm="python")

        self.assertEqual((plain["status"], driven["status"]), ("pass", "pass"), (plain, driven))

    def test_driver_runs_the_solution_next_to_a_loopback_peer_without_network(self) -> None:
        driver = (
            "import socket, subprocess, sys\n"
            "peer = socket.socket()\n"
            "peer.bind(('127.0.0.1', 0))\n"
            "peer.listen(1)\n"
            "child = subprocess.Popen(sys.argv[2:] + [str(peer.getsockname()[1])], stdin=subprocess.PIPE, text=True)\n"
            "child.stdin.write(sys.argv[1])\n"
            "child.stdin.close()\n"
            "connection, _ = peer.accept()\n"
            "print('peer got', connection.recv(100).decode())\n"
            "child.wait()\n"
        )
        source = (
            "import socket, sys\n"
            "n = int(sys.stdin.read())\n"
            "socket.create_connection(('127.0.0.1', int(sys.argv[1]))).sendall(str(n * 2).encode())\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.sample_task(root, driver)
            (root / "tasks" / "sample" / "hidden" / "01.out").write_text("peer got 6\n", encoding="utf-8")

            result = self.grade(root, "peer", source, arm="python")

        self.assertEqual((result["status"], result["passed"]), ("pass", 1), result)


if __name__ == "__main__":
    unittest.main()
