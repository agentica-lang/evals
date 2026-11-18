from conf.errors import ConfError
from conf.lexer import Token
from conf.syntax import Binary, Expr, Field, File, If, Import, Item, ListOf, Literal, Name, Record, Statement, Unary

LEVELS = [{"||"}, {"&&"}, {"==", "!="}, {"<", "<=", ">", ">="}, {"+", "-"}, {"*", "/"}]
SINGLE = {2, 3}  # the levels where an operator may appear once without parentheses


def fail(token: Token) -> ConfError:
    return ConfError("E-SYNTAX", token.line, token.col)


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.at = 0
        # Whether newlines are only space here: true inside ( and [, false at the top and inside {.
        self.spaces = [False]

    def peek(self) -> Token:
        if self.spaces[-1]:
            while self.tokens[self.at].kind == "nl":
                self.at += 1
        return self.tokens[self.at]

    def take(self) -> Token:
        token = self.peek()
        if token.kind != "eof":
            self.at += 1
        return token

    def expect(self, text: str) -> Token:
        token = self.take()
        if not token.is_(text):
            raise fail(token)
        return token

    def expect_name(self) -> Token:
        token = self.take()
        if token.kind != "name":
            raise fail(token)
        return token

    def blank_lines(self) -> None:
        while self.peek().kind == "nl":
            self.take()

    def end_of_line(self) -> None:
        token = self.peek()
        if token.kind == "nl":
            self.take()
        elif token.kind != "eof":
            raise fail(token)

    def file(self) -> File:
        imports = []
        self.blank_lines()
        while self.peek().is_("import"):
            self.take()
            path = self.take()
            if path.kind != "str":
                raise fail(path)
            self.expect("as")
            imports.append(Import(path, self.expect_name()))
            self.end_of_line()
            self.blank_lines()
        statements = []
        while self.peek().kind != "eof":
            statements.append(self.statement())
            self.end_of_line()
            self.blank_lines()
        return File(imports, statements)

    def statement(self) -> Statement:
        token = self.take()
        is_let = token.is_("let")
        name = self.expect_name() if is_let else token
        if name.kind != "name":
            raise fail(name)
        self.expect("=")
        return Statement(is_let, name, self.expr())

    def expr(self) -> Expr:
        if self.peek().is_("if"):
            token = self.take()
            condition = self.expr()
            self.expect("then")
            then = self.expr()
            self.expect("else")
            return If(token, condition, then, self.expr())
        return self.binary(0)

    def binary(self, level: int) -> Expr:
        if level == len(LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek().kind == "sym" and self.peek().text in LEVELS[level]:
            token = self.take()
            left = Binary(token, left, self.binary(level + 1))
            if level in SINGLE and self.peek().kind == "sym" and self.peek().text in LEVELS[level]:
                raise fail(self.peek())
        return left

    def unary(self) -> Expr:
        if self.peek().is_("-") or self.peek().is_("!"):
            token = self.take()
            return Unary(token, self.unary())
        return self.postfix()

    def postfix(self) -> Expr:
        expr = self.primary()
        while True:
            if self.peek().is_("."):
                token = self.take()
                expr = Field(token, expr, self.expect_name())
            elif self.peek().is_("["):
                token = self.take()
                self.spaces.append(True)
                index = self.expr()
                self.expect("]")
                self.spaces.pop()
                expr = Item(token, expr, index)
            else:
                return expr

    def primary(self) -> Expr:
        token = self.take()
        if token.kind in ("int", "str") or token.is_("true") or token.is_("false"):
            return Literal(token)
        if token.kind == "name":
            return Name(token)
        if token.is_("("):
            self.spaces.append(True)
            inner = self.expr()
            self.expect(")")
            self.spaces.pop()
            return inner
        if token.is_("["):
            return self.list_of(token)
        if token.is_("{"):
            return self.record(token)
        raise fail(token)

    def list_of(self, token: Token) -> Expr:
        self.spaces.append(True)
        items = []
        while not self.peek().is_("]"):
            items.append(self.expr())
            if self.peek().is_(","):
                self.take()
            elif not self.peek().is_("]"):
                raise fail(self.peek())
        self.take()
        self.spaces.pop()
        return ListOf(token, items)

    def record(self, token: Token) -> Expr:
        self.spaces.append(False)
        statements = []
        while True:
            while self.peek().kind == "nl" or self.peek().is_(","):
                self.take()
            if self.peek().is_("}"):
                break
            statements.append(self.statement())
            if not (self.peek().kind == "nl" or self.peek().is_(",") or self.peek().is_("}")):
                raise fail(self.peek())
        self.take()
        self.spaces.pop()
        return Record(token, statements)


def parse(tokens: list[Token]) -> File:
    return Parser(tokens).file()
