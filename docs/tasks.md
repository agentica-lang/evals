# Tasks

The tasks are in `tasks/`. Each has a `task.md`, a reference solution in
Agentica (`reference.agc`) and in typed Python (`reference.py`), and hidden
cases. The tasks that start from a program have `start.agc` and `start.py` (and
`start.typed.py` when the typed arm needs a different start). A starter program
can hold an intentional bug: when you edit a task, do not repair it and do not
change the hidden cases. `run.py` runs the agents. `diagnostics.py` counts the
diagnostics the agents saw in their logs.

The suite keeps eight tasks (#15): four small ones from the first rounds and
four larger ones (t24 to t27, coming one by one). The removed tasks (t1–t7,
t9–t15, t17, t19, t20, t22, t23) are in git history; the ids are kept, so the
numbers of earlier rounds still name the same tasks.

| Task | Kind | The agent does |
|---|---|---|
| `t8-enum-ledger` | small program | run a ledger of commands with enums and `case` |
| `t16-robust-csv` | error handling | report `line N: problem` for a CSV summary, with five checks in a fixed order |
| `t18-stats-server` | repair an integration | an `std/http` server with wrong JSON, status codes and port line |
| `t21-notes-api` | build on packages | a JSON API for notes on SQLite, from a start that answers `/health` only (see [The ecosystem tasks](#the-ecosystem-tasks)) |

The larger tasks from t25 on (#15) are tree tasks (see [Tree tasks and case
tiers](#tree-tasks-and-case-tiers)): solutions of several files, with
adversarial and hygiene cases. Each targets a strength of Agentica.

| Task | Kind | The agent does |
|---|---|---|
| `t25-fanout-deadlines` | concurrency | fetch URLs with a concurrency limit, request timeouts, hedged requests (the loser cancelled), retries with backoff and a deadline for the whole run |
| `t27-config-language` | many error paths | an interpreter for a small configuration language (lexer, parser, name checker, evaluator, imports with cycle detection) that prints canonical JSON or the first error as a code at file:line:col |

t25's driver is an HTTP backend that follows a script per URL (delays, hangs, a
body a byte at a time, resets, status sequences). Its hygiene cases check the
concurrency limit, that the run ends by the deadline, and that a hedge's loser
is closed before its answer. `agent_timeout` gives it 2400 seconds.

t27's cases are sets of files (`=== PATH` lines start each), which its driver
writes to a folder before it runs the program on `main.conf`: valid programs,
one or more cases per error code, nesting 300 deep, and an adversarial tier of
programs with one to three random edits (seed 27). Its start gives every arm six
of them under `cases/` and a runnable spec (`agentica test`, `unittest`, `go
test`), so `spec runs` shows how often an arm runs it. It also has 2400 seconds.

## The ecosystem tasks

A task whose `start.agc` imports a package (`pkg/...`) is an ecosystem task.
Each arm builds it with the libraries a developer would take:

- Agentica: Bond and agentica-db. `ecosystem/agentica.toml` and
  `ecosystem/agentica.lock` pin their releases (and the `pool` package that
  agentica-db needs) by tag, commit and hash. The runner installs them once with
  the Agentica under test (`agentica install`) into `.cache/` and copies the
  manifest, the lock and `deps/` into the workspace, so neither the agent nor
  the grader fetches anything (`agentica install` runs on every round and checks
  what is there, so a partial `deps/` is never used). The docs are the ones of
  the pinned releases only: the prompt names Bond's versioned
  `https://www.agentica-lang.com/bond/0.15.1/llms.txt`, and agentica-db's site
  pages at the locked commit (it has no versioned `llms.txt`) are fetched with
  the packages and copied into the workspace as `docs/agentica-db/`. Not the
  site's root `llms.txt`: it links a Bond and agentica-db todo-API tutorial,
  which is nearly t21.
- Python: the standard library, `http.server` and `sqlite3`, as
  agentica-lang/agentica#1843 allows; the image has no pip packages for it, and
  the prompt names no docs.
- Go: `net/http` and `database/sql` with `modernc.org/sqlite` (pure Go, no cgo),
  pinned in `ecosystem/go.mod` and `ecosystem/go.sum`. The image downloads it at
  build time into a read-only module cache (`GOMODCACHE=/opt/go-mod`, about 260
  MB) and warms the build cache for it, so a check takes about a second. At run
  time `GOPROXY` stays off: another module does not build. The workspace gets
  that `go.mod` and `go.sum`, and the prompt names the module (no docs: the Go
  arm knows the standard library and `database/sql`).

The agent container has network, as for every task, so the agent can read the
docs; the offline tasks do not need it, and the grading stays offline. An
Agentica arm that reads Bond's docs with `curl` counts in `net_commands` on
these tasks. The hidden driver starts the service on a fresh database file,
sends the requests, runs SQL on the file from outside (so a service that keeps
the notes in memory fails), reads the table, and restarts the service on the
same file. Its SQL does not wait for a lock (`timeout=0`): the task says a
change is committed before its answer, so a service that answers first and
commits after fails a case. A case may take 30 seconds (`hidden/timeout`), as a
restart starts the service again. A `405` shows the status alone, because Bond
answers it in plain text by itself. The agentica-db native SQLite driver needs a
C compiler, which the image does not have, so Agentica runs its FFI driver, with
a warning on stderr.

## Hidden cases

A case is `hidden/NN.in` (standard input) and `hidden/NN.out` (the expected
standard output, compared after trimming the final newlines); the run passes the
case when the output is equal and the exit code is 0. A task directory may add
two optional files, which the integration and big-data tasks use:

- `hidden/driver.py` makes a case a small scenario. The runner starts `python3
  -I -` in the grader container with the driver source on its standard input,
  the content of `NN.in` as its first argument (`sys.argv[1]`, read as bytes and
  decoded as UTF-8, so a CRLF stays CRLF) and the solution command after it
  (`sys.argv[2:]`), and compares what the driver prints. The driver is Python
  standard library only and the independent peer: it runs the solution with an
  absolute path (`/workspace/bin/agentica /workspace/solution.agc`, or `python3
  -I /workspace/solution.py`; for a tree task see below), serves or calls it on
  `127.0.0.1` port 0, creates its fixtures in a temporary directory, and prints
  a transcript. The driver source is never mounted and is read from the standard
  input, so it is in no file and in no `/proc/*/cmdline`; the harness does not
  defend against a solution that reads the memory of its parent process. The
  case content is in the command line, and a plain case gives it to the solution
  as its input anyway. The drivers: t18 starts the solution as a server, reads
  its `listening PORT` line and calls it with `http.client`; t21 does the same
  on a fresh database; t25 and t27 are described with their tasks.
- `hidden/timeout` is the time limit of one case in seconds (the default is 10).

## Tree tasks and case tiers

A tree task's solution spans several files. The task has `reference/<ext>/`
(`agc`, `py`, `go`) instead of `reference.<ext>`, each a whole tree with its
entry point `solution.<ext>`, and may have `start/<ext>/`, a tree the workspace
starts from (the program to change; `--check-starts` needs one per language).

The solution is `solution.<ext>` and every other `.<ext>` file of the workspace.
These are left out, and the prompt says so:

- the reserved folders the harness fills (`bin/`, `skills/`, `deps/`, `docs/`,
  `examples/`), hidden files and folders, and links (also files under a linked
  folder);
- the agent's own tests: `test_*.py`, `test.py`, `tests.py`, `conftest.py`,
  `*_test.py`, `*_test.go`, `*_test.agc`, and anything under a `test/`, `tests/`
  or `specs/` folder;
- any other file (data, `.pyi`, `go:embed`).

More than 200 files, or a file over 1 MiB, fails the run with failure `size`
(code `too-many-files` or `too-large`), and a file the grader cannot read with
failure `copy`, before any case runs. The grader copies the files
(`solution.<ext>` first), and the run keeps them under `solution/`.

- Python runs as `python3 -s -E solution.py` (also under a driver), so it
  imports its own modules. The typed arm runs `mypy --strict
  --explicit-package-bases -- FILES` on the graded files.
- Go is the module `solution`: package main in the root, other packages in
  subfolders (`solution/<folder>`), checked with `go vet ./...` and `go build -o
  .solution-bin .`. A `_test.go` file is not copied, so vet never sees it.
- Agentica imports its files by relative path.
- `fix_rounds` counts an edit of any graded file: an edit tool, or a shell write
  in the forms of single-file tasks (`>`, `tee`, `sed -i`, `cp`/`mv`, `open(...,
  'w')`). An edit of a test file is not one.
- `agent_timeout` in the task folder raises `--timeout` for that task.
- An `ecosystem` file in the task folder makes it an ecosystem task (see [The
  ecosystem tasks](#the-ecosystem-tasks)) without a start that imports a
  package.

A hidden case's name prefix puts it in a tier, in any task:

| prefix | tier | in the status? | counted as |
|---|---|---|---|
| `adv-` | adversarial: malformed input, faults, edge values | no | `adversarial_passed` of `adversarial_total` |
| `reg-` | regression: old behaviour a change must keep | yes | `regressions` (failed cases) |
| `hyg-` | hygiene: shutdown, leaks, exit code | yes | `hygiene_failed` |
| none | main | yes | `passed` of `total` |

`passed` and `total` leave the adversarial cases out; a task needs at least one
other case. `failed_cases` names the cases that failed (of every tier), and
`--check-references` prints them for a reference that fails. A run whose cases
did not run (no file, a failed check, a `size` or `copy` failure) fails every
regression and hygiene case.

`crash_cases` counts the failed cases that crashed rather than gave a wrong
answer: the stderr shows a crash (a traceback, `panic:`, `fatal error:` or
`error[RUNTIME-`), and the program exited non-zero. Under a driver the exit
status is the driver's: a driver passes on the program's stderr and adds a line
`PROGRAM-EXIT CODE` when the program ended on its own (not when the driver
stopped it), and a crash needs such a line with a code other than 0. Every
driver does this.

`spec_runs` counts runs of the agent's own tests: `agentica test`, `python3 -m
unittest`, `pytest` (alone or with `-m`), `go test`, and a test file run
directly (`python3 tests/test_x.py`, `agentica x_test.agc`). It comes from Pi's
transcript, so rows of the claude and reference agents have none (`-`).

`summary.md` adds a table per arm with these, the share of cases passed and the
spend per passing run.
