import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

SCHEMA = "create table if not exists todos (id integer primary key, title text not null)"
PRIORITY = "alter table todos add column priority integer not null default 2"


def migrate(db: sqlite3.Connection) -> None:
    db.execute(SCHEMA)
    columns = [row[1] for row in db.execute("pragma table_info(todos)")]
    if "priority" not in columns:
        db.execute(PRIORITY)


def todo(row: tuple[int, str, int]) -> dict[str, Any]:
    return {"id": row[0], "title": row[1], "priority": row[2]}


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
        path, _, query = self.path.partition("?")
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        if path != "/todos":
            return self.send_json(404, {"error": "not found"})
        with sqlite3.connect(self.database, isolation_level=None) as db:
            if method == "GET":
                return self.list_todos(db, query)
            if method == "POST":
                return self.create(db, raw)
        self.send_json(405, {"error": "method not allowed"})

    def list_todos(self, db: sqlite3.Connection, query: str) -> None:
        wanted = parse_qs(query, keep_blank_values=True).get("priority")
        if wanted is None:
            rows = db.execute("select id, title, priority from todos order by id").fetchall()
        elif wanted[0] in ("1", "2", "3"):
            rows = db.execute("select id, title, priority from todos where priority = ? order by id",
                              (int(wanted[0]),)).fetchall()
        else:
            return self.send_json(400, {"error": "invalid priority"})
        self.send_json(200, {"todos": [todo(row) for row in rows]})

    def create(self, db: sqlite3.Connection, raw: bytes) -> None:
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = None
        priority = body.get("priority", 2) if isinstance(body, dict) else None
        if (not isinstance(body, dict) or not isinstance(body.get("title"), str) or body["title"] == ""
                or type(priority) is not int or not 1 <= priority <= 3):
            return self.send_json(400, {"error": "invalid todo"})
        cursor = db.execute("insert into todos (title, priority) values (?, ?)", (body["title"], priority))
        self.send_json(201, todo((cursor.lastrowid or 0, body["title"], priority)))

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
        migrate(db)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(f"listening {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
