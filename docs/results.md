# Results

Tokens are input plus output per run. A failing interpreter run is an `agentica`
call that ended with an error. Rounds 1 to 4 used earlier sandboxes (round 1 had
none); round 5 is the first run in Docker. Compare rows within a round, not
across rounds. With 3 reps per cell, every finding is a direction, not a claim.
The full tables of rounds 1 to 12 are in git history.

## Rounds 1 to 12: findings

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

## Round 13: the 6c round (2026-10-22)

The first full 6c round: tag 0.8.1, the `skill`, `typed-python` and
`skill-nocli` arms, 3 reps, DeepSeek V4.1 flash (13 tasks; the budget cap
stopped it) and GLM 5.3 flash (20 tasks). With 3 reps these are directions, not
claims; the raw tables are in git history.

- **The query commands were not used.** No run called `outline`, `type-at`,
  `symbol` or `refs`, so the round cannot show the value of the semantic CLI;
  how the skill presents them is what to change before the next round.
- **Pass rates are close.** DeepSeek 38/39 `skill` against 39/39 `typed-python`;
  GLM 58/60 against 53/60. Every failure is a logic error on a hidden case.
- **Agentica costs more per run:** 1.8 times (DeepSeek) and 3.1 times (GLM),
  with 4.7 and 4.8 times the context. Input and cache reads are 75% and 81% of
  the extra cost, so the context, not the output, is what to cut.

## Round 14 (R1): Go and the ecosystem tasks (2026-11-18)

Agentica 0.34.1 against typed Python and Go, 1 rep, about $0.80 for 123 runs.
DeepSeek V4.1 flash ran 23 tasks, GLM 5.3 flash ran 11 of them (t6, t8, t10,
t16 to t23).

| Model | Arm | Pass | $/run | Turns/run |
|---|---|---|---|---|
| DeepSeek | `skill` | 23/23 | 0.0088 | 11.5 |
| DeepSeek | `typed-python` | 22/23 | 0.0038 | 5.7 |
| DeepSeek | `go` | 23/23 | 0.0039 | 6.0 |
| GLM | `skill` | 10/11 | 0.0145 | 17.4 |
| GLM | `typed-python` | 10/11 | 0.0039 | 7.8 |
| GLM | `go` | 11/11 | 0.0057 | 9.9 |

- **Pass rates are at the ceiling** for every arm, so the round cannot show a
  quality difference.
- **Agentica costs 2.3 to 3.7 times more per run** and takes about twice the
  turns. On the ecosystem tasks (t21 to t23, with packages) it is about 3.5
  times the cost and 3 to 4 times the turns.
- **Where the extra turns go** (DeepSeek, per run): about 2.4 reads of the skill
  and docs, 1.5 greps over them, 5.5 self-test calls against 1.1, and 0.57 fix
  rounds against nearly none. The cached context is about 9 times larger.
- **Time** is about 75% model output; grading takes about 5 s.
- The baselines get no docs, so the cost gap includes learning the language.

## Round 15 (R2): larger tree tasks (2026-11-18)

Main 9835239, DeepSeek V4.1 flash, 1 rep, 4 arms, 6 tasks (t8, t16, t18, t21,
and the larger tree tasks t25 and t27 with adversarial cases), 24 runs, $0.72.

| Arm | Pass | Cases | Adversarial | $/run | Turns/run | s/run |
|---|---|---|---|---|---|---|
| `skill` | 6/6 | 119/119 | 24/24 | 0.036 | 30.0 | 441 |
| `typed-python` | 6/6 | 119/119 | 24/24 | 0.036 | 19.5 | 410 |
| `python` | 6/6 | 119/119 | 24/24 | 0.027 | 14.5 | 474 |
| `go` | 6/6 | 119/119 | 24/24 | 0.021 | 15.7 | 401 |

- **Larger tasks do not separate the arms either.** Every arm passed every
  hidden case, adversarial included, with no crash and no hygiene failure.
- **Agentica was the slowest on t25 and the fastest on t27.** On t25 it took
  about twice the time (1076 s against 475 to 557) and 3 to 4 times the turns.
  On t27 it finished first (970 s against 1219 to 1918), and its cost was
  below `typed-python` and `python`.
- **The `skill` arm costs the same per run as `typed-python`** at about twice
  the turns; `go` is the cheapest.
- **The `skill` arm ran its own spec least:** 2 times in all, against 12 to 14.
- **Typed Python escaped its checker** 9 times on t25 and 3 times on t18.

## Conclusions

- With the cheap models tried, every arm reaches the ceiling on these tasks,
  small or large. The evals measure the cost of a language an agent does not
  know, not a quality edge.
- That cost has come down: from about 4 times the tokens of Python (round 1) to
  the same cost per run as typed Python on the larger tasks (round 15). The
  extra turns are mostly reading the skill and the docs.
- Agentica is not slower to finish once a task is large: the fastest arm on t27.
- A quality edge, if any, would need tasks that fail often in the baselines, or
  models that fail more. Neither showed up in these rounds.
- No blog post is planned from these numbers; they live here.

## What the results do not show

- Accuracy on tasks the baselines fail. Even the larger tree tasks of round 15
  pass in every arm.
- Strong models. Only small and cheap ones ran (DeepSeek, GLM, gpt-oss, and
  Nemotron in part).
- Whether `--ai` or `--json` help. They were not measured.
- Whether Agentica beats typed Python with confidence. The round 10 pilot points
  that way for two of three models, with 3 reps per cell. The full comparison is
  issue #1009 (see [The full 6c round](running.md#the-full-6c-round)).
- Time in rounds 10 and 11, which ran next to each other with more runs at a
  time.
- Whether the semantic CLI helps. In round 13 no agent called it.

## Diagnostics

`diagnostics.py` counts the codes the agents saw. In the `binary` rounds 5 to 8
the top codes were `PARSE-UNEXPECTED-TOKEN`, `CHECK-UNKNOWN-NAME`,
`CHECK-TYPE-MISMATCH`, `CHECK-MISSING-RETURN` and `CHECK-UNKNOWN-METHOD`, mostly
Python and Ruby habits, not logic errors (`len(s)`, `s.length`, `x.to_i`,
`print(x)`, `x += 1`; check the grammar for what the language accepts). In
rounds 2 to 4, agents fixed failing runs after reading the code and the span, so
the diagnostics worked as a repair signal.
