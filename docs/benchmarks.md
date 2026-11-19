# Benchmark twins

`bench/` times agentica's benchmark programs against a Python and a Go twin of
each, to compare the speed of the three. The Agentica programs and the Python
twins come from agentica's `benchmarks/` at the pinned commit
(`AGENTICA_COMMIT`, the 0.35.0 tag; agentica's master no longer has the Python
twins), fetched into `.cache/` like the sources. The Go twins are in
`bench/go/`, one file per program, and print the same.

```sh
make bench                  # median of 5 runs after one warm-up run, size 5
make bench RUNS=9 SIZE=10   # more runs, more work per run
make bench-check            # one run each at size 1: do the outputs match (CI)
make image                  # rebuild the evaluation image (bench/run.py builds it when it is missing)
```

`bench/run.py` stages the scaled programs, the twins and the pinned binary, and
runs `bench/measure.py` in one container of the evaluation image: no network,
every capability dropped, no new privileges, at most 512 processes, `--init`,
and every core of the machine (no CPU limit, as a user's program would run). The
versions are fixed: Agentica 0.35.0 (the release), Go 1.27.4 (`GO_VERSION` of
the Dockerfile, checked by its SHA-256) and Python 3.13 (the `python3` of the
digest-pinned Debian trixie base, 3.13.5 when written); `measure.py` prints them
and stops when the image has another Python minor or Go version.

`measure.py` first builds the Go twins and compiles each Agentica program to
bytecode (`agentica compile`); neither is timed. Each program then runs on four
runners:

- `agentica`: the bytecode, `agentica run -- FILE.agcb`. The main column, as in
  agentica's own benchmarks.
- `agentica cold`: `agentica FILE.agc`, which runs the front end every time, the
  start-up a user sees (about 50 ms more).
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
most of the time; size 1 (`bench-check`) is for the outputs only. The programs
that write files (`read-lines`, `line-scan`, `bytes`) write them to the
container's `/tmp`, a 1 GB tmpfs: above size 20, raise it (`python3 bench/run.py
--tmpfs 4g ...`).

The twins follow their program, not the fastest Go: an ATS is a map behind a
lock, `Task.spawn` a goroutine, a channel a buffered channel of size 1. A
channel call or an await with a deadline (`recv(5000)`, `Task.await(t, 60000)`)
is a `select` on a timer that the goroutine resets for each call, with the same
deadline as the program (5 s in `channel-pingpong`, 1 s in `deadline-pingpong`,
60 s in `store-clients` and in the second phase of `sleepers`); the Python twins
pass the same timeouts to `queue`.

The ping-pong programs hand one value back and forth between two tasks, so they
measure the wake-up of the other task: Agentica's scheduler and Go's runtime do
it in very different ways, and Python's threads are far slower at it. In Go the
timer is most of the cost: at size 5, `deadline-pingpong` took 3.6 s, and the
same exchange with no deadline about 0.47 s (0.40 s with `GOMAXPROCS=1`). The
figure depends on the cost of Go's timers and of the futex calls that wake a
goroutine on another core, so on the kernel and the number of cores.

Go's `regexp` is RE2, which does not backtrack: the `(a+)+$` case of `regex` is
a backtracking blow-up for engines that backtrack, and a short linear scan in
Go.
