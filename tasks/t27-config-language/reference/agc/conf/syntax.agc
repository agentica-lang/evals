## The syntax tree. Each node keeps the token that errors about it point at.

import {Token} from "lexer"

struct Statement
  is_let: Bool
  name: Token
  value: Expr
end

struct Import
  path: Token
  name: Token
end

struct Program
  imports: List[Import]
  statements: List[Statement]
end

enum Expr
  Literal(Token)
  Name(Token)
  ListOf(Token, List[Expr])
  Record(Token, List[Statement])
  Unary(Token, Expr)
  Binary(Token, Expr, Expr)
  If(Token, Expr, Expr, Expr)
  Field(Token, Expr, Token)
  Item(Token, Expr, Expr)
end
