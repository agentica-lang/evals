import sys
from pathlib import Path

from conf.errors import ConfError
from conf.loader import Loader
from conf.output import to_json


def main() -> int:
    sys.setrecursionlimit(20000)
    path = Path(sys.argv[1])
    loader = Loader(path.parent)
    try:
        text = loader.read(path.name)
        if text is None:
            raise ConfError("E-IMPORT-READ", 1, 1, path.name)
        out = to_json(loader.load(path.name, text, [path.name]))
    except ConfError as error:
        out = f"error {error.code} at {error.file}:{error.line}:{error.col}"
        sys.stdout.buffer.write(out.encode() + b"\n")
        return 1
    sys.stdout.buffer.write(out.encode() + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
