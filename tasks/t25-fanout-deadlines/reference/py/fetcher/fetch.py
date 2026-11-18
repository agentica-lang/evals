import asyncio
import json
import time

from fetcher.client import NoResponse, get
from fetcher.job import Job

LIMIT = 2**63


async def attempt(url: str, job: Job, budget_ms: float) -> tuple[int, bytes] | None:
    """One attempt: a request, a hedge after hedge_ms, the first response wins; None when every request failed."""
    timeout = min(job.request_timeout_ms, budget_ms)
    first = asyncio.create_task(get(url, max(1, int(timeout))))
    requests = [first]
    try:
        if job.hedge_ms > 0:
            done, _ = await asyncio.wait(requests, timeout=job.hedge_ms / 1000)
            if done and first.exception() is not None:
                return None
            if not done:
                requests.append(asyncio.create_task(get(url, max(1, int(min(job.request_timeout_ms, budget_ms - job.hedge_ms))))))
        pending = set(requests)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for request in done:
                if request.exception() is None:
                    return request.result()
        return None
    finally:
        for request in requests:
            request.cancel()


def describe(answer: tuple[int, bytes] | None) -> str:
    if answer is None:
        return "error no response"
    status, body = answer
    if status != 200:
        return f"error status {status}"
    try:
        data = json.loads(body)
    except ValueError:
        return "error body"
    value = data.get("value") if isinstance(data, dict) else None
    if type(value) is not int or not -LIMIT <= value < LIMIT:
        return "error body"
    return f"ok {value}"


async def fetch(url: str, job: Job, ends_at: float) -> str:
    backoff = job.backoff_ms
    for retry in range(job.retries + 1):
        answer = await attempt(url, job, (ends_at - time.monotonic()) * 1000)
        if answer is not None and not 500 <= answer[0] <= 599:
            break
        if retry < job.retries:
            await asyncio.sleep(backoff / 1000)
            backoff *= 2
    return describe(answer)


async def run(job: Job, began: float) -> list[str]:
    ends_at = began + job.deadline_ms / 1000
    results = ["error deadline"] * len(job.urls)
    slots = asyncio.Semaphore(job.concurrency)

    async def one(index: int, url: str) -> None:
        async with slots:
            results[index] = await fetch(url, job, ends_at)

    tasks = [asyncio.create_task(one(index, url)) for index, url in enumerate(job.urls)]
    if tasks:
        await asyncio.wait(tasks, timeout=max(0.0, ends_at - time.monotonic()))
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return results
