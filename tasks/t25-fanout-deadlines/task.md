# Task: fetch many URLs with a limit, timeouts, hedging and a deadline

Write a command line program that fetches a list of URLs over HTTP, many at
a time, and reports what happened to each one. It is a whole program; split it
into several files the way you would in a real project (the entry point is
`solution.agc`, or `solution.py` in Python).

## Input

The program takes one argument, the path of a job file, and reads nothing from
standard input. The job file is a JSON object:

```json
{"concurrency": 4, "request_timeout_ms": 400, "deadline_ms": 3000,
 "hedge_ms": 150, "retries": 2, "backoff_ms": 50,
 "urls": ["http://127.0.0.1:8000/a", "http://127.0.0.1:8000/b"]}
```

Every field is required. `concurrency` is at least 1; `request_timeout_ms`,
`deadline_ms` and `backoff_ms` are at least 1; `hedge_ms` and `retries` are at
least 0 (`hedge_ms` 0 means no hedging); all are integers (not booleans or
decimals). `urls` is a list of strings (it may be empty), each an `http://`
URL. Other fields are ignored. When the file cannot be read, is not JSON, or a
field is missing or wrong, the program prints `error: bad job file` and exits
with status 2, fetching nothing.

## Fetching

Each URL is fetched with `GET` requests, without a body. Redirects are not
followed: a `3xx` answer is a status like any other. The program works on
at most `concurrency` URLs at the same time. When one URL is done, the next
one in the list starts.

A URL is fetched in **attempts**. An attempt sends one request. If no response
has come after `hedge_ms` (and `hedge_ms` is above 0), it sends a second,
identical request (a hedge) for the same URL, while the first goes on. The
attempt ends with the first response that either request gets, whatever its
status, and the other request is cancelled at once: its connection is closed
without waiting for its answer. If the first request fails before `hedge_ms`,
the attempt got no response, and no hedge is sent. A request that gets no
response (it times out,
or the connection fails or is closed) does not end the attempt while the other
request is still going; when every request of the attempt has failed, the
attempt got no response.

A request times out when its whole response (head and body) has not arrived
within `request_timeout_ms` of sending it.

An attempt that ends with a status from 500 to 599, or with no response, is
retried: after `backoff_ms`, then `2 * backoff_ms`, then `4 * backoff_ms` and so
on, up to `retries` more attempts. Any other status ends the URL.

The whole run has a deadline: `deadline_ms` after the program starts. When it
passes, every request still going is cancelled, every URL not done gets the
result `error deadline` (also one waiting for a retry or not started yet), and
the program prints its report and exits at once. A run never takes much longer
than `deadline_ms`.

## Results and output

The result of a URL is, from its last attempt:

- status 200 and a body that is a JSON object whose `value` is an integer
  that fits in a signed 64-bit integer (not a boolean or a decimal such as
  `3.0`): `ok VALUE`;
- status 200 and any other body: `error body`;
- another status: `error status CODE`;
- no response: `error no response`;
- not done by the deadline: `error deadline`.

The program prints one line per URL, in the order of the list, as `N RESULT`
with `N` counting from 1, then one line `ok K of M`, where `K` is the number of
`ok` results and `M` the number of URLs. It exits with status 0. Example:

```text
1 ok 5
2 error status 404
3 error no response
4 error deadline
ok 1 of 4
```
