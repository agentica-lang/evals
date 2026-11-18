import http.server
import json
import os
import select
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

# A case is a script of lines:
#   job KEY=VALUE ...            the job fields (urls come from the `url` lines)
#   url NAME STEP STEP ...       a path /NAME; request k of it gets step k (the last step repeats)
#   raw TEXT                     the job file is TEXT as it is (no backend)
#   check concurrency|deadline|requests|cancelled NAME
# A step is ok:V (200 {"value":V}), status:C, body:TEXT, delay:MS:STEP, drip:STEP (the body a byte per 100 ms),
# hang, or reset (closes the connection at once).
# The driver prints the program's output, its exit status and one line per check.


class State:
    def __init__(self, scripts):
        self.scripts = scripts
        self.lock = threading.Lock()
        self.counts = {}
        self.active = {}
        self.most_active = 0
        self.cancelled = {}

    def begin(self, name):
        with self.lock:
            index = self.counts.get(name, 0)
            self.counts[name] = index + 1
            self.active[name] = self.active.get(name, 0) + 1
            self.most_active = max(self.most_active, sum(1 for n in self.active.values() if n))
            steps = self.scripts.get(name, ["status:404"])
            return steps[min(index, len(steps) - 1)]

    def end(self, name, cancelled):
        with self.lock:
            self.active[name] -= 1
            if cancelled:
                self.cancelled[name] = self.cancelled.get(name, 0) + 1


def closed_by_client(connection):
    ready, _, _ = select.select([connection], [], [], 0)
    if not ready:
        return False
    try:
        return connection.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def wait(self, milliseconds):
        """Sleeps, and returns True when the client closed the connection meanwhile."""
        end = time.monotonic() + milliseconds / 1000
        while time.monotonic() < end:
            if closed_by_client(self.connection):
                return True
            time.sleep(0.01)
        return False

    def do_GET(self):
        name = self.path.lstrip("/")
        step = self.server.state.begin(name)
        cancelled = False
        try:
            cancelled = self.serve(step)
        except OSError:
            cancelled = True
        finally:
            self.server.state.end(name, cancelled)
            self.close_connection = True

    def serve(self, step, drip=False):
        kind, _, rest = step.partition(":")
        if kind == "delay":
            milliseconds, _, inner = rest.partition(":")
            return self.wait(int(milliseconds)) or self.serve(inner, drip)
        if kind == "drip":
            return self.serve(rest, True)
        if kind == "hang":
            return self.wait(30000)
        if kind == "reset":
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
            self.connection.close()
            return False
        status, body = 200, b""
        if kind == "ok":
            body = json.dumps({"value": int(rest)}).encode()
        elif kind == "status":
            status, body = int(rest), b'{"error":"status"}'
        elif kind == "body":
            body = rest.encode()
        self.send_response(status)
        if 300 <= status < 400:
            self.send_header("Location", "/redirected")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not drip:
            self.wfile.write(body)
            return False
        for byte in body:
            if self.wait(100):
                return True
            self.wfile.write(bytes([byte]))
            self.wfile.flush()
        return False


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


def refused_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def main():
    lines = [line for line in sys.argv[1].splitlines() if line.strip()]
    command = sys.argv[2:]
    scripts, job, raw, checks = {}, {}, None, []
    for line in lines:
        word, _, rest = line.partition(" ")
        if word == "job":
            for pair in rest.split():
                key, _, value = pair.partition("=")
                job[key] = json.loads(value)
        elif word == "url":
            name, *steps = rest.split(" ")
            scripts[name] = steps
        elif word == "raw":
            raw = rest
        elif word == "check":
            checks.append(rest.split())
    state = State(scripts)
    server = Server(("127.0.0.1", 0), Handler)
    server.state = state
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    # A name starting with `refused` points at a port where nothing listens.
    job["urls"] = [f"http://127.0.0.1:{refused_port() if name.startswith('refused') else port}/{name}"
                   for name in scripts]
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "job.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(raw if raw is not None else json.dumps(job))
        deadline = job.get("deadline_ms", 3000)
        began = time.monotonic()
        try:
            done = subprocess.run(command + [path], stdin=subprocess.DEVNULL, capture_output=True,
                                  timeout=deadline / 1000 + 10)
        except subprocess.TimeoutExpired:
            print("the program did not finish")
            return
        took = (time.monotonic() - began) * 1000
    time.sleep(0.2)
    server.shutdown()
    sys.stdout.write(done.stdout.decode("utf-8", "replace"))
    print(f"exit {done.returncode}")
    for check in checks:
        if check[0] == "concurrency":
            print(f"at most {job['concurrency']} URLs in flight: {'yes' if state.most_active <= job['concurrency'] else 'no'}")
        elif check[0] == "deadline":
            print(f"finished within the deadline: {'yes' if took <= deadline + 1000 else 'no'}")
        elif check[0] == "requests":
            print("requests: " + " ".join(f"{name}={state.counts.get(name, 0)}" for name in scripts))
        elif check[0] == "cancelled":
            print(f"a slow request to /{check[1]} was cancelled: {'yes' if state.cancelled.get(check[1]) else 'no'}")
    sys.stderr.write(done.stderr.decode("utf-8", "replace"))


main()
