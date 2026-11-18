# Task: repair an orders API

`start.agc` (or `start.py` for Python) is a small JSON API for the orders of a
shop, kept in a SQLite database, and it does not meet its spec. Fix it and save
the result as `solution.agc` (or `solution.py`).

In Agentica it uses the Bond web framework (`pkg/bond/bond`) and agentica-db
(`pkg/db/db`, `pkg/db/sqlite`), which are installed in `deps/`. In Python it
uses the standard library (`http.server` and `sqlite3`).

## How the service starts

It takes one argument, the path of the SQLite database file, and creates the
file and the tables when they do not exist:

```sql
create table if not exists customers (id integer primary key, name text not null unique)
create table if not exists orders (id integer primary key, customer_id integer not null references customers (id), item text not null, quantity integer not null, cents integer not null)
```

It listens on `127.0.0.1` with a port the system picks (port 0), prints one
line, `listening PORT`, with the real port, flushes it, and serves requests
until it is killed. Every request reads and writes the database: other programs
may change the tables while the service runs. A change is committed before its
answer is sent.

## The routes

Every response, except a `405`, has the header `Content-Type: application/json`
and a JSON object as its body. An order is
`{"id":ID,"customer":"NAME","item":"ITEM","quantity":Q,"cents":C}`; `cents` is
the price of one unit.

- `POST /orders`: the body is a JSON object with `customer` and `item`, two
  non-empty strings, `quantity`, an integer of at least 1, and `cents`, an
  integer of at least 0 (integers only: not booleans, not decimals); other keys
  are ignored. The customer is the row of `customers` with that name, inserted
  when there is none, so a name has one row. The order is inserted, and the
  answer is `201` with the new order. Any other body is `400` with
  `{"error":"invalid order"}`, and nothing is inserted.
- `GET /customers/NAME/orders`: `200` with
  `{"customer":"NAME","orders":[...],"total_cents":T}`: the orders of that
  customer by `id` ascending, and the sum of `quantity * cents` over them. A
  name with no row in `customers` is `404` with `{"error":"not found"}`. Names
  may hold any character but `/`, `?`, `%` and spaces, the quote `'` too.
- `GET /report`: `200` with `{"customers":[...]}`, one entry
  `{"customer":"NAME","orders":N,"total_cents":T}` per customer with at least
  one order, by `total_cents` descending, then by name ascending.
- Any other path: `404` with `{"error":"not found"}`.
- `/orders`, `/customers/NAME/orders` or `/report` with another method: `405`
  (the body does not matter).

The service must keep serving after any bad request.

Test it against your own client before you finish (a few requests with `curl`,
if it is installed, or a short script).
