# Agent evaluation

Can an agent write and repair Agentica programs? An agent gets one task, and its
program is graded against hidden cases. The runs count passing cases, tokens,
time, and interpreter and checker runs that failed.

This repository holds the tasks, the runner and the results notes. It used to
live in `tests/eval/` of
[agentica-lang/agentica](https://github.com/agentica-lang/agentica), and its
history came along.

The suite has eight tasks: four small ones and four larger tree tasks. The task
list, the hidden cases and the ecosystem tasks are in
[docs/tasks.md](docs/tasks.md).

## The arms

The arms are the context an agent gets. The prompts differ by arm, so read a
difference between arms with that in mind.

| Arm | The agent gets |
|---|---|
| `python` | the task in Python, untyped: the baseline of the first rounds |
| `typed-python` | the task in Python with annotations, checked by `mypy --strict` |
| `skill` | the `agentica-programming` skill and the `agentica` binary |
| `skill-nocli` | the `skill` arm without the four query commands (opt-in) |
| `grammar` | `docs/grammar.md` and `examples/`, without the skill |
| `binary` | only the binary, `agentica check`, and a one-line hint |
| `go` | the task in Go, checked by `go vet` and `go build` (opt-in) |

Each arm, the Agentica version under test and the prompts are in
[docs/arms.md](docs/arms.md).

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

# The runner's unit tests (CI runs them)
python3 -m unittest discover -p 'test_*.py'
```

The options, the sandbox, the cost measures, the budget cap and the checklist
before a round are in [docs/running.md](docs/running.md).

## Results

Easy tasks did not separate the arms in round 1. In the round 10 pilot, Agentica
cost 1.5 to 3.3 times more per run than typed Python, mostly for reading the
skill. Round 12 cut the skill from about 5,300 to 1,600 tokens: tokens per run
fell 14% to 23%, and the pass rates held.

Round 13 was the first full 6c round (2026-10-22). Pass rates were close:
DeepSeek 38/39 `skill` against 39/39 `typed-python`, and GLM 58/60 against
53/60. Agentica cost 1.8 times (DeepSeek) and 3.1 times (GLM) as much per run.
No run called the query commands.

With 3 reps per cell these are directions, not claims. The findings of every
round, what the results do not show, and the diagnostics are in
[docs/results.md](docs/results.md).

## Docs

| Page | What it covers |
|---|---|
| [docs/arms.md](docs/arms.md) | the arms, the prompts, the Agentica under test, the typed Python, Go and no-CLI arms |
| [docs/tasks.md](docs/tasks.md) | the tasks, the ecosystem tasks, the hidden cases, the tree tasks and the case tiers |
| [docs/running.md](docs/running.md) | the options, the Docker sandbox, the measures, the budget cap, the preflight and before a round |
| [docs/results.md](docs/results.md) | the findings of rounds 1 to 13, what the results do not show, the diagnostics |
| [docs/benchmarks.md](docs/benchmarks.md) | the benchmark twins: `make bench` and its runners |
