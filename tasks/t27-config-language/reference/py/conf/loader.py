import re
from pathlib import Path

from conf.checker import check
from conf.errors import ConfError
from conf.evaluator import Value, evaluate
from conf.lexer import Ref, tokenize
from conf.parser import parse
from conf.syntax import Import

PART = re.compile(r"[A-Za-z0-9_.-]+")


class Loader:
    """Loads files under one folder; a file's name is its path relative to that folder, with `/`."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.values: dict[str, dict[str, Value]] = {}

    def read(self, name: str) -> str | None:
        try:
            return (self.folder / name).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def load(self, name: str, text: str, stack: list[str]) -> dict[str, Value]:
        try:
            file = parse(tokenize(text))
            imported: dict[str, Value] = {}
            for item in file.imports:
                imported[item.name.text] = self.load_import(name, item, stack)
            check(file)
            value = evaluate(file, imported)
        except ConfError as error:
            if error.file is None:
                error.file = name
            raise
        self.values[name] = value
        return value

    def load_import(self, importer: str, item: Import, stack: list[str]) -> dict[str, Value]:
        token = item.path
        path = "".join(part for part in token.parts if isinstance(part, str))
        parts = path.split("/")
        if (any(isinstance(part, Ref) for part in token.parts) or not path.endswith(".conf")
                or any(not PART.fullmatch(part) or part in (".", "..") for part in parts)):
            raise ConfError("E-IMPORT-PATH", token.line, token.col)
        name = "/".join([*importer.split("/")[:-1], *parts])
        if name in stack:
            raise ConfError("E-IMPORT-CYCLE", token.line, token.col)
        if name in self.values:
            return self.values[name]
        text = self.read(name)
        if text is None:
            raise ConfError("E-IMPORT-READ", token.line, token.col)
        return self.load(name, text, [*stack, name])
