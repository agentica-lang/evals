import json
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SCHEMA = [
    "create table if not exists customers (id integer primary key, name text not null unique)",
    "create table if not exists orders (id integer primary key, customer_id integer not null references customers (id), "
    "item text not null, quantity integer not null, cents integer not null)",
]
CUSTOMER_ORDERS = re.compile(r"/customers/([^/]+)/orders")


def order(row: tuple[int, str, str, int, int]) -> dict[str, Any]:
    return {"id": row[0], "customer": row[1], "item": row[2], "quantity": row[3], "cents": row[4]}


def whole(value: object, least: int) -> bool:
    return type(value) is int and value >= least


def valid_order(body: object) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("customer"), str) and body["customer"] != ""
            and isinstance(body.get("item"), str) and body["item"] != ""
            and whole(body.get("quantity"), 1) and whole(body.get("cents"), 0))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    database = ""

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: int, value: dict[str, Any]) -> None:
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def route(self, method: str) -> None:
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        found = CUSTOMER_ORDERS.fullmatch(path)
        wanted = "POST" if path == "/orders" else "GET" if found or path == "/report" else None
        if wanted is None:
            return self.send_json(404, {"error": "not found"})
        if method != wanted:
            return self.send_json(405, {"error": "method not allowed"})
        with sqlite3.connect(self.database, isolation_level=None) as db:
            if path == "/orders":
                return self.create(db, raw)
            if found:
                return self.customer(db, found.group(1))
            self.report(db)

    def create(self, db: sqlite3.Connection, raw: bytes) -> None:
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = None
        if not valid_order(body):
            return self.send_json(400, {"error": "invalid order"})
        db.execute("insert or ignore into customers (name) values (?)", (body["customer"],))
        customer_id = db.execute("select id from customers where name = ?", (body["customer"],)).fetchone()[0]
        cursor = db.execute("insert into orders (customer_id, item, quantity, cents) values (?, ?, ?, ?)",
                            (customer_id, body["item"], body["quantity"], body["cents"]))
        self.send_json(201, order((cursor.lastrowid or 0, body["customer"], body["item"], body["quantity"],
                                   body["cents"])))

    def customer(self, db: sqlite3.Connection, name: str) -> None:
        if db.execute("select id from customers where name = ?", (name,)).fetchone() is None:
            return self.send_json(404, {"error": "not found"})
        rows = db.execute("select o.id, c.name, o.item, o.quantity, o.cents from orders o "
                          "join customers c on c.id = o.customer_id where c.name = ? order by o.id", (name,)).fetchall()
        self.send_json(200, {"customer": name, "orders": [order(row) for row in rows],
                             "total_cents": sum(row[3] * row[4] for row in rows)})

    def report(self, db: sqlite3.Connection) -> None:
        rows = db.execute("select c.name, count(*), sum(o.quantity * o.cents) as total from orders o "
                          "join customers c on c.id = o.customer_id group by c.id order by total desc, c.name").fetchall()
        self.send_json(200, {"customers": [{"customer": name, "orders": count, "total_cents": total}
                                           for name, count, total in rows]})

    def do_GET(self) -> None:
        self.route("GET")

    def do_POST(self) -> None:
        self.route("POST")

    def do_PUT(self) -> None:
        self.route("PUT")

    def do_DELETE(self) -> None:
        self.route("DELETE")


def main() -> None:
    Handler.database = sys.argv[1]
    with sqlite3.connect(Handler.database, isolation_level=None) as db:
        for statement in SCHEMA:
            db.execute(statement)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(f"listening {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
