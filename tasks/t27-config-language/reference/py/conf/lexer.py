from dataclasses import dataclass, field

from conf.errors import ConfError

KEYWORDS = {"import", "as", "let", "if", "then", "else", "true", "false"}
PAIRS = {"==", "!=", "<=", ">=", "&&", "||"}
SINGLES = set("=+-*/()[]{},.<>!")
ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "$": "$"}
MAX_INT = 2**63 - 1


@dataclass
class Ref:
    name: str
    line: int
    col: int
    dollar_col: int


@dataclass
class Token:
    kind: str  # name, kw, int, str, sym, nl, eof
    text: str
    line: int
    col: int
    number: int = 0
    parts: list[str | Ref] = field(default_factory=list)

    def is_(self, text: str) -> bool:
        return self.kind in ("sym", "kw") and self.text == text


def is_name_start(c: str) -> bool:
    return c.isascii() and (c.isalpha() or c == "_")


def is_name_char(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i, line, col = 0, 1, 1
    while i < len(text):
        c = text[i]
        if c == "\n":
            tokens.append(Token("nl", c, line, col))
            i, line, col = i + 1, line + 1, 1
        elif c in " \t":
            i, col = i + 1, col + 1
        elif c == "#":
            while i < len(text) and text[i] != "\n":
                i, col = i + 1, col + 1
        elif is_name_start(c):
            j = i
            while j < len(text) and is_name_char(text[j]):
                j += 1
            word = text[i:j]
            tokens.append(Token("kw" if word in KEYWORDS else "name", word, line, col))
            i, col = j, col + j - i
        elif c.isascii() and c.isdigit():
            j = i
            while j < len(text) and text[j].isascii() and text[j].isdigit():
                j += 1
            digits = text[i:j].lstrip("0") or "0"
            # Checked by length first: int() refuses very long digit strings.
            number = int(digits) if len(digits) <= 19 else MAX_INT + 1
            if number > MAX_INT:
                raise ConfError("E-NUMBER", line, col)
            tokens.append(Token("int", text[i:j], line, col, number=number))
            i, col = j, col + j - i
        elif c == '"':
            token, i = read_string(text, i, line, col)
            tokens.append(token)
            col += len(token.text)
        elif text[i:i + 2] in PAIRS:
            tokens.append(Token("sym", text[i:i + 2], line, col))
            i, col = i + 2, col + 2
        elif c in SINGLES:
            tokens.append(Token("sym", c, line, col))
            i, col = i + 1, col + 1
        else:
            raise ConfError("E-CHAR", line, col)
    lines = text.count("\n") + (0 if text == "" or text.endswith("\n") else 1)
    tokens.append(Token("eof", "", lines + 1, 1))
    return tokens


def read_string(text: str, start: int, line: int, col: int) -> tuple[Token, int]:
    parts: list[str | Ref] = []
    chunk: list[str] = []
    i = start + 1
    while True:
        here = col + i - start
        if i >= len(text) or text[i] == "\n":
            raise ConfError("E-STRING", line, col)
        c = text[i]
        if c == '"':
            break
        if c == "\\":
            escaped = text[i + 1] if i + 1 < len(text) else ""
            if escaped not in ESCAPES:
                raise ConfError("E-ESCAPE", line, here)
            chunk.append(ESCAPES[escaped])
            i += 2
        elif c == "$" and text[i + 1:i + 2] == "{":
            j = i + 2
            if j < len(text) and is_name_start(text[j]):
                j += 1
                while j < len(text) and is_name_char(text[j]):
                    j += 1
            name = text[i + 2:j]
            if not name or name in KEYWORDS or text[j:j + 1] != "}":
                raise ConfError("E-ESCAPE", line, here)
            parts.append("".join(chunk))
            chunk = []
            parts.append(Ref(name, line, here + 2, here))
            i = j + 1
        else:
            chunk.append(c)
            i += 1
    parts.append("".join(chunk))
    return Token("str", text[start:i + 1], line, col, parts=parts), i + 1
