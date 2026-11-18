# Agentica evals

The agent evaluation of Agentica: tasks, a runner that gives each task to an
agent in a Docker sandbox, and the grading against hidden cases. `README.md`
explains the arms, the measures and the results.

## Map

```text
run.py              the runner: prepare, run the agent, grade, summarize
diagnostics.py      counts the diagnostics the agents saw
test_*.py           unit tests of the runner (unittest)
Dockerfile          the evaluation image (Pi, mypy, pinned)
tasks/              one folder per task: task.md, reference.*, start.*, hidden/
.cache/             the pinned Agentica release and sources (not versioned)
.secrets/           provider auth files (never committed)
results/            run output (never committed)
```

## Commands

- `python3 -m unittest discover -p 'test_*.py'`: the unit tests. The tests
  that need the pinned Agentica sources fetch them once into `.cache/` and are
  skipped when that fails (offline); the Docker tests need the image.
- `python3 run.py --check-references`: every reference passes every hidden
  case; no model, no credentials.
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
