import http.client
import contextlib
import json
import os
import re
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time

# A case is a script of lines: `METHOD PATH [BODY]` sends a request, `SQL STATEMENT` runs a statement on the
# database file from outside the service, `TABLE` prints the notes table as the file holds it, and `RESTART` stops the
# service and starts it again on the same file.


def read_port(proc):
    deadline = time.time() + 30
    buffer = b""
    while time.time() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.2)
        if ready:
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                return None
            buffer += chunk
            found = re.search(rb"^listening (\d+)\r?$", buffer, re.MULTILINE)
            if found:
                return int(found.group(1))
        if proc.poll() is not None:
            return None
    return None


def shown_body(media, raw):
    text = raw.decode("utf-8", "replace")
    if media == "application/json":
        try:
            return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
        except ValueError:
            pass
    return "<not json: " + repr(text[:60]) + ">"


def request(port, line):
    method, _, rest = line.partition(" ")
    path, _, body = rest.partition(" ")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {"Content-Type": "application/json"} if body else {}
        connection.request(method, path, body=body.encode() if body else None, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        if response.status == 405:
            return f"{method} {path} -> 405"
        media = (response.getheader("Content-Type") or "-").split(";")[0].strip().lower()
        return f"{method} {path} -> {response.status} {media} {shown_body(media, raw)}"
    except (OSError, http.client.HTTPException):
        return f"{method} {path} -> no response"
    finally:
        connection.close()


def start(command, database):
    proc = subprocess.Popen(command + [database], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    return proc, read_port(proc)


def stop(proc, errors):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    errors.append(proc.stderr.read().decode("utf-8", "replace"))


def table(database):
    try:
        with contextlib.closing(sqlite3.connect(database, timeout=0)) as db:
            rows = db.execute("select id, title, body from notes order by id").fetchall()
    except sqlite3.Error as exc:
        return f"table: error {exc}"
    return "table: " + json.dumps(rows, separators=(",", ":"))


def outside(database, statement):
    """Runs a statement on the file as another program would. It does not wait for a lock (timeout 0): a service
    commits each change before it answers, so the file is never locked between requests."""
    try:
        with contextlib.closing(sqlite3.connect(database, timeout=0, isolation_level=None)) as db:
            db.execute(statement)
    except sqlite3.Error as exc:
        return f"sql: error {exc}"
    return "sql: ok"


def main():
    script = [line for line in sys.argv[1].splitlines() if line.strip()]
    command = sys.argv[2:]
    errors = []
    with tempfile.TemporaryDirectory() as directory:
        database = os.path.join(directory, "notes.db")
        proc, port = start(command, database)
        for line in script:
            if port is None:
                print("error: the server did not announce a port")
                break
            if line == "RESTART":
                stop(proc, errors)
                proc, port = start(command, database)
                print("restarted")
            elif line == "TABLE":
                print(table(database))
            elif line.startswith("SQL "):
                print(outside(database, line[4:]))
            else:
                print(request(port, line))
        stop(proc, errors)
    sys.stderr.write("".join(errors))


main()
