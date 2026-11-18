import os
import subprocess
import sys
import tempfile

# A case is files: a line `=== PATH` starts the file PATH, and the lines up to the next such line are its text (each
# line ends with a newline). The program runs on main.conf; the driver prints its output and its exit status.


def main():
    files, name = {}, None
    for line in sys.argv[1].removesuffix("\n").split("\n"):
        if line.startswith("=== "):
            name = line[4:].strip()
            files[name] = ""
        elif name is not None:
            files[name] += line + "\n"
    with tempfile.TemporaryDirectory() as directory:
        for name, text in files.items():
            path = os.path.join(directory, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
        try:
            done = subprocess.run(sys.argv[2:] + [os.path.join(directory, "main.conf")], stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=20)
        except subprocess.TimeoutExpired:
            print("the program did not finish")
            return
    sys.stdout.write(done.stdout.decode("utf-8", "replace"))
    print(f"exit {done.returncode}")
    sys.stderr.write(done.stderr.decode("utf-8", "replace"))
    sys.stderr.write(f"PROGRAM-EXIT {done.returncode}\n")


main()
