import asyncio
import sys
import time

from fetcher.fetch import run
from fetcher.job import BadJob, load_job


def main() -> int:
    began = time.monotonic()
    try:
        job = load_job(sys.argv[1])
    except (BadJob, IndexError):
        print("error: bad job file")
        return 2
    results = asyncio.run(run(job, began))
    for number, result in enumerate(results, 1):
        print(f"{number} {result}")
    print(f"ok {sum(result.startswith('ok ') for result in results)} of {len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
