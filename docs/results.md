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

## What the results do not show

- Accuracy on harder tasks. These tasks do not need sorting or building a list,
  and most of them pass.
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
