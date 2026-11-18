from conf.errors import ConfError
from conf.lexer import Ref, Token
from conf.syntax import Binary, Expr, Field, File, If, Item, ListOf, Literal, Name, Record, Statement, Unary


def duplicate(token: Token) -> ConfError:
    return ConfError("E-DUPLICATE", token.line, token.col)


def check(file: File) -> None:
    """Every name has a binding before it, and no scope binds a name or a record a key twice."""
    top: set[str] = set()
    for item in file.imports:
        if item.name.text in top:
            raise duplicate(item.name)
        top.add(item.name.text)
    statements(file.statements, [top])


def statements(items: list[Statement], scopes: list[set[str]]) -> None:
    keys: set[str] = set()
    for statement in items:
        seen = scopes[-1] if statement.is_let else keys
        if statement.name.text in seen:
            raise duplicate(statement.name)
        if not statement.is_let:
            keys.add(statement.name.text)
        expr(statement.value, scopes)
        if statement.is_let:
            scopes[-1].add(statement.name.text)


def bound(name: str, line: int, col: int, scopes: list[set[str]]) -> None:
    if not any(name in scope for scope in scopes):
        raise ConfError("E-NAME", line, col)


def expr(node: Expr, scopes: list[set[str]]) -> None:
    match node:
        case Literal(token):
            for part in token.parts:
                if isinstance(part, Ref):
                    bound(part.name, part.line, part.col, scopes)
        case Name(token):
            bound(token.text, token.line, token.col, scopes)
        case ListOf(_, items):
            for item in items:
                expr(item, scopes)
        case Record(_, inner):
            statements(inner, [*scopes, set()])
        case Unary(_, operand):
            expr(operand, scopes)
        case Binary(_, left, right) | Item(_, left, right):
            expr(left, scopes)
            expr(right, scopes)
        case If(_, condition, then, otherwise):
            for child in (condition, then, otherwise):
                expr(child, scopes)
        case Field(_, target, _):
            expr(target, scopes)
