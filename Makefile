# The benchmark twins (bench/): the Agentica programs of the pinned commit against Python and Go, in the
# evaluation image. RUNS and SIZE pass on to bench/run.py.
RUNS ?= 5
SIZE ?= 1

.PHONY: bench bench-check image

image:
	docker build --tag agentica-eval:local .

bench:
	python3 bench/run.py --runs $(RUNS) --size $(SIZE)

bench-check:
	python3 bench/run.py --check
