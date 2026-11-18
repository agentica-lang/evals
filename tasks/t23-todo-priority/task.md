# Task: add a column to a live database

`start.agc` (or `start.py` for Python) is a small JSON API for todos, kept in a
SQLite database. Todos now get a priority. Change the service as below and save
the result as `solution.agc` (or `solution.py`).

In Agentica it uses the Bond web framework (`pkg/bond/bond`) and agentica-db
(`pkg/db/db`, `pkg/db/sqlite`), which are installed in `deps/`. In Python it
uses the standard library (`http.server` and `sqlite3`).

## How the service starts

It takes one argument, the path of the SQLite database file. It listens on
`127.0.0.1` with a port the system picks (port 0), prints one line,
`listening PORT`, with the real port, flushes it, and serves requests until it
is killed. Every request reads and writes the database, and a change is
committed before its answer is sent.

Today it creates the table when it does not exist:

```sql
create table if not exists todos (id integer primary key, title text not null)
```

## The change

- The `todos` table gets a column `priority integer not null default 2`. The
  service is started on databases that already have todos, made by the old
  version: it adds the column there, and their todos get priority 2. A new
  database gets the table with the column. Starting the service again on the
  same file works and changes nothing. Other tables may be added (for example
  to record the schema version).
- A todo is `{"id":ID,"title":"TITLE","priority":P}` in every answer.
- `POST /todos`: the body is a JSON object with `title`, a non-empty string,
  and an optional `priority`, an integer from 1 to 3 (not a boolean, not a
  decimal), 2 when it is missing; other keys are ignored. The answer is `201`
  with the new todo. Any other body is `400` with `{"error":"invalid todo"}`,
  and nothing is inserted.
- `GET /todos`: `200` with `{"todos":[...]}`, by `id` ascending, as before.
  With the query `?priority=P` (`P` is `1`, `2` or `3`) it lists only the todos
  of that priority. Any other value of `priority` (also an empty one) is `400`
  with `{"error":"invalid priority"}`. Other query parameters are ignored.

Unchanged:

- Every response, except a `405`, has the header
  `Content-Type: application/json` and a JSON object as its body.
- Any other path is `404` with `{"error":"not found"}`; `/todos` with another
  method is `405` (the body does not matter).
- The service keeps serving after any bad request.

Test it against your own client before you finish, also on a database made by
the start program.
