## Evaluates a checked Program to the record of its entries.

import Lexer from "lexer"
import {Part, Token} from "lexer"
import Syntax from "syntax"
import {Expr, Statement} from "syntax"

MAX_INT = 9223372036854775807
MIN_INT = -9223372036854775807 - 1

enum Value
  Whole(Int)
  Text(String)
  Truth(Bool)
  Items(List[Value])
  Entries(Map[String, Value])
end

def at[T](code: String, token: Token) -> Result[T] = Lexer.fail(code, token.line, token.col)

def kind(value: Value) -> String
  case value
    Value.Whole(_) -> "int"
    Value.Text(_) -> "string"
    Value.Truth(_) -> "bool"
    Value.Items(_) -> "list"
    Value.Entries(_) -> "record"
  end
end

def evaluate(program: Syntax.Program, imported: Map[String, Value]) -> Result[Value]
  statements(program.statements, [], imported)
end

def statements(items: List[Statement], outer: List[Map[String, Value]], start: Map[String, Value]) -> Result[Value]
  scope = start
  entries: Map[String, Value] = {}
  for item in items
    value = try expr(item.value, outer.push(scope))
    if item.is_let
      scope = scope.put(item.name.text, value)
    else
      entries = entries.put(item.name.text, value)
    end
  end
  ok(Value.Entries(entries))
end

def lookup(name: String, scopes: List[Map[String, Value]]) -> Value
  scope = scopes.reverse.find { |each| each.key?(name) }.unwrap!
  scope[name]
end

def text_of(token: Token, scopes: List[Map[String, Value]]) -> Result[Value]
  out = ""
  for part in token.parts
    piece = case part
      Part.Text(text) -> ok(text)
      Part.Name(ref) -> interpolated(ref, lookup(ref.name, scopes))
    end
    out += try piece
  end
  ok(Value.Text(out))
end

def interpolated(ref: Lexer.Ref, value: Value) -> Result[String]
  case value
    Value.Whole(n) -> ok("#{n}")
    Value.Text(text) -> ok(text)
    Value.Truth(flag) -> ok("#{flag}")
    _ -> Lexer.fail("E-TYPE", ref.line, ref.dollar_col)
  end
end

def expr(node: Expr, scopes: List[Map[String, Value]]) -> Result[Value]
  case node
    Expr.Literal(token) -> literal(token, scopes)
    Expr.Name(token) -> ok(lookup(token.text, scopes))
    Expr.ListOf(_, items) -> list_of(items, scopes)
    Expr.Record(_, inner) -> statements(inner, scopes, {})
    Expr.Unary(token, operand) -> unary(token, try expr(operand, scopes))
    Expr.Binary(token, left, right) -> binary(token, left, right, scopes)
    Expr.If(token, condition, then, otherwise) -> choose(token, try expr(condition, scopes), then, otherwise, scopes)
    Expr.Field(token, target, name) -> field(token, try expr(target, scopes), name)
    Expr.Item(token, target, index) -> item(token, try expr(target, scopes), try expr(index, scopes))
  end
end

def literal(token: Token, scopes: List[Map[String, Value]]) -> Result[Value]
  if token.kind == "int"
    return ok(Value.Whole(token.number))
  end
  if token.kind == "str"
    return text_of(token, scopes)
  end
  ok(Value.Truth(token.text == "true"))
end

def list_of(items: List[Expr], scopes: List[Map[String, Value]]) -> Result[Value]
  values: List[Value] = []
  for each in items
    values = values.push(try expr(each, scopes))
  end
  ok(Value.Items(values))
end

def unary(token: Token, value: Value) -> Result[Value]
  case value
    Value.Whole(n) if token.text == "-" and n == MIN_INT -> at("E-OVERFLOW", token)
    Value.Whole(n) if token.text == "-" -> ok(Value.Whole(-n))
    Value.Truth(flag) if token.text == "!" -> ok(Value.Truth(!flag))
    _ -> at("E-TYPE", token)
  end
end

def choose(token: Token, test: Value, then: Expr, otherwise: Expr, scopes: List[Map[String, Value]]) -> Result[Value]
  case test
    Value.Truth(true) -> expr(then, scopes)
    Value.Truth(false) -> expr(otherwise, scopes)
    _ -> at("E-TYPE", token)
  end
end

def field(token: Token, target: Value, name: Token) -> Result[Value]
  case target
    Value.Entries(entries) if entries.key?(name.text) -> ok(entries[name.text])
    Value.Entries(_) -> at("E-FIELD", name)
    _ -> at("E-TYPE", token)
  end
