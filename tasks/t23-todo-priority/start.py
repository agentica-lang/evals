import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SCHEMA = "create table if not exists todos (id integer primary key, title text not null)"


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
        if path != "/todos":
            return self.send_json(404, {"error": "not found"})
        with sqlite3.connect(self.database, isolation_level=None) as db:
            if method == "GET":
                return self.list_todos(db)
            if method == "POST":
                return self.create(db, raw)
        self.send_json(405, {"error": "method not allowed"})

    def list_todos(self, db: sqlite3.Connection) -> None:
        rows = db.execute("select id, title from todos order by id").fetchall()
        self.send_json(200, {"todos": [{"id": row[0], "title": row[1]} for row in rows]})

    def create(self, db: sqlite3.Connection, raw: bytes) -> None:
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("title"), str) or body["title"] == "":
            return self.send_json(400, {"error": "invalid todo"})
        cursor = db.execute("insert into todos (title) values (?)", (body["title"],))
        self.send_json(201, {"id": cursor.lastrowid, "title": body["title"]})

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
        db.execute(SCHEMA)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(f"listening {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
