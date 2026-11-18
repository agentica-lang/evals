import json
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SCHEMA = "create table if not exists notes (id integer primary key, title text not null, body text not null)"
NOTE_PATH = re.compile(r"/notes/([^/]*)")


def note(row: tuple[int, str, str]) -> dict[str, Any]:
    return {"id": row[0], "title": row[1], "body": row[2]}


def note_id(text: str) -> int | None:
    return int(text) if re.fullmatch(r"[0-9]+", text) else None


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

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database)

    def route(self, method: str) -> None:
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        found = NOTE_PATH.fullmatch(path)
        if path == "/health":
            if method != "GET":
                return self.send_json(405, {"error": "method not allowed"})
            return self.send_json(200, {"status": "ok"})
        if path == "/notes":
            if method == "GET":
                return self.list_notes()
            if method == "POST":
                return self.create(raw)
            return self.send_json(405, {"error": "method not allowed"})
        if found:
            if method not in ("GET", "DELETE"):
                return self.send_json(405, {"error": "method not allowed"})
            return self.one(method, note_id(found.group(1)))
        self.send_json(404, {"error": "not found"})

    def list_notes(self) -> None:
        with self.connect() as db:
            rows = db.execute("select id, title, body from notes order by id").fetchall()
        self.send_json(200, {"notes": [note(row) for row in rows]})

    def create(self, raw: bytes) -> None:
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = None
        if (not isinstance(body, dict) or not isinstance(body.get("title"), str) or body["title"] == ""
                or not isinstance(body.get("body"), str)):
            return self.send_json(400, {"error": "invalid note"})
        with self.connect() as db:
            cursor = db.execute("insert into notes (title, body) values (?, ?)", (body["title"], body["body"]))
            new_id = cursor.lastrowid
        self.send_json(201, {"id": new_id, "title": body["title"], "body": body["body"]})

    def one(self, method: str, wanted: int | None) -> None:
        with self.connect() as db:
            row = None if wanted is None else db.execute(
                "select id, title, body from notes where id = ?", (wanted,)).fetchone()
            if row is None:
                return self.send_json(404, {"error": "not found"})
            if method == "DELETE":
                db.execute("delete from notes where id = ?", (wanted,))
                return self.send_json(200, {"deleted": wanted})
        self.send_json(200, note(row))

    def do_GET(self) -> None:
        self.route("GET")

    def do_POST(self) -> None:
        self.route("POST")

    def do_PUT(self) -> None:
        self.route("PUT")

    def do_PATCH(self) -> None:
        self.route("PATCH")

    def do_DELETE(self) -> None:
        self.route("DELETE")


def main() -> None:
    Handler.database = sys.argv[1]
    with sqlite3.connect(Handler.database) as db:
        db.execute(SCHEMA)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(f"listening {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