end

def item(token: Token, target: Value, index: Value) -> Result[Value]
  items = items_of(target)
  n = whole(index)
  if kind(target) != "list" or kind(index) != "int"
    return at("E-TYPE", token)
  end
  if n < 0 or n >= items.size
    return at("E-INDEX", token)
  end
  ok(items[n])
end

def binary(token: Token, left_node: Expr, right_node: Expr, scopes: List[Map[String, Value]]) -> Result[Value]
  op = token.text
  left = try expr(left_node, scopes)
  if op == "&&" or op == "||"
    decided = case left
      Value.Truth(flag) -> ok(flag == (op == "||"))
      _ -> at("E-TYPE", token)
    end
    if try decided
      return ok(left)
    end
    right_value = try expr(right_node, scopes)
    return case right_value
      Value.Truth(_) -> ok(right_value)
      _ -> at("E-TYPE", token)
    end
  end
  right = try expr(right_node, scopes)
  if op == "==" or op == "!="
    if kind(left) != kind(right)
      return at("E-TYPE", token)
    end
    return ok(Value.Truth((left == right) == (op == "==")))
  end
  if kind(left) != kind(right)
    return at("E-TYPE", token)
  end
  case left
    Value.Whole(a) -> arithmetic(token, a, whole(right))
    Value.Text(a) -> texts(token, a, text(right))
    Value.Items(a) if op == "+" -> ok(Value.Items(a + items_of(right)))
    _ -> at("E-TYPE", token)
  end
end

def whole(value: Value) -> Int
  case value
    Value.Whole(n) -> n
    _ -> 0
  end
end

def text(value: Value) -> String
  case value
    Value.Text(t) -> t
    _ -> ""
  end
end

def items_of(value: Value) -> List[Value]
  case value
    Value.Items(values) -> values
    _ -> []
  end
end

def texts(token: Token, a: String, b: String) -> Result[Value]
  if token.text == "+"
    return ok(Value.Text(a + b))
  end
  order = a.compare(b)
  case token.text
    "<" -> ok(Value.Truth(order < 0))
    "<=" -> ok(Value.Truth(order <= 0))
    ">" -> ok(Value.Truth(order > 0))
    ">=" -> ok(Value.Truth(order >= 0))
    _ -> at("E-TYPE", token)
  end
end

def arithmetic(token: Token, a: Int, b: Int) -> Result[Value]
  case token.text
    "<" -> ok(Value.Truth(a < b))
    "<=" -> ok(Value.Truth(a <= b))
    ">" -> ok(Value.Truth(a > b))
    ">=" -> ok(Value.Truth(a >= b))
    "+" -> checked(token, (b > 0 and a > MAX_INT - b) or (b < 0 and a < MIN_INT - b), a, b)
    "-" -> checked(token, (b < 0 and a > MAX_INT + b) or (b > 0 and a < MIN_INT + b), a, b)
    "*" -> checked(token, multiply_overflows?(a, b), a, b)
    _ -> divide(token, a, b)
  end
end

def magnitude(n: Int) -> Int
  if n < 0
    return -n
  end
  n
end

## Whether a * b leaves the 64-bit range, worked out without overflowing.
def multiply_overflows?(a: Int, b: Int) -> Bool
  if a == 0 or b == 0 or a == 1 or b == 1
    return false
  end
  if a == MIN_INT or b == MIN_INT
    return true
  end
  x = magnitude(a)
  y = magnitude(b)
  if (a > 0) == (b > 0)
    return x > MAX_INT / y
  end
  # A negative product may reach 2^63, one past MAX_INT.
  limit = MAX_INT / y
  if MAX_INT % y == y - 1
    limit += 1
  end
  x > limit
end

def checked(token: Token, overflows: Bool, a: Int, b: Int) -> Result[Value]
  if overflows
    return at("E-OVERFLOW", token)
  end
  case token.text
    "+" -> ok(Value.Whole(a + b))
    "-" -> ok(Value.Whole(a - b))
    _ -> ok(Value.Whole(a * b))
  end
end

def divide(token: Token, a: Int, b: Int) -> Result[Value]
  if b == 0
    return at("E-ZERO", token)
  end
  if a == MIN_INT and b == -1
    return at("E-OVERFLOW", token)
  end
  ok(Value.Whole(a / b))
end
