import json
from dataclasses import dataclass

INT_FIELDS = {"concurrency": 1, "request_timeout_ms": 1, "deadline_ms": 1, "hedge_ms": 0, "retries": 0, "backoff_ms": 1}


class BadJob(Exception):
    pass


@dataclass(frozen=True)
class Job:
    concurrency: int
    request_timeout_ms: int
    deadline_ms: int
    hedge_ms: int
    retries: int
    backoff_ms: int
    urls: list[str]


def load_job(path: str) -> Job:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise BadJob() from exc
    if not isinstance(data, dict):
        raise BadJob()
    values: dict[str, int] = {}
    for name, least in INT_FIELDS.items():
        value = data.get(name)
        if type(value) is not int or value < least:
            raise BadJob()
        values[name] = value
    urls = data.get("urls")
    if not isinstance(urls, list) or not all(isinstance(url, str) and url.startswith("http://") for url in urls):
        raise BadJob()
    return Job(urls=urls, **values)
