# Task: a notes API on a database

`start.agc` (or `start.py` for Python) is the start of a small JSON API for
notes, kept in a SQLite database. It opens the database and answers
`GET /health`, and nothing else yet. Finish it and save the result as
`solution.agc` (or `solution.py`).

In Agentica use the Bond web framework (`import Bond from "pkg/bond/bond"`) and
agentica-db (`import Db from "pkg/db/db"`, `import Sqlite from "pkg/db/sqlite"`),
which are installed in `deps/` (`agentica.toml` and `agentica.lock` list them).
In Python use the standard library (`http.server` and `sqlite3`).

## How the service starts

It takes one argument, the path of the SQLite database file, and creates the
file and the table when they do not exist:

```sql
create table if not exists notes (id integer primary key, title text not null, body text not null)
```

It listens on `127.0.0.1` with a port the system picks (port 0). Once it is
listening it prints one line, `listening PORT`, with the real port, and flushes
it. Then it serves requests until it is killed. It reads nothing from standard
input.

Every request reads and writes the database: other programs may change the
table while the service runs, and a service started again on the same file finds
the notes it had.

## The routes

Every response, except a `405`, has the header `Content-Type: application/json`
and a JSON object as its body. A note is `{"id":ID,"title":"TITLE","body":"BODY"}`.

- `GET /health`: `200` with `{"status":"ok"}`.
- `POST /notes`: the request body is a JSON object with `title`, a non-empty
  string, and `body`, a string (it may be empty); other keys are ignored. The
  note is inserted, and the answer is `201` with the new note (its `id` is the
  one SQLite gives). A body that is not JSON, not an object, or has a missing or
  wrong `title` or `body` is `400` with `{"error":"invalid note"}`, and nothing
  is inserted.
- `GET /notes`: `200` with `{"notes":[...]}`, every note, by `id` ascending.
- `GET /notes/ID`: `200` with the note, or `404` with `{"error":"not found"}`
  when there is no such note or `ID` is not a number.
- `DELETE /notes/ID`: deletes the note, `200` with `{"deleted":ID}`; `404` with
  `{"error":"not found"}` as for `GET`.
- Any other path: `404` with `{"error":"not found"}`.
- `/health`, `/notes` or `/notes/ID` with another method: `405` (the body does
  not matter).

The service must keep serving after any bad request.

Example, with the service on port 40001:

```text
POST /notes {"title":"milk","body":"2 liters"}  ->  201  {"id":1,"title":"milk","body":"2 liters"}
POST /notes {"title":""}                        ->  400  {"error":"invalid note"}
GET /notes/1                                    ->  200  {"id":1,"title":"milk","body":"2 liters"}
DELETE /notes/7                                 ->  404  {"error":"not found"}
```

Test it against your own client before you finish (a few requests with `curl`,
if it is installed, or a short script).
