# Agentica evals

The agent evaluation of Agentica: tasks, a runner that gives each task to an
agent in a Docker sandbox, and the grading against hidden cases. `README.md` is
the entry page; `docs/` holds the arms, the tasks, how to run, the results and
the benchmarks.

## Map

```text
run.py              the runner: prepare, run the agent, grade, summarize
diagnostics.py      counts the diagnostics the agents saw
test_*.py           unit tests of the runner (unittest)
Dockerfile          the evaluation image (Pi, mypy, pinned)
tasks/              one folder per task: task.md, reference.* (or reference/<ext>/
                    trees), start.* (or start/<ext>/), hidden/
ecosystem/          the pinned packages of the ecosystem tasks
.cache/             the pinned Agentica release and sources (not versioned)
.secrets/           provider auth files (never committed)
results/            run output (never committed)
bench/              the benchmark twins: run.py, measure.py, go/ (make bench)
docs/               the pages behind README.md: arms, tasks, running, results,
                    benchmarks
```

## Commands

- `python3 -m unittest discover -p 'test_*.py'`: the unit tests. The tests
  that need the pinned Agentica sources fetch them once into `.cache/` and are
  skipped when that fails (offline); the Docker tests need the image.
- `python3 run.py --check-references`: every reference passes every hidden
  case; no model, no credentials.
- `make bench-check`: the Go twins of `bench/go/` print what the pinned
  Agentica programs and Python twins print; `make bench` times them.
- `python3 run.py --agent pi --model M --pi-auth .secrets/pi-auth.json ...`: a
  model round. It costs money: only with the owner's OK.

## Rules

- This repository is public. Never commit `.secrets/`, `results/`, keys,
  tokens, request headers or raw transcripts. Check a key only with `jq -e`.
- A starter program keeps its intentional bugs; do not repair it or change the
  hidden cases. A task change passes `--check-references`.
- The Agentica version is pinned in `run.py` (release archive SHA-256 and tag
  commit); change the three values together.
- Tests use the standard library only. A pull request runs CI: the unit tests
  and `--check-references`. No model calls in CI.
- Merge commits only; no force push and no rebase of a shared branch.
- Prose wraps at 80 characters; code blocks keep their line breaks. Use simple
  words.
