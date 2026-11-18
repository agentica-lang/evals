# Agent evaluation

Can an agent write and repair Agentica programs? An agent gets one task, and its
program is graded against hidden cases. The runs count passing cases, tokens,
time, and interpreter and checker runs that failed.

This repository holds the tasks, the runner and the results notes. It used to
live in `tests/eval/` of
[agentica-lang/agentica](https://github.com/agentica-lang/agentica), and its
history came along.

The tasks are in `tasks/`. Each has a `task.md`, a reference solution
in Agentica (`reference.agc`) and in typed Python (`reference.py`), and hidden
cases. The tasks that start from a program have `start.agc` and `start.py` (and
`start.typed.py` when the typed arm needs a different start). A starter program
can hold an intentional bug: when you edit a task, do not repair it and do not
change the hidden cases.
`run.py` runs the agents. `diagnostics.py` counts the
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
| `t21-notes-api` | build on packages | a JSON API for notes on SQLite, from a start that answers `/health` only (see "The ecosystem tasks") |

The larger tasks from t25 on (#15) are tree tasks (see "Tree tasks and case
tiers"): solutions of several files, with adversarial and hygiene cases. Each
targets a strength of Agentica.

| Task | Kind | The agent does |
|---|---|---|
| `t25-fanout-deadlines` | concurrency | fetch URLs with a concurrency limit, request timeouts, hedged requests (the loser cancelled), retries with backoff and a deadline for the whole run |

t25's driver is an HTTP backend that follows a script per URL (delays, hangs, a
body a byte at a time, resets, status sequences). Its hygiene cases check the
concurrency limit, that the run ends by the deadline, and that a hedge's loser
is closed before its answer. `agent_timeout` gives it 2400 seconds.

The arms are the context an agent gets:

- `python`: the same task in Python (untyped). The baseline of the first rounds.
- `typed-python`: the same task in Python with type annotations, checked by
  `mypy --strict` (see "The typed Python arm").
- `skill`: the `agentica-programming` skill and the `agentica` binary.
- `skill-nocli`: the `skill` arm without the four query commands
  (`agentica outline`, `type-at`, `symbol`, `refs`), for the measurement of the
  query commands. It is opt-in: `--arms` must name it. See "The no-CLI arm".
- `grammar`: `docs/grammar.md` and `examples/`, without the skill. Its prompt
  gained the `agentica help` pointer (commit efba1a0b), so older grammar-arm
  results are not comparable.
  `agentica help` covers the builtins only, so this arm has no signature source
  for the `std/` modules (`HTTP`, `Queue`, `BDD`).
- `binary`: only the binary, `agentica check`, and a one-line hint. No docs.
- `go`: the same task in Go, standard library only, checked by `go vet` and
  `go build`. It is opt-in: `--arms` must name it. See "The Go arm".

The prompts are not equal, and they stay as they are so that rounds remain
comparable. The `binary` prompt names `agentica check` and `agentica --help`;
the `skill` prompt names only the skill, which teaches `agentica check`; the
`grammar` prompt names `agentica help NAME`; the `typed-python` prompt names
`mypy --strict solution.py`; the `go` prompt names `go vet solution.go` and
`go build solution.go`; the `python` prompt names no checker. Read a
difference between arms with that in mind.

## How to run

Docker is needed. The runner builds its default image the first time it runs.
Pass a provider key by name with `--pass-env`.

```sh
# Check the tasks: every reference solution must pass every hidden case (no model, no credentials)
python3 run.py --check-references

# A model run: 3 reps per task and arm
python3 run.py --agent pi --model fireworks/accounts/fireworks/models/deepseek-v4p1-flash --pass-env FIREWORKS_API_KEY --arms skill typed-python --reps 3 --jobs 4

# The same through OpenCode Go, with the key in a Pi auth file
python3 run.py --agent pi --model opencode-go/deepseek-v4.1-flash --pi-auth .secrets/pi-auth.json --arms skill typed-python --reps 3 --jobs 2 --max-cost 2

# Summarize a finished run, and count the diagnostics the agents saw
python3 run.py --summarize results/<run directory>
python3 diagnostics.py
```

`--tasks` picks tasks (the default is all twenty). `--arms` picks arms (the
default is every arm but the opt-in `skill-nocli` and `go`). `--arm-tasks
ARM=TASK,TASK` limits one arm to some of the tasks (full task names, all in
`--tasks`; repeat the option for another arm). `--max-cost USD` is a soft cap on
the cost of the round (see "The budget cap"). `--sandbox firejail
--chroot-root PATH` is the other sandbox; you prepare its rootfs yourself, and
it needs `mypy` for the typed arm. Docker is the only sandbox tested with the
typed arm, the drivers and the loopback peers; Firejail is untested for them.
The results go to `results/`, which is not versioned. Each run directory has a
`run.json` with the commit, the Agentica version and source commit, the checker
version, the Go version, the Pi version, the model, the arms, and the image
name and ID, next to `results.jsonl` and `summary.md`. The runner has its own
tests: `python3 -m unittest discover -p 'test_*.py'`. CI runs them,
`--check-references` and `--check-starts` on every pull request (no model
calls).

`--check-references` is the same as `--agent reference` with the arms `binary`,
`python`, `typed-python` and `go` (the three Agentica arms share one
reference). It copies each `reference.*` as the solution, grades it like an
agent's, prints the table, and exits 1 when a reference fails. Use it after any
change to a task, the runner, the image or the Agentica version.

`--check-starts` grades each `start.go` and the typed Python start of its task
as solutions, and exits 1 when their status, passed cases or failure kind
differ, so a Go start keeps the bugs of the Python one.

### The Agentica under test

By default a run uses Agentica 0.34.1: the `linux-x86_64` release archive,
downloaded once into `.cache/` and checked against the SHA-256 pinned in
`run.py`, and a sparse checkout of the commit of the `0.34.1` tag for the
skill, the grammar, the library pages and the examples. `.cache/` is not
versioned. Two options replace them:

- `--agentica PATH`: another `agentica` binary built for Linux x86_64, such as
  `dist/agentica` of an agentica checkout.
- `--agentica-src PATH`: an agentica checkout for the skill, `docs/grammar/`,
  `site/content/library/` and `examples/`.

Only a round with an Agentica arm fetches them; a Python-only round needs no
network for them. `run.json` records `agentica_version`, `agentica_commit`,
`agentica_binary_sha256`, and whether `--agentica` or `--agentica-src` replaced
the pins (`agentica_override`, `agentica_src_override`).

To move to a new release, change `AGENTICA_VERSION`, `AGENTICA_ARCHIVE_SHA256`
and `AGENTICA_COMMIT` together and run `--check-references`.

The Docker sandbox works like this:

- Grading runs each hidden case in a fresh container with `--network=none`, no
  provider credentials, and the solution mounted read-only. The container has a
  loopback interface, so a grader can run a server next to the solution (see
  "Hidden cases").
- Agent containers mount only the task workspace, and they can reach the
  provider. They run with `--read-only`, `--cap-drop=ALL` and
  `no-new-privileges`. Credentials come only from `--pass-env` or
  `--pi-auth`.
- `--pi-auth PATH` gives Pi a key in its `auth.json` format, such as
  `{"opencode-go": {"type": "api_key", "key": "..."}}`. The key file lives in
  `.secrets/`, which git ignores; it is never in the image. The
  container gets it read-only at `/run/pi-auth.json` and copies it to
  `~/.pi/agent/auth.json` on its tmpfs, because Pi locks that file in its own
  folder. Its strings of 8 characters or more are redacted from the agent log
  (as written and JSON-escaped; Pi's delta events, which can split a key, are
  dropped from it) and from the copied solution, and `run.json` records only
  `pi_auth_file: true`. Pi 1.3.0 of the image has the `opencode-go` provider
  (`pi --list-models opencode-go`). The agent runs as the same user and can
  read the copy, so use a key made for the eval, with a spend cap, rotate it
  after a round, and put one provider only in the file.
- `TMPDIR` is `/tmp` in every container, because the root file system is
  read-only and the launcher writes its bytecode to the temporary directory. The
  image has `libgc1` and `libssl3t64`, which a `dist/agentica` built with the
  system libraries links; the release binary needs only glibc.
- `--agent claude` needs `--image` with the Claude CLI and Python. The default
  image has Pi only.

If you change `Dockerfile`, remove the old image (`docker rmi
agentica-eval:local`). The runner also rebuilds the default image by itself, and
prints a line saying so, in two cases: `mypy --version` exits 126 or 127 in it
(typed arm), or it cannot run a hello program with the agentica binary
(any Agentica arm). Any other failure of the probes stops the run with a
message, and an image given with `--image` is never rebuilt: the runner stops
and asks you to rebuild it.

### The typed Python arm

The `typed-python` arm is the Python side of the typed-Python comparison. The
agent writes `solution.py` with type annotations and gets `mypy` on its `PATH`,
like the Agentica arms get `agentica check`. The prompt gives the command,
`mypy --strict solution.py`, and says not to silence it with `# type: ignore` or
by weakening its options.

- Checker: mypy 2.3.1 (compiled), run with `--strict`. The version and its five
  dependencies are pinned in `Dockerfile`; `run.json` records the
  version the image reports. mypy is the checker of this arm. It installs
  from PyPI as compiled wheels, with no download at run time; the `pyright`
  package on PyPI fetches its npm package on first use, which the grader (no
  network) cannot do.
- Grading: the grader first runs
  `mypy --strict --cache-dir=/dev/null solution.py` in a fresh container, in the
  same mount and with the same limits as the hidden cases. A solution that fails
  the checker is a failing run with 0 cases passed, like an Agentica program
  that fails `agentica check` and never runs. The row has `failure: check` and
  the first mypy error code (`arg-type`, `assignment`, `return`...) as `code`,
  or `syntax` for a parse error, and `check_errors`, the number of errors. A
  checker that runs for more than 90 seconds is `failure: check-timeout`. A
  passing solution then runs against the hidden cases like any other.
- Silencing the checker fails the run. A solution with a `# type: ignore` or a
  `# mypy:` comment (such as `# mypy: ignore-errors`, which makes
  `mypy --strict` pass) fails before mypy runs, with `failure: check`,
  `code: ignore` and 0 cases passed. The prompt forbids `# type: ignore` and
  weakening the options; it does not name `# mypy:` (the prompt stays as it is
  so that rounds remain comparable), but the grader rejects those comments too.
  Every typed row has `type_ignores`, the number of those comments, so a failing
  row shows it, and `type_escapes`, the number of `Any`, `cast(`,
  `no_type_check` and `TYPE_CHECKING` in the source. `type_escapes` is a
  heuristic text count: words in strings and comments count, and an alias
  (`import typing as t`, `from typing import Any as A`) hides one. Escapes do
  not fail a run, and the checker still runs, but check them before you compare
  the arms: `summary.md` shows their mean in the `type escapes` column.
- Measures: `interpreter_runs` counts every bash call that runs `agentica`,
  `python`, `mypy` or `go vet|build|run|test`; `check_runs` counts the calls
  to `mypy`, `agentica check`, `go vet` and `go build`. A `go vet` and a
  `go build` in calls next to each other, in either order (no edit or other run
  between), are one interpreter run, one check run and one failure at most,
  because the Go check is the two commands where the other arms have one (both
  a lower bound: a
  command is recognised at the start of a shell segment, also after `do`,
  `then`, `else`, `!`, `{`, `(`, `$(` or a backtick, after the `env`, `time`,
  `timeout`, `nohup`, `xargs`, `uv run` and `NAME=value` prefixes, and inside
  `bash -c` or `sh -c`, so a run through another wrapper or a script is not
  counted). A program that a `go build` wrote, run through a path
  (`./solution`, `/tmp/s`), is a run too, and its `panic:` a failure.
  Before 2026-11-18 a call that only named one of them, such as a `sed` of the
  skill's files, also counted, in `interpreter_runs` and, when its output held
  an error line, in `failing_runs`. That inflated the skill arm, so rounds 1–15
  do not compare between arms on those two measures;
  `check_failures` counts those that failed (a mypy `error:` line, an
  `error[...]` diagnostic); `failing_runs` counts every failing call, checks
  included, so repairs are compared with the checker calls on both sides.
  Tokens, turns, cost and seconds are the same as in the Agentica arms.
  `diagnostics.py` still counts Agentica diagnostics only. A `file.go:N:M:` or
  `panic:` line is a failure of a Go call (see "The Go arm"). Only
  `--agent pi` reports calls:
  `--agent claude` gives totals, so its interpreter, check and failing runs
  read 0, which means not measured.
- Starts: `start.py` is typed and passes `mypy --strict`. A task written for
  the untyped arm may have `start.typed.py`, the same program with
  annotations, which the typed arm gets as `start.py`.
- The untyped `python` arm stays for comparison with the early rounds. It is not
  part of the typed-Python pilot. Its workspace has no Agentica binaries.

### The Go arm

The `go` arm writes `solution.go`, one `main` package with the standard library
only (`net/http` for t18). The workspace has a `go.mod` (`module
solution`, the Go version of the image), and `start.go` where the task has a
start. The prompt gives `go run solution.go` and the two checkers,
`go vet solution.go` and `go build solution.go`, and says not to silence them.
A task without a `reference.go` is not available in Go yet: the go arm skips
it and prints a note, and `--check-references` grades go only on the tasks
that have one.

- Toolchain: Go 1.27.4, pinned with its SHA-256 in `Dockerfile`;
  `run.json` records `go env GOVERSION`, and the workspace `go.mod` takes its
  language version from it. The image sets `GOFLAGS=-mod=mod`, `GOPROXY=off`,
  `GOTOOLCHAIN=local` and `CGO_ENABLED=0`, so Go works offline by default; the
  agent container has network, so an agent that sets `GOPROXY` itself can
  still download (`net_commands` counts `go get`, `go install`,
  `go mod download`, `go mod tidy`, `GOPROXY=`, `golang.org` and `pkg@version`
  or `@latest`). The image carries a
  read-only build cache of the whole public standard library (every
  `go list std` package outside `internal`, `vendor` and `cmd`;
  `GOCACHE=/opt/go-cache`, about 160 MB). Go reads a read-only cache but cannot
  add to it, and a package it never indexed is "not in std", so the cache must
  hold them all; a check then takes under a second instead of half a minute.
- Grading: `go vet solution.go`, then `go build -o solution solution.go`, in a
  fresh container with the workspace writable for the binary. A failure is
  `failure: check` with `code` `vet` or `build` (`syntax` for a syntax error)
  and `check_errors`, the number of `file.go:line:` lines. The build always
  runs. `go vet` type-checks first and stops at the first type or syntax error
  (its `vet: ` line; an unused variable is a type error, so its code is `vet`):
  then the class (`syntax error` gives `syntax`) and the count come from
  `go build -gcflags=-e`, so a program with six type errors counts 6, not 1. A vet failure
  records `build_ok`, and `summary.md` counts the go runs that failed vet alone
  (the build passed). The hidden cases then run the binary. A `panic:` is
  `failure: runtime`, code `panic`, and a `fatal error:` (a deadlock) code
  `fatal`. Go rows have no `type_escapes` (`-` in `summary.md`).
- Starts: `start.go` keeps the bugs of `start.py` and has `//go:build ignore`,
  so `go build .` leaves it out. A start gives the output of `start.py` on the
  hidden cases, and `--check-starts` checks that they grade alike.

What is not equal to the other arms:

- The commands name the file (`go vet solution.go`), not the package: the
  workspace also holds `start.go`, which is package `main` too.
- `task.md` names `solution.agc` and `solution.py` only; the prompt names
  `solution.go`. Some tasks ask for an Agentica or Python type: a `Command[T]`
  enum with exhaustive `case` (t8). Go has no sum types or exhaustive switch,
  so the reference uses an interface with a type switch, and nothing checks a
  missing case. A task can add a `task.go.md`, which the go arm gets at the
  end of its `task.md`.
- The task text of t18 names `sys.argv`, `System.args()` and the Python or
  Agentica HTTP modules; the Go prompt adds that these are `os.Args` and
  `net/http`.
- Go is strict where the other checkers are not: an unused variable or import
  is a compile error, so a draft fails more checks. `go vet` also runs analyses
  that are not type checks (`printf` formats, copied locks, unreachable code),
  which mypy and `agentica check` do not have.
- The check is two commands, each with the 90-second checker limit, where the
  other arms have one.
- The arm runs in Docker only. The Firejail sandbox refuses it. For `go run`
  the `/tmp` tmpfs of every container is now mounted `exec` with 256 MB; rounds
  before the Go arm had it `noexec`.
- The image is `linux/amd64` only (the Go archive is), and the Dockerfile needs
  BuildKit (`ADD --checksum`).
- A crash exits 1 in Python and Agentica and 2 in Go (a `panic`). No rule
  depends on it: a case passes only with exit 0 and the expected output, and
  the failure class comes from stderr.
- Known gaps, not fixed: the t18 driver never sends some of the cases the task
  describes, so a Go (or any) server can get them wrong and still pass. t16
  states that salaries and totals fit in 64 bits, as Agentica's `Int` and Go's
  `int` do.

### The ecosystem tasks

A task whose `start.agc` imports a package (`pkg/...`) is an ecosystem task.
Each arm builds it with the libraries a developer would take:

- Agentica: Bond and agentica-db. `ecosystem/agentica.toml` and
  `ecosystem/agentica.lock` pin their releases (and the `pool` package that
  agentica-db needs) by tag, commit and hash. The runner installs them once
  with the Agentica under test (`agentica install`) into `.cache/` and copies
  the manifest, the lock and `deps/` into the workspace, so neither the agent
  nor the grader fetches anything (`agentica install` runs on every round and
  checks what is there, so a partial `deps/` is never used). The docs are the
  ones of the pinned releases only: the prompt names Bond's versioned
  `https://www.agentica-lang.com/bond/0.15.1/llms.txt`, and agentica-db's site
  pages at the locked commit (it has no versioned `llms.txt`) are fetched with
  the packages and copied into the workspace as `docs/agentica-db/`. Not the
  site's root `llms.txt`: it links a Bond and agentica-db todo-API tutorial,
  which is nearly t21.
- Python: the standard library, `http.server` and `sqlite3`, as
  agentica-lang/agentica#1843 allows; the image has no pip packages for it,
  and the prompt names no docs.
- Go: `net/http` and `database/sql` with `modernc.org/sqlite` (pure Go, no
  cgo), pinned in `ecosystem/go.mod` and `ecosystem/go.sum`. The image
  downloads it at build time into a read-only module cache
  (`GOMODCACHE=/opt/go-mod`, about 260 MB) and warms the build cache for it,
  so a check takes about a second. At run time `GOPROXY` stays off: another
  module does not build. The workspace gets that `go.mod` and `go.sum`, and the
  prompt names the module (no docs: the Go arm knows the standard library and
  `database/sql`).

The agent container has network, as for every task, so the agent can read the
docs; the offline tasks do not need it, and the grading stays offline. An
Agentica arm that reads Bond's docs with `curl` counts in `net_commands` on
these tasks. The
hidden driver starts the service on a fresh database file, sends the requests,
runs SQL on the file from outside (so a service that keeps the notes in memory
fails), reads the table, and restarts the service on the same file. Its SQL
does not wait for a lock (`timeout=0`): the task says a change is committed
before its answer, so a service that answers first and commits after fails a
case. A case may take 30 seconds (`hidden/timeout`), as a restart starts the
service again. A `405`
shows the status alone, because Bond answers it in plain text by itself. The
agentica-db native SQLite driver needs a C compiler, which the image does not
have, so Agentica runs its FFI driver, with a warning on stderr.

### Spend and fix rounds

Every row and `summary.md` have two more figures; `summary.md` also totals
them per arm, over the tasks every arm ran (the go arm skips a task without Go
files), and lists the tasks of each arm.

- `cost` (the `spend $` column) is the cost Pi reports, `cost_source: agent`.
  When Pi reports 0 for a run that used tokens, the runner prices the tokens
  with `PRICES` in `run.py` (`cost_source: table`): the opencode-go prices of
  Pi 1.3.0's catalog, the same as
  `https://opencode.ai/inference/go/v1/models` on 2026-11-18. A model
  outside the table gets `cost_source: none` and a cost of 0. Either way it is
  the list price: it does not count OpenCode Go's double price on weekday
  hours (01:00 to 04:00 and 06:00 to 10:00 UTC) or the allowance of the plan.
  `run.json` has `started_utc` for that reason.
- A run whose agent passes `--timeout` has `status: timeout` and
  `failure: agent-timeout`, whatever its file grades (the cases it passes stay
  in `passed`). It keeps the transcript and the cost of the turns Pi finished;
  the request still open when it was killed reports nothing, so its
  `cost_source` ends in `-partial` and the cost is a lower bound.
- `fix_rounds` counts failed check or run calls (the calls of
  `interpreter_runs`) that an edit follows before the next check or run call:
  Pi's `edit` or `write` tool on a `solution.*` file without an error, or a
  shell command that writes `solution.*` in a common form (`>`, a `cat`
  heredoc, `tee`, `sed -i`, `cp` or `mv` onto it, `open(..., 'w')` in a
  `python -c`); a script that writes it is not seen. A failure that another
  call follows first, or that is never edited, is no round. `failing_runs` stays
  the count of every failed call.

`--agent claude` reports no calls, so its `fix rounds` read `-`.

### Query-command counts

For `--agent pi`, every row and `summary.md` count, next to the checks:

- `query_runs`: bash calls that run `agentica outline`, `type-at`, `symbol` or
  `refs`, with or without `--json`, through a path (`dist/agentica`) or after
  `cd x &&`, `time` or a pipe. Like `check_runs`, it is a lower bound (no
  `bash -c`, no script).
- `read_runs`: calls that read files: a shell segment that starts with `cat`,
  `rg`, `sed`, `head`, `grep` or `tail` (a `| head` filter does not count), and
  every call of Pi's `read` tool.
- `refused_queries`: calls the `skill-nocli` wrapper refused (0 in the other
  arms).

`--agent claude` reports 0 for the counts, which means not measured.

### The no-CLI arm

`skill-nocli` is the `skill` arm with two changes, made in the copy the agent
gets (the skill in the repository is never edited):

- The skill copy has no `references/queries.md` and no `references/analysis.md`,
  and none of the lines that point to them: their two table rows in
  `SKILL.md`, and the `QUERY-` codes of `references/diagnostics.md`. The
  runner stops when any file of the copy still names a query command, so a
  change to the skill cannot leak one unnoticed.
- `bin/agentica` is a shell wrapper and the real binary is `bin/agentica-real`.
  The wrapper answers `outline`, `type-at`, `symbol` and `refs` with exit 2 and
  one stderr line (`agentica: 'refs' is not available in this evaluation arm`),
  appends a line to `bin/.refused-queries`, and passes every other command to
  the real binary. The grader uses the real binary, not the wrapper.

What the arm does not hide, and the results must say: `agentica --help` and
`agentica help` still list the four commands (`run.json` has `arm_notes` with
this), and an agent can call `bin/agentica-real` or read the wrapper. A
`query_runs` above `refused_queries` shows such a bypass. A refused call still
costs the agent a turn; read `refused_queries` with that in mind.

The arm ran on the tasks that cross a program (t9, t11 to t14), a change that
follows a type through many uses, where `refs` and `type-at` should help. Those
tasks were removed with the eight-task suite (#15), so the arm has no subset
now.

### The full 6c round

Issue #1009 tracks it: the Agentica `skill` arm against the typed Python arm,
with the same model and budget, and the measurement of `--ai` and labels
against plain text on the `binary` arm.

### The preflight

Before the first task of a `--agent pi` round in Docker, the runner makes one
tiny call in the agent image, with the round's model, mounts, auth and
network: the prompt `Reply with the word pong.` It stops the round before any
task when Pi does not answer, when the provider refuses the key or the model
(Pi exits 0 then, and the error is in the assistant's `message_end`), when Pi
does not know the model, when the answer has no tokens or does not parse, or
when the run has no cost source ("no cost source for MODEL": Pi reports 0 and
`PRICES` has no price). `run.json` records `preflight` (`ok`, `cost_source`,
`tokens`, `turns`, `cost`), and its cost counts toward `--max-cost`.
`--no-preflight` skips it; `--preflight-only` runs it alone.

### The budget cap

The queue goes rep by rep: rep 1 of every task and arm (task by task, then arm
by arm), then rep 2, and so on; `--jobs` starts runs in that order. A stop then
leaves every task and arm with the same number of reps, give or take one, and
when the cap stops the round, `summary.md` lists the reps each one finished.

`--max-cost USD` is a soft cap, not a hard limit; without it there is no cap.
Before each run starts, the runner adds the cost so far, plus the estimate of
that run and of every run in flight; if the sum passes the cap, it stops
starting new runs (the runs in flight finish) and `summary.md` and `run.json`
get `stopped_for_budget` (true) and `runs_skipped`. Runs already going and
outlier runs can go past the cap by up to `--jobs` times the costliest run. The
6c commands use `--jobs 2`, which keeps that overshoot near $0.06 (the costliest
run of round 12 was about $0.03).

The estimate is the highest cost seen so far (never below the mean), and never
below `--run-cost-estimate` (default $0.01). A run that reports no cost (no
usage at all, or `cost.total` of 0: a timeout, a 429, an auth error) is charged
the estimate, stays out of that figure, and prints a `warning:` line. Cost is
what Pi reports (`cost.total`), or the fallback of "Spend and fix rounds", so
the cap is as good as the price table of the model. The runner prints
`cost so far: $X of the $Y cap` after every run, and `run.json` and
`summary.md` end with the total. The cap is per command: for two
models, give each its share of the total (one command each, as in the example
above); a shared total across commands would need a way to read earlier run
folders, which the runner does not have.

### Hidden cases

A case is `hidden/NN.in` (standard input) and `hidden/NN.out` (the expected
standard output, compared after trimming the final newlines); the run passes the
case when the output is equal and the exit code is 0. A task directory may add
two optional files, which the integration and big-data tasks use:

- `hidden/driver.py` makes a case a small scenario. The runner starts
  `python3 -I -` in the grader container with the driver source on its standard
  input, the content of `NN.in` as its first argument (`sys.argv[1]`, read as
  bytes and decoded as UTF-8, so a CRLF stays CRLF) and the solution command
  after it (`sys.argv[2:]`), and compares what the driver prints. The driver is
  Python standard library only and the independent peer: it runs the solution
  with an absolute path (`/workspace/bin/agentica /workspace/solution.agc`, or
  `python3 -I /workspace/solution.py`; for a tree task see below), serves or
  calls it on `127.0.0.1` port 0, creates its fixtures in a temporary
  directory, and prints a transcript. The
  driver source is never mounted and is read from the standard input, so it is
  in no file and in no `/proc/*/cmdline`; the harness does not defend against a
  solution that reads the memory of its parent process. The case content is in
  the command line, and a plain case gives it to the solution as its input
  anyway. The drivers: t18 starts the solution as a server, reads its
  `listening PORT` line and calls it with `http.client`; t21 does the same on a
  fresh database; t25 and t27 are described with their tasks.
- `hidden/timeout` is the time limit of one case in seconds (the default is 10).

### Tree tasks and case tiers

A tree task's solution spans several files. The task has `reference/<ext>/`
(`agc`, `py`, `go`) instead of `reference.<ext>`, each a whole tree with its
entry point `solution.<ext>`, and may have `start/<ext>/`, a tree the
workspace starts from (the program to change; `--check-starts` needs one per
language).

The solution is `solution.<ext>` and every other `.<ext>` file of the
workspace. These are left out, and the prompt says so:

- the reserved folders the harness fills (`bin/`, `skills/`, `deps/`,
  `docs/`, `examples/`), hidden files and folders, and links (also files
  under a linked folder);
- the agent's own tests: `test_*.py`, `test.py`, `tests.py`,
  `conftest.py`, `*_test.py`, `*_test.go`, `*_test.agc`, and anything under
  a `test/`, `tests/` or `specs/` folder;
- any other file (data, `.pyi`, `go:embed`).

More than 200 files, or a file over 1 MiB, fails the run with failure `size`
(code `too-many-files` or `too-large`), and a file the grader cannot read
with failure `copy`, before any case runs. The grader copies the files
(`solution.<ext>` first), and the run keeps them under `solution/`.

- Python runs as `python3 -s -E solution.py` (also under a driver), so it
  imports its own modules. The typed arm runs `mypy --strict
  --explicit-package-bases -- FILES` on the graded files.
- Go is the module `solution`: package main in the root, other packages in
  subfolders (`solution/<folder>`), checked with `go vet ./...` and
  `go build -o .solution-bin .`. A `_test.go` file is not copied, so vet
  never sees it.
- Agentica imports its files by relative path.
- `fix_rounds` counts an edit of any graded file: an edit tool, or a shell
  write in the forms of single-file tasks (`>`, `tee`, `sed -i`, `cp`/`mv`,
  `open(..., 'w')`). An edit of a test file is not one.
- `agent_timeout` in the task folder raises `--timeout` for that task.
- An `ecosystem` file in the task folder makes it an ecosystem task (see "The
  ecosystem tasks") without a start that imports a package.

A hidden case's name prefix puts it in a tier, in any task:

| prefix | tier | in the status? | counted as |
|---|---|---|---|
| `adv-` | adversarial: malformed input, faults, edge values | no | `adversarial_passed` of `adversarial_total` |
| `reg-` | regression: old behaviour a change must keep | yes | `regressions` (failed cases) |
| `hyg-` | hygiene: shutdown, leaks, exit code | yes | `hygiene_failed` |
| none | main | yes | `passed` of `total` |

`passed` and `total` leave the adversarial cases out; a task needs at least
one other case. `failed_cases` names the cases that failed (of every tier),
and `--check-references` prints them for a reference that fails. A run whose cases did not run (no file, a failed check, a
`size` or `copy` failure) fails every regression and hygiene case.

`crash_cases` counts the failed cases that crashed rather than gave a wrong
answer: the stderr shows a crash (a traceback, `panic:`, `fatal error:` or
`error[RUNTIME-`), and the program exited non-zero. Under a driver the exit
status is the driver's: a driver passes on the program's stderr and adds a
line `PROGRAM-EXIT CODE` when the program ended on its own (not when the
driver stopped it), and a crash needs such a line with a code other than 0.
Every driver does this.

`spec_runs` counts runs of the agent's own tests: `agentica test`,
`python3 -m unittest`, `pytest` (alone or with `-m`), `go test`, and a test
file run directly (`python3 tests/test_x.py`, `agentica x_test.agc`). It comes
from Pi's transcript, so rows of the claude and reference agents have none
(`-`).

`summary.md` adds a table per arm with these, the share of cases passed and
the spend per passing run.

### Before a round

- Network access for the agents. Agent containers can reach the provider, so
  they can reach the whole internet, and the programming skill links
  `https://www.agentica-lang.com/agentica/llms.txt`, so an agent with a shell
  can read the public site. Decide before a round whether that is allowed, and
  record it with the results: `run.json` has `agent_network` (`true` for a model
  run, `false` for `--check-references`), and `net_commands` counts the commands
  that mention `wget`, `git clone`, `github.com`, `pip install`, `npm`, `apt`,
  or `curl` or `urllib` to a host other than `localhost` and `127.0.0.1`. The
  runner has no allow-list for the provider host, so closing the network for the
  agents needs a proxy or firewall that you provide.
- Rebuild the image if the Dockerfile changed (`docker rmi
  agentica-eval:local`), and run `--check-references`. The Dockerfile pins Pi
  1.3.0 (the rounds up to 12 used Pi 1.0.0), so token counts of the 6c round
  are not strictly comparable with those of earlier rounds; the arms inside the
  round are. A model run probes `pi --version` in the default image and stops
  when it differs from the Dockerfile's pin (a stale image); `run.json` has
  `pi_version`.
- Do not merge anything or change the skill while a round runs.
- If `/tmp` is a small `tmpfs`, point `TMPDIR` at a directory on disk before you
  start the runner. Each run copies the runtime bundle (about 580 MB) into a
  temporary directory, so many runs at a time can fill a small `/tmp` and stop
  the round with `No space left on device`.

## Results

Tokens are input plus output per run. A failing interpreter run is an `agentica`
call that ended with an error. Rounds 1 to 4 used earlier sandboxes (round 1 had
none); round 5 is the first run in Docker. Compare rows within a round, not
across rounds. With 3 reps per cell, every finding is a direction, not a claim.
The full tables of rounds 1 to 12 are in git history.

### Rounds 1 to 12: findings

| Round | Setup | Finding |
|---|---|---|
| 1 (2026-10-01) | five tasks, DeepSeek V4.1 flash | every arm 15/15: easy tasks do not separate arms. Agentica about 4x Python tokens (`skill` 13,681 per run, `python` 3,506); the skill 14% under grammar and examples |
| 2 to 4 | `binary` arm | richer diagnostics (labels, `help`, suggestions) cut tokens by a third and time by half, with no docs. Naming `--help` in the prompt made no visible difference |
| 5 and 6 (2026-10-10) | `binary`, no docs | agents write Ruby (`while cond do`, `case x`, `var x = ...`, `when`). Accepting those forms cut failing runs by a quarter to 40%; tokens did not fall |
| 7 (2026-10-10) | `skill` A/B | a 5k-token core with on-demand references cut tokens by 45% and cost by 39%, with the same accuracy |
| 8 | GLM 5.3 flash, `binary` | a second model wrote the same Ruby and Python forms, so the habits are not one model's quirk |
| 9 (2026-10-14) | `binary` on the VM, row 7.2.2 | no regression; tokens fell for both models. The repeated `CHECK-CAPTURED-ASSIGNMENT` on t4 got a help naming the `for` rewrite (PR #195) |
| 10 (2026-10-14) | the 6c pilot, `skill` against `typed-python`, 20 tasks | DeepSeek 59/60 against 57/60, GLM 58/60 against 52/60, gpt-oss-120b 31/60 against 45/60. Agentica cost 1.5 to 3.3 times more per run, mostly reading the skill. gpt-oss writes C-style code and sometimes no `solution.agc`; Nemotron rarely wrote Agentica and was dropped. Typed Python escaped the checker 0.5 to 0.9 times per run (`Any`, `cast(`) |
| 11 | `binary`, PR #198 | `agentica --help` with four core rules and the builtin namespaces cut tokens by a third to a half for DeepSeek and 10% to 20% for GLM, with fewer failing runs |
| 12 | `skill`, PRs #200, #201, #204 | hints for `;`, braces and other foreign habits, and `SKILL.md` cut from about 5,300 to 1,600 tokens: tokens per run fell 14% to 23%, pass rates held. gpt-oss still fails half its runs |

### Round 13: the 6c round (2026-10-22)

The first full 6c round: tag 0.8.1, the `skill`, `typed-python` and
`skill-nocli` arms, 3 reps, DeepSeek V4.1 flash (13 tasks; the budget cap
stopped it) and GLM 5.3 flash (20 tasks). With 3 reps these are directions, not
claims; the raw tables are in git history.

- **The query commands were not used.** No run called `outline`, `type-at`,
  `symbol` or `refs`, so the round cannot show the value of the semantic CLI;
  how the skill presents them is what to change before the next round.
- **Pass rates are close.** DeepSeek 38/39 `skill` against 39/39
  `typed-python`; GLM 58/60 against 53/60. Every failure is a logic error on a
  hidden case.
- **Agentica costs more per run:** 1.8 times (DeepSeek) and 3.1 times (GLM),
  with 4.7 and 4.8 times the context. Input and cache reads are 75% and 81% of
  the extra cost, so the context, not the output, is what to cut.

## Benchmark twins

`bench/` times agentica's benchmark programs against a Python and a Go twin of
each, to compare the speed of the three. The Agentica programs and the Python
twins come from agentica's `benchmarks/` at the pinned commit
(`AGENTICA_COMMIT`, the 0.34.1 tag; agentica's master no longer has the Python
twins), fetched into `.cache/` like the sources. The Go twins are in
`bench/go/`, one file per program, and print the same.

```sh
make bench                  # median of 5 runs after one warm-up run, size 5
make bench RUNS=9 SIZE=10   # more runs, more work per run
make bench-check            # one run each at size 1: do the outputs match (CI)
make image                  # rebuild the evaluation image (bench/run.py builds it when it is missing)
```

`bench/run.py` stages the scaled programs, the twins and the pinned binary,
and runs `bench/measure.py` in one container of the evaluation image: no
network, every capability dropped, no new privileges, at most 512 processes,
`--init`, and every core of the machine (no CPU limit, as a user's program
would run). The versions are fixed: Agentica 0.34.1 (the release), Go 1.27.4
(`GO_VERSION` of the Dockerfile, checked by its SHA-256) and Python 3.13 (the
`python3` of the digest-pinned Debian trixie base, 3.13.5 when written);
`measure.py` prints them and stops when the image has another Python minor or
Go version.

`measure.py` first builds the Go twins and compiles each Agentica program to
bytecode (`agentica compile`); neither is timed. Each program then runs on
four runners:

- `agentica`: the bytecode, `agentica run -- FILE.agcb`. The main column, as
  in agentica's own benchmarks.
- `agentica cold`: `agentica FILE.agc`, which runs the front end every time,
  the start-up a user sees (about 50 ms more).
- `python`: `python3` on the twin.
- `go`: the built twin.

One run of each runner is not timed: it warms the caches and gives the outputs,
and an output that differs from Agentica's is a `mismatch` (the run then exits
1). Then each timed round goes through the four runners in turn, so a change in
the machine's load hits them alike; the table has the median seconds of each.
The `hello` row is the start-up of each runtime (a program that prints one
line). The two last columns say how the `agentica` column compares: `3.2x
faster` or `2.5x slower` than Python, and than Go. The load average is printed
at the start and at the end; above 2 the numbers are rough.

The default size is 5, so most programs run long enough that start-up is not
most of the time; size 1 (`bench-check`) is for the outputs only. The
programs that write files (`read-lines`, `line-scan`, `bytes`) write them to
the container's `/tmp`, a 1 GB tmpfs: above size 20, raise it
(`python3 bench/run.py --tmpfs 4g ...`).

The twins follow their program, not the fastest Go: an ATS is a map behind a
lock, `Task.spawn` a goroutine, a channel a buffered channel of size 1. A
channel call or an await with a deadline (`recv(5000)`, `Task.await(t, 60000)`)
is a `select` on a timer that the goroutine resets for each call, with the same
deadline as the program (5 s in `channel-pingpong`, 1 s in
`deadline-pingpong`, 60 s in `store-clients` and in the second phase of
`sleepers`); the Python twins pass the same timeouts to `queue`.

The ping-pong programs hand one value back and forth between two tasks, so they
measure the wake-up of the other task: Agentica's scheduler and Go's runtime do
it in very different ways, and Python's threads are far slower at it. In Go
the timer is most of the cost: at size 5, `deadline-pingpong` took 3.6 s, and
the same exchange with no deadline about 0.47 s (0.40 s with `GOMAXPROCS=1`).
The figure depends on the cost of Go's timers and of the futex calls that wake
a goroutine on another core, so on the kernel and the number of cores.

Go's `regexp` is RE2, which does not backtrack: the `(a+)+$` case of `regex`
is a backtracking blow-up for engines that backtrack, and a short linear scan
in Go.

## Diagnostics

`diagnostics.py` counts the codes the agents saw. In the `binary`
rounds 5 to 8 the top codes were `PARSE-UNEXPECTED-TOKEN`, `CHECK-UNKNOWN-NAME`,
`CHECK-TYPE-MISMATCH`, `CHECK-MISSING-RETURN` and `CHECK-UNKNOWN-METHOD`, mostly
Python and Ruby habits, not logic errors (`len(s)`, `s.length`, `x.to_i`,
`print(x)`, `x += 1`; check the grammar for what the language accepts). In
rounds 2 to 4, agents fixed failing runs after reading the code and the span, so
the diagnostics worked as a repair signal.

## What the results do not show

- Accuracy on harder tasks. These tasks do not need sorting or building a list,
  and most of them pass.
- Strong models. Only small and cheap ones ran (DeepSeek, GLM, gpt-oss, and
  Nemotron in part).
- Whether `--ai` or `--json` help. They were not measured.
- Whether Agentica beats typed Python with confidence. The round 10 pilot points
  that way for two of three models, with 3 reps per cell. The full comparison is
  issue #1009 (see "The full 6c round").
- Time in rounds 10 and 11, which ran next to each other with more runs at a
  time.
- Whether the semantic CLI helps. In round 13 no agent called it.
