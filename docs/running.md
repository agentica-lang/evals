# Running the evals

## Options

`--tasks` picks tasks (the default is all six). `--arms` picks arms (the
default is every arm but the opt-in `skill-nocli` and `go`). `--arm-tasks
ARM=TASK,TASK` limits one arm to some of the tasks (full task names, all in
`--tasks`; repeat the option for another arm). `--max-cost USD` is a soft cap on
the cost of the round (see [The budget cap](#the-budget-cap)). `--sandbox
firejail --chroot-root PATH` is the other sandbox; you prepare its rootfs
yourself, and it needs `mypy` for the typed arm. Docker is the only sandbox
tested with the typed arm, the drivers and the loopback peers; Firejail is
untested for them. The results go to `results/`, which is not versioned. Each
run directory has a `run.json` with the commit, the Agentica version and source
commit, the checker version, the Go version, the Pi version, the model, the
arms, and the image name and ID, next to `results.jsonl` and `summary.md`. The
runner has its own tests: `python3 -m unittest discover -p 'test_*.py'`. CI runs
them, `--check-references` and `--check-starts` on every pull request (no model
calls).

## Checks

`--check-references` is the same as `--agent reference` with the arms `binary`,
`python`, `typed-python` and `go` (the three Agentica arms share one reference).
It copies each `reference.*` as the solution, grades it like an agent's, prints
the table, and exits 1 when a reference fails. Use it after any change to a
task, the runner, the image or the Agentica version.

`--check-starts` grades each `start.go` and the typed Python start of its task
as solutions, and exits 1 when their status, passed cases or failure kind
differ, so a Go start keeps the bugs of the Python one.

## The Docker sandbox

The Docker sandbox works like this:

- Grading runs each hidden case in a fresh container with `--network=none`, no
  provider credentials, and the solution mounted read-only. The container has a
  loopback interface, so a grader can run a server next to the solution (see
  [Hidden cases](tasks.md#hidden-cases)).
- Agent containers mount only the task workspace, and they can reach the
  provider. They run with `--read-only`, `--cap-drop=ALL` and
  `no-new-privileges`. Credentials come only from `--pass-env` or `--pi-auth`.
- `--pi-auth PATH` gives Pi a key in its `auth.json` format, such as
  `{"opencode-go": {"type": "api_key", "key": "..."}}`. The key file lives in
  `.secrets/`, which git ignores; it is never in the image. The container gets
  it read-only at `/run/pi-auth.json` and copies it to `~/.pi/agent/auth.json`
  on its tmpfs, because Pi locks that file in its own folder. Its strings of 8
  characters or more are redacted from the agent log (as written and
  JSON-escaped; Pi's delta events, which can split a key, are dropped from it)
  and from the copied solution, and `run.json` records only `pi_auth_file:
  true`. Pi 1.3.0 of the image has the `opencode-go` provider (`pi --list-models
  opencode-go`). The agent runs as the same user and can read the copy, so use a
  key made for the eval, with a spend cap, rotate it after a round, and put one
  provider only in the file.
- `TMPDIR` is `/tmp` in every container, because the root file system is
  read-only and the launcher writes its bytecode to the temporary directory. The
  image has `libgc1` and `libssl3t64`, which a `dist/agentica` built with the
  system libraries links; the release binary needs only glibc.
- `--agent claude` needs `--image` with the Claude CLI and Python. The default
  image has Pi only.

If you change `Dockerfile`, remove the old image (`docker rmi
agentica-eval:local`). The runner also rebuilds the default image by itself, and
prints a line saying so, in two cases: `mypy --version` exits 126 or 127 in it
(typed arm), or it cannot run a hello program with the agentica binary (any
Agentica arm). Any other failure of the probes stops the run with a message, and
an image given with `--image` is never rebuilt: the runner stops and asks you to
rebuild it.

## Spend and fix rounds

Every row and `summary.md` have two more figures; `summary.md` also totals them
per arm, over the tasks every arm ran (the go arm skips a task without Go
files), and lists the tasks of each arm.

- `cost` (the `spend $` column) is the cost Pi reports, `cost_source: agent`.
  When Pi reports 0 for a run that used tokens, the runner prices the tokens
  with `PRICES` in `run.py` (`cost_source: table`): the opencode-go prices of Pi
  1.3.0's catalog, the same as `https://opencode.ai/inference/go/v1/models` on
  2026-11-18. A model outside the table gets `cost_source: none` and a cost of
  0. Either way it is the list price: it does not count OpenCode Go's double
  price on weekday hours (01:00 to 04:00 and 06:00 to 10:00 UTC) or the
  allowance of the plan. `run.json` has `started_utc` for that reason.
- A run whose agent passes `--timeout` has `status: timeout` and `failure:
  agent-timeout`, whatever its file grades (the cases it passes stay in
  `passed`). It keeps the transcript and the cost of the turns Pi finished; the
  request still open when it was killed reports nothing, so its `cost_source`
  ends in `-partial` and the cost is a lower bound.
- `fix_rounds` counts failed check or run calls (the calls of
  `interpreter_runs`) that an edit follows before the next check or run call:
  Pi's `edit` or `write` tool on a `solution.*` file without an error, or a
  shell command that writes `solution.*` in a common form (`>`, a `cat` heredoc,
  `tee`, `sed -i`, `cp` or `mv` onto it, `open(..., 'w')` in a `python -c`); a
  script that writes it is not seen. A failure that another call follows first,
  or that is never edited, is no round. `failing_runs` stays the count of every
  failed call.

`--agent claude` reports no calls, so its `fix rounds` read `-`.

## Query-command counts

For `--agent pi`, every row and `summary.md` count, next to the checks:

- `query_runs`: bash calls that run `agentica outline`, `type-at`, `symbol` or
  `refs`, with or without `--json`, through a path (`dist/agentica`) or after
  `cd x &&`, `time` or a pipe. Like `check_runs`, it is a lower bound (no `bash
  -c`, no script).
- `read_runs`: calls that read files: a shell segment that starts with `cat`,
  `rg`, `sed`, `head`, `grep` or `tail` (a `| head` filter does not count), and
  every call of Pi's `read` tool.
- `refused_queries`: calls the `skill-nocli` wrapper refused (0 in the other
  arms).

`--agent claude` reports 0 for the counts, which means not measured.

## The full 6c round

Issue #1009 tracks it: the Agentica `skill` arm against the typed Python arm,
with the same model and budget, and the measurement of `--ai` and labels against
plain text on the `binary` arm.

## The preflight

Before the first task of a `--agent pi` round in Docker, the runner makes one
tiny call in the agent image, with the round's model, mounts, auth and network:
the prompt `Reply with the word pong.` It stops the round before any task when
Pi does not answer, when the provider refuses the key or the model (Pi exits 0
then, and the error is in the assistant's `message_end`), when Pi does not know
the model, when the answer has no tokens or does not parse, or when the run has
no cost source ("no cost source for MODEL": Pi reports 0 and `PRICES` has no
price). `run.json` records `preflight` (`ok`, `cost_source`, `tokens`, `turns`,
`cost`), and its cost counts toward `--max-cost`. `--no-preflight` skips it;
`--preflight-only` runs it alone.

## The budget cap

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
what Pi reports (`cost.total`), or the fallback of [Spend and fix
rounds](#spend-and-fix-rounds), so the cap is as good as the price table of the
model. The runner prints `cost so far: $X of the $Y cap` after every run, and
`run.json` and `summary.md` end with the total. The cap is per command: for two
models, give each its share of the total (one command each, as in the example
above); a shared total across commands would need a way to read earlier run
folders, which the runner does not have.

## Before a round

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
  1.3.0 (the rounds up to 12 used Pi 1.0.0), so token counts of the 6c round are
  not strictly comparable with those of earlier rounds; the arms inside the
  round are. A model run probes `pi --version` in the default image and stops
  when it differs from the Dockerfile's pin (a stale image); `run.json` has
  `pi_version`.
- Do not merge anything or change the skill while a round runs.
- If `/tmp` is a small `tmpfs`, point `TMPDIR` at a directory on disk before you
  start the runner. Each run copies the runtime bundle (about 580 MB) into a
  temporary directory, so many runs at a time can fill a small `/tmp` and stop
  the round with `No space left on device`.
