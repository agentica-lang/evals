"""The syntax tree. Every node keeps the token that errors about it point at."""
from dataclasses import dataclass

from conf.lexer import Token


@dataclass
class Literal:
    token: Token  # int, str, true or false


@dataclass
class Name:
    token: Token


@dataclass
class ListOf:
    token: Token
    items: list["Expr"]


@dataclass
class Record:
    token: Token
    statements: list["Statement"]


@dataclass
class Unary:
    token: Token
    operand: "Expr"


@dataclass
class Binary:
    token: Token
    left: "Expr"
    right: "Expr"


@dataclass
class If:
    token: Token
    condition: "Expr"
    then: "Expr"
    otherwise: "Expr"


@dataclass
class Field:
    token: Token  # the dot
    target: "Expr"
    name: Token


@dataclass
class Item:
    token: Token  # the [
    target: "Expr"
    index: "Expr"


type Expr = Literal | Name | ListOf | Record | Unary | Binary | If | Field | Item


@dataclass
class Statement:
    is_let: bool
    name: Token
    value: Expr


@dataclass
class Import:
    path: Token
    name: Token


@dataclass
class File:
    imports: list[Import]
    statements: list[Statement]
