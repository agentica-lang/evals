from conf.errors import ConfError
from conf.lexer import Ref, Token
from conf.syntax import Binary, Expr, Field, File, If, Item, ListOf, Literal, Name, Record, Statement, Unary

type Value = int | str | bool | list["Value"] | dict[str, "Value"]

MIN_INT, MAX_INT = -(2**63), 2**63 - 1
TYPES = {int: "int", str: "string", bool: "bool", list: "list", dict: "record"}


def kind(value: Value) -> str:
    return TYPES[type(value)]


def at(code: str, token: Token) -> ConfError:
    return ConfError(code, token.line, token.col)


def evaluate(file: File, imported: dict[str, Value]) -> dict[str, Value]:
    return statements(file.statements, [dict(imported)])


def statements(items: list[Statement], scopes: list[dict[str, Value]]) -> dict[str, Value]:
    entries: dict[str, Value] = {}
    for statement in items:
        value = expr(statement.value, scopes)
        (scopes[-1] if statement.is_let else entries)[statement.name.text] = value
    return entries


def lookup(name: str, scopes: list[dict[str, Value]]) -> Value:
    return next(scope[name] for scope in reversed(scopes) if name in scope)


def equal(a: Value, b: Value) -> bool:
    if kind(a) != kind(b):
        return False
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[key], b[key]) for key in a)
    return a == b


def checked(value: int, token: Token) -> int:
    if not MIN_INT <= value <= MAX_INT:
        raise at("E-OVERFLOW", token)
    return value


def text_of(token: Token, scopes: list[dict[str, Value]]) -> str:
    out = []
    for part in token.parts:
        if isinstance(part, Ref):
            value = lookup(part.name, scopes)
            if isinstance(value, (list, dict)):
                raise ConfError("E-TYPE", part.line, part.dollar_col)
            out.append(str(value).lower() if isinstance(value, bool) else str(value))
        else:
            out.append(part)
    return "".join(out)


def expr(node: Expr, scopes: list[dict[str, Value]]) -> Value:
    match node:
        case Literal(token):
            if token.kind == "int":
                return token.number
            if token.kind == "str":
                return text_of(token, scopes)
            return token.text == "true"
        case Name(token):
            return lookup(token.text, scopes)
        case ListOf(_, items):
            return [expr(item, scopes) for item in items]
        case Record(_, inner):
            return statements(inner, [*scopes, {}])
        case Unary(token, operand):
            value = expr(operand, scopes)
            if token.text == "-" and isinstance(value, int) and not isinstance(value, bool):
                return checked(-value, token)
            if token.text == "!" and isinstance(value, bool):
                return not value
            raise at("E-TYPE", token)
        case Binary(token, left, right):
            return binary(token, left, right, scopes)
        case If(token, condition, then, otherwise):
            test = expr(condition, scopes)
            if not isinstance(test, bool):
                raise at("E-TYPE", token)
            return expr(then if test else otherwise, scopes)
        case Field(token, target, name):
            record = expr(target, scopes)
            if not isinstance(record, dict):
                raise at("E-TYPE", token)
            if name.text not in record:
                raise at("E-FIELD", name)
            return record[name.text]
        case Item(token, target, index):
            listed, position = expr(target, scopes), expr(index, scopes)
            if not isinstance(listed, list) or kind(position) != "int":
                raise at("E-TYPE", token)
            assert isinstance(position, int)
            if not 0 <= position < len(listed):
                raise at("E-INDEX", token)
            return listed[position]
    raise AssertionError(node)


def binary(token: Token, left_node: Expr, right_node: Expr, scopes: list[dict[str, Value]]) -> Value:
    op = token.text
    left = expr(left_node, scopes)
    if op in ("&&", "||"):
        if not isinstance(left, bool):
            raise at("E-TYPE", token)
        if left == (op == "||"):
            return left
        right = expr(right_node, scopes)
        if not isinstance(right, bool):
            raise at("E-TYPE", token)
        return right
    right = expr(right_node, scopes)
    pair = (kind(left), kind(right))
    if op in ("==", "!="):
        if pair[0] != pair[1]:
            raise at("E-TYPE", token)
        return equal(left, right) == (op == "==")
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        return left + right
    if op == "+" and isinstance(left, list) and isinstance(right, list):
        return left + right
    if op in ("<", "<=", ">", ">=") and pair == ("string", "string"):
        a, b = str(left).encode(), str(right).encode()
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if pair != ("int", "int"):
        raise at("E-TYPE", token)
    assert isinstance(left, int) and isinstance(right, int)
    if op == "/":
        if right == 0:
            raise at("E-ZERO", token)
        quotient = abs(left) // abs(right)
        return checked(quotient if (left < 0) == (right < 0) else -quotient, token)
    if op in ("<", "<=", ">", ">="):
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]
    return checked(left + right if op == "+" else left - right if op == "-" else left * right, token)
