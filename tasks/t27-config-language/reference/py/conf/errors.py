from dataclasses import dataclass


@dataclass
class ConfError(Exception):
    code: str
    line: int
    col: int
    file: str | None = None
