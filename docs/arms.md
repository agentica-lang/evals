# Arms

The arms are the context an agent gets:

- `python`: the same task in Python (untyped). The baseline of the first rounds.
- `typed-python`: the same task in Python with type annotations, checked by
  `mypy --strict` (see [The typed Python arm](#the-typed-python-arm)).
- `skill`: the `agentica-programming` skill and the `agentica` binary.
- `skill-nocli`: the `skill` arm without the four query commands (`agentica
  outline`, `type-at`, `symbol`, `refs`), for the measurement of the query
  commands. It is opt-in: `--arms` must name it. See [The no-CLI
  arm](#the-no-cli-arm).
- `grammar`: `docs/grammar.md` and `examples/`, without the skill. Its prompt
  gained the `agentica help` pointer (commit efba1a0b), so older grammar-arm
  results are not comparable. `agentica help` covers the builtins only, so this
  arm has no signature source for the `std/` modules (`HTTP`, `Queue`, `BDD`).
- `binary`: only the binary, `agentica check`, and a one-line hint. No docs.
- `go`: the same task in Go, standard library only, checked by `go vet` and `go
  build`. It is opt-in: `--arms` must name it. See [The Go arm](#the-go-arm).

The prompts are not equal, and they stay as they are so that rounds remain
comparable. The `binary` prompt names `agentica check` and `agentica --help`;
the `skill` prompt names only the skill, which teaches `agentica check`; the
`grammar` prompt names `agentica help NAME`; the `typed-python` prompt names
`mypy --strict solution.py`; the `go` prompt names `go vet solution.go` and `go
build solution.go`; the `python` prompt names no checker. Read a difference
between arms with that in mind.

## The Agentica under test

By default a run uses Agentica 0.34.1: the `linux-x86_64` release archive,
downloaded once into `.cache/` and checked against the SHA-256 pinned in
`run.py`, and a sparse checkout of the commit of the `0.34.1` tag for the skill,
the grammar, the library pages and the examples. `.cache/` is not versioned. Two
options replace them:

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

## The typed Python arm

The `typed-python` arm is the Python side of the typed-Python comparison. The
agent writes `solution.py` with type annotations and gets `mypy` on its `PATH`,
like the Agentica arms get `agentica check`. The prompt gives the command, `mypy
--strict solution.py`, and says not to silence it with `# type: ignore` or by
weakening its options.

- Checker: mypy 2.3.1 (compiled), run with `--strict`. The version and its five
  dependencies are pinned in `Dockerfile`; `run.json` records the version the
  image reports. mypy is the checker of this arm. It installs from PyPI as
  compiled wheels, with no download at run time; the `pyright` package on PyPI
  fetches its npm package on first use, which the grader (no network) cannot do.
- Grading: the grader first runs `mypy --strict --cache-dir=/dev/null
  solution.py` in a fresh container, in the same mount and with the same limits
  as the hidden cases. A solution that fails the checker is a failing run with 0
  cases passed, like an Agentica program that fails `agentica check` and never
  runs. The row has `failure: check` and the first mypy error code (`arg-type`,
  `assignment`, `return`...) as `code`, or `syntax` for a parse error, and
  `check_errors`, the number of errors. A checker that runs for more than 90
  seconds is `failure: check-timeout`. A passing solution then runs against the
  hidden cases like any other.
- Silencing the checker fails the run. A solution with a `# type: ignore` or a
  `# mypy:` comment (such as `# mypy: ignore-errors`, which makes `mypy
  --strict` pass) fails before mypy runs, with `failure: check`, `code: ignore`
  and 0 cases passed. The prompt forbids `# type: ignore` and weakening the
  options; it does not name `# mypy:` (the prompt stays as it is so that rounds
  remain comparable), but the grader rejects those comments too. Every typed row
  has `type_ignores`, the number of those comments, so a failing row shows it,
  and `type_escapes`, the number of `Any`, `cast(`, `no_type_check` and
  `TYPE_CHECKING` in the source. `type_escapes` is a heuristic text count: words
  in strings and comments count, and an alias (`import typing as t`, `from
  typing import Any as A`) hides one. Escapes do not fail a run, and the checker
  still runs, but check them before you compare the arms: `summary.md` shows
  their mean in the `type escapes` column.
- Measures: `interpreter_runs` counts every bash call that runs `agentica`,
  `python`, `mypy` or `go vet|build|run|test`; `check_runs` counts the calls to
  `mypy`, `agentica check`, `go vet` and `go build`. A `go vet` and a `go build`
  in calls next to each other, in either order (no edit or other run between),
  are one interpreter run, one check run and one failure at most, because the Go
  check is the two commands where the other arms have one (both a lower bound: a
  command is recognised at the start of a shell segment, also after `do`,
  `then`, `else`, `!`, `{`, `(`, `$(` or a backtick, after the `env`, `time`,
  `timeout`, `nohup`, `xargs`, `uv run` and `NAME=value` prefixes, and inside
  `bash -c` or `sh -c`, so a run through another wrapper or a script is not
  counted). A program that a `go build` wrote, run through a path (`./solution`,
  `/tmp/s`), is a run too, and its `panic:` a failure. Before 2026-11-18 a call
  that only named one of them, such as a `sed` of the skill's files, also
  counted, in `interpreter_runs` and, when its output held an error line, in
  `failing_runs`. That inflated the skill arm, so rounds 1–15 do not compare
  between arms on those two measures; `check_failures` counts those that failed
  (a mypy `error:` line, an `error[...]` diagnostic); `failing_runs` counts
  every failing call, checks included, so repairs are compared with the checker
  calls on both sides. Tokens, turns, cost and seconds are the same as in the
  Agentica arms. `diagnostics.py` still counts Agentica diagnostics only. A
  `file.go:N:M:` or `panic:` line is a failure of a Go call (see [The Go
  arm](#the-go-arm)). Only `--agent pi` reports calls: `--agent claude` gives
  totals, so its interpreter, check and failing runs read 0, which means not
  measured.
- Starts: `start.py` is typed and passes `mypy --strict`. A task written for the
  untyped arm may have `start.typed.py`, the same program with annotations,
  which the typed arm gets as `start.py`.
- The untyped `python` arm stays for comparison with the early rounds. It is not
  part of the typed-Python pilot. Its workspace has no Agentica binaries.

## The Go arm

The `go` arm writes `solution.go`, one `main` package with the standard library
only (`net/http` for t18). The workspace has a `go.mod` (`module solution`, the
Go version of the image), and `start.go` where the task has a start. The prompt
gives `go run solution.go` and the two checkers, `go vet solution.go` and `go
build solution.go`, and says not to silence them. A task without a
`reference.go` is not available in Go yet: the go arm skips it and prints a
note, and `--check-references` grades go only on the tasks that have one. A tree
task may get its references one language per change (Python first): until
`reference/<ext>/` is there, every arm of that language skips it, and
`--check-starts` compares the start trees it has.

- Toolchain: Go 1.27.4, pinned with its SHA-256 in `Dockerfile`; `run.json`
  records `go env GOVERSION`, and the workspace `go.mod` takes its language
  version from it. The image sets `GOFLAGS=-mod=mod`, `GOPROXY=off`,
  `GOTOOLCHAIN=local` and `CGO_ENABLED=0`, so Go works offline by default; the
  agent container has network, so an agent that sets `GOPROXY` itself can still
  download (`net_commands` counts `go get`, `go install`, `go mod download`, `go
  mod tidy`, `GOPROXY=`, `golang.org` and `pkg@version` or `@latest`). The image
  carries a read-only build cache of the whole public standard library (every
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
  then the class (`syntax error` gives `syntax`) and the count come from `go
  build -gcflags=-e`, so a program with six type errors counts 6, not 1. A vet
  failure records `build_ok`, and `summary.md` counts the go runs that failed
  vet alone (the build passed). The hidden cases then run the binary. A `panic:`
  is `failure: runtime`, code `panic`, and a `fatal error:` (a deadlock) code
  `fatal`. Go rows have no `type_escapes` (`-` in `summary.md`).
- Starts: `start.go` keeps the bugs of `start.py` and has `//go:build ignore`,
  so `go build .` leaves it out. A start gives the output of `start.py` on the
  hidden cases, and `--check-starts` checks that they grade alike.

What is not equal to the other arms:

- The commands name the file (`go vet solution.go`), not the package: the
  workspace also holds `start.go`, which is package `main` too.
- `task.md` names `solution.agc` and `solution.py` only; the prompt names
  `solution.go`. Some tasks ask for an Agentica or Python type: a `Command[T]`
  enum with exhaustive `case` (t8). Go has no sum types or exhaustive switch, so
  the reference uses an interface with a type switch, and nothing checks a
  missing case. A task can add a `task.go.md`, which the go arm gets at the end
  of its `task.md`.
- The task text of t18 names `sys.argv`, `System.args()` and the Python or
  Agentica HTTP modules; the Go prompt adds that these are `os.Args` and
  `net/http`.
- Go is strict where the other checkers are not: an unused variable or import is
  a compile error, so a draft fails more checks. `go vet` also runs analyses
  that are not type checks (`printf` formats, copied locks, unreachable code),
  which mypy and `agentica check` do not have.
- The check is two commands, each with the 90-second checker limit, where the
  other arms have one.
- The arm runs in Docker only. The Firejail sandbox refuses it. For `go run` the
  `/tmp` tmpfs of every container is now mounted `exec` with 256 MB; rounds
  before the Go arm had it `noexec`.
- The image is `linux/amd64` only (the Go archive is), and the Dockerfile needs
  BuildKit (`ADD --checksum`).
- A crash exits 1 in Python and Agentica and 2 in Go (a `panic`). No rule
  depends on it: a case passes only with exit 0 and the expected output, and the
  failure class comes from stderr.
- Known gaps, not fixed: the t18 driver never sends some of the cases the task
  describes, so a Go (or any) server can get them wrong and still pass. t16
  states that salaries and totals fit in 64 bits, as Agentica's `Int` and Go's
  `int` do.

## The no-CLI arm

`skill-nocli` is the `skill` arm with two changes, made in the copy the agent
gets (the skill in the repository is never edited):

- The skill copy has no `references/queries.md` and no `references/analysis.md`,
  and none of the lines that point to them: their two table rows in `SKILL.md`,
  and the `QUERY-` codes of `references/diagnostics.md`. The runner stops when
  any file of the copy still names a query command, so a change to the skill
  cannot leak one unnoticed.
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
