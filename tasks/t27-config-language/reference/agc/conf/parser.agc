## Parses tokens into a File. Every function takes the position of its first token and whether newlines are only
## space there (inside `(` and `[`), and gives the node with the position after it.

import Lexer from "lexer"
import {Token} from "lexer"
import Syntax from "syntax"
import {Expr, Statement} from "syntax"

LEVELS = [["||"], ["&&"], ["==", "!="], ["<", "<=", ">", ">="], ["+", "-"], ["*", "/"]]
SINGLE = [2, 3]

struct ExprAt
  expr: Expr
  pos: Int
end

struct StatementAt
  statement: Statement
  pos: Int
end

def syntax[T](token: Token) -> Result[T] = Lexer.fail("E-SYNTAX", token.line, token.col)

## The position of the next token, past newlines where they are only space.
def skip(tokens: List[Token], pos: Int, spaces: Bool) -> Int
  at = pos
  while spaces and tokens[at].kind == "nl"
    at += 1
  end
  at
end

def peek(tokens: List[Token], pos: Int, spaces: Bool) -> Token = tokens[skip(tokens, pos, spaces)]

## The position after the token `text`, which must come next.
def expect(tokens: List[Token], pos: Int, spaces: Bool, text: String) -> Result[Int]
  at = skip(tokens, pos, spaces)
  if !Lexer.is?(tokens[at], text)
    return syntax(tokens[at])
  end
  ok(at + 1)
end

def blank_lines(tokens: List[Token], pos: Int) -> Int
  at = pos
  while tokens[at].kind == "nl"
    at += 1
  end
  at
end

def end_of_line(tokens: List[Token], pos: Int) -> Result[Int]
  token = tokens[pos]
  if token.kind == "nl"
    return ok(pos + 1)
  end
  if token.kind != "eof"
    return syntax(token)
  end
  ok(pos)
end

def parse(tokens: List[Token]) -> Result[Syntax.Program]
  imports: List[Syntax.Import] = []
  statements: List[Statement] = []
  pos = blank_lines(tokens, 0)
  while Lexer.is?(tokens[pos], "import")
    path = tokens[pos + 1]
    if path.kind != "str"
      return syntax(path)
    end
    at = try expect(tokens, pos + 2, false, "as")
    name = tokens[at]
    if name.kind != "name"
      return syntax(name)
    end
    imports = imports.push(Syntax.Import(path: path, name: name))
    pos = blank_lines(tokens, try end_of_line(tokens, at + 1))
  end
  while tokens[pos].kind != "eof"
    read = try statement(tokens, pos)
    statements = statements.push(read.statement)
    pos = blank_lines(tokens, try end_of_line(tokens, read.pos))
  end
  ok(Syntax.Program(imports: imports, statements: statements))
end

def statement(tokens: List[Token], pos: Int) -> Result[StatementAt]
  is_let = Lexer.is?(tokens[pos], "let")
  at = pos
  if is_let
    at += 1
  end
  name = tokens[at]
  if name.kind != "name"
    return syntax(name)
  end
  value_at = try expect(tokens, at + 1, false, "=")
  value = try expr(tokens, value_at, false)
  ok(StatementAt(statement: Statement(is_let: is_let, name: name, value: value.expr), pos: value.pos))
end

def expr(tokens: List[Token], pos: Int, spaces: Bool) -> Result[ExprAt]
  at = skip(tokens, pos, spaces)
  if !Lexer.is?(tokens[at], "if")
    return binary(tokens, at, spaces, 0)
  end
  condition = try expr(tokens, at + 1, spaces)
  then_at = try expect(tokens, condition.pos, spaces, "then")
  then = try expr(tokens, then_at, spaces)
  else_at = try expect(tokens, then.pos, spaces, "else")
  otherwise = try expr(tokens, else_at, spaces)
  ok(ExprAt(expr: Expr.If(tokens[at], condition.expr, then.expr, otherwise.expr), pos: otherwise.pos))
end

def at_level?(token: Token, level: Int) -> Bool = token.kind == "sym" and LEVELS[level].include?(token.text)

