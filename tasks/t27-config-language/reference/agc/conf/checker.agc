## Checks that every name has a binding before it, and that no scope binds a name, or a record a key, twice.

import Lexer from "lexer"
import {Part, Token} from "lexer"
import Syntax from "syntax"
import {Expr, Statement} from "syntax"

def at[T](code: String, token: Token) -> Result[T] = Lexer.fail(code, token.line, token.col)

def check(program: Syntax.Program) -> Result[Void]
  top: Set[String] = Set.new([])
  for item in program.imports
    if top.include?(item.name.text)
      return at("E-DUPLICATE", item.name)
    end
    top = top.add(item.name.text)
  end
  statements(program.statements, [], top)
end

def statements(items: List[Statement], outer: List[Set[String]], start: Set[String]) -> Result[Void]
  scope = start
  keys: Set[String] = Set.new([])
  for item in items
    name = item.name.text
    if (item.is_let and scope.include?(name)) or (!item.is_let and keys.include?(name))
      return at("E-DUPLICATE", item.name)
    end
    if !item.is_let
      keys = keys.add(name)
    end
    try expr(item.value, outer.push(scope))
    if item.is_let
      scope = scope.add(name)
    end
  end
  ok()
end

def bound(name: String, line: Int, col: Int, scopes: List[Set[String]]) -> Result[Void]
  if !(scopes.any? { |scope| scope.include?(name) })
    return Lexer.fail("E-NAME", line, col)
  end
  ok()
end

def all(nodes: List[Expr], scopes: List[Set[String]]) -> Result[Void]
  for node in nodes
    try expr(node, scopes)
  end
  ok()
end

def expr(node: Expr, scopes: List[Set[String]]) -> Result[Void]
  case node
    Expr.Literal(token) ->
      for part in token.parts
        case part
          Part.Name(ref) -> try bound(ref.name, ref.line, ref.col, scopes)
          Part.Text(_) -> nil
        end
      end
      ok()
    Expr.Name(token) -> bound(token.text, token.line, token.col, scopes)
    Expr.ListOf(_, items) -> all(items, scopes)
    Expr.Record(_, inner) -> statements(inner, scopes, Set.new([]))
    Expr.Unary(_, operand) -> expr(operand, scopes)
    Expr.Binary(_, left, right) -> all([left, right], scopes)
    Expr.If(_, condition, then, otherwise) -> all([condition, then, otherwise], scopes)
    Expr.Field(_, target, _) -> expr(target, scopes)
    Expr.Item(_, target, index) -> all([target, index], scopes)
  end
end