def binary(tokens: List[Token], pos: Int, spaces: Bool, level: Int) -> Result[ExprAt]
  if level == LEVELS.size
    return unary(tokens, pos, spaces)
  end
  first = try binary(tokens, pos, spaces, level + 1)
  left = first.expr
  at = first.pos
  while at_level?(peek(tokens, at, spaces), level)
    op = skip(tokens, at, spaces)
    right = try binary(tokens, op + 1, spaces, level + 1)
    left = Expr.Binary(tokens[op], left, right.expr)
    at = right.pos
    if SINGLE.include?(level) and at_level?(peek(tokens, at, spaces), level)
      return syntax(peek(tokens, at, spaces))
    end
  end
  ok(ExprAt(expr: left, pos: at))
end

def unary(tokens: List[Token], pos: Int, spaces: Bool) -> Result[ExprAt]
  at = skip(tokens, pos, spaces)
  token = tokens[at]
  if Lexer.is?(token, "-") or Lexer.is?(token, "!")
    operand = try unary(tokens, at + 1, spaces)
    return ok(ExprAt(expr: Expr.Unary(token, operand.expr), pos: operand.pos))
  end
  postfix(tokens, at, spaces)
end

def postfix(tokens: List[Token], pos: Int, spaces: Bool) -> Result[ExprAt]
  read = try primary(tokens, pos, spaces)
  node = read.expr
  at = read.pos
  next_token = peek(tokens, at, spaces)
  while Lexer.is?(next_token, ".") or Lexer.is?(next_token, "[")
    op = skip(tokens, at, spaces)
    if Lexer.is?(next_token, ".")
      name = peek(tokens, op + 1, spaces)
      if name.kind != "name"
        return syntax(name)
      end
      node = Expr.Field(next_token, node, name)
      at = skip(tokens, op + 1, spaces) + 1
    else
      index = try expr(tokens, op + 1, true)
      at = try expect(tokens, index.pos, true, "]")
      node = Expr.Item(next_token, node, index.expr)
    end
    next_token = peek(tokens, at, spaces)
  end
  ok(ExprAt(expr: node, pos: at))
end

def primary(tokens: List[Token], pos: Int, spaces: Bool) -> Result[ExprAt]
  at = skip(tokens, pos, spaces)
  token = tokens[at]
  if token.kind == "int" or token.kind == "str" or Lexer.is?(token, "true") or Lexer.is?(token, "false")
    return ok(ExprAt(expr: Expr.Literal(token), pos: at + 1))
  end
  if token.kind == "name"
    return ok(ExprAt(expr: Expr.Name(token), pos: at + 1))
  end
  if Lexer.is?(token, "(")
    inner = try expr(tokens, at + 1, true)
    close = try expect(tokens, inner.pos, true, ")")
    return ok(ExprAt(expr: inner.expr, pos: close))
  end
  if Lexer.is?(token, "[")
    return list_of(tokens, at)
  end
  if Lexer.is?(token, "{")
    return record(tokens, at)
  end
  syntax(token)
end

def list_of(tokens: List[Token], open: Int) -> Result[ExprAt]
  items: List[Expr] = []
  at = open + 1
  while !Lexer.is?(peek(tokens, at, true), "]")
    item = try expr(tokens, at, true)
    items = items.push(item.expr)
    at = skip(tokens, item.pos, true)
    if Lexer.is?(tokens[at], ",")
      at += 1
    elsif !Lexer.is?(tokens[at], "]")
      return syntax(tokens[at])
    end
  end
  ok(ExprAt(expr: Expr.ListOf(tokens[open], items), pos: skip(tokens, at, true) + 1))
end

def separator?(token: Token) -> Bool = token.kind == "nl" or Lexer.is?(token, ",")

def record(tokens: List[Token], open: Int) -> Result[ExprAt]
  statements: List[Statement] = []
  at = open + 1
  while separator?(tokens[at])
    at += 1
  end
  while !Lexer.is?(tokens[at], "}")
    read = try statement(tokens, at)
    statements = statements.push(read.statement)
    at = read.pos
    if !separator?(tokens[at]) and !Lexer.is?(tokens[at], "}")
      return syntax(tokens[at])
    end
    while separator?(tokens[at])
      at += 1
    end
  end
  ok(ExprAt(expr: Expr.Record(tokens[open], statements), pos: at + 1))
end
