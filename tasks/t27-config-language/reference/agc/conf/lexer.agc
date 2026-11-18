## Splits a Conf file into tokens. A failure is an error whose message is `CODE LINE COL`.

KEYWORDS = Set.new(["import", "as", "let", "if", "then", "else", "true", "false"])
PAIRS = Set.new(["==", "!=", "<=", ">=", "&&", "||"])
SINGLES = Set.new(["=", "+", "-", "*", "/", "(", ")", "[", "]", "{", "}", ",", ".", "<", ">", "!"])
ESCAPES = {"\"": "\"", "\\": "\\", "n": "\n", "t": "\t", "$": "$"}

struct Ref
  name: String
  line: Int
  col: Int
  dollar_col: Int
end

## A token: kind is name, kw, int, str, sym, nl or eof. An int keeps its value in number, a str its parts.
struct Token
  kind: String
  text: String
  line: Int
  col: Int
  number: Int = 0
  parts: List[Part] = []
end

struct StringAt
  token: Token
  next: Int
end

enum Part
  Text(String)
  Name(Ref)
end

def fail[T](code: String, line: Int, col: Int) -> Result[T] = error("#{code} #{line} #{col}")

def is?(token: Token, text: String) -> Bool
  (token.kind == "sym" or token.kind == "kw") and token.text == text
end

def name_start?(c: String) -> Bool
  code = c.code
  c == "_" or (code >= 65 and code <= 90) or (code >= 97 and code <= 122)
end

def digit?(c: String) -> Bool
  code = c.code
  code >= 48 and code <= 57
end

def name_char?(c: String) -> Bool = name_start?(c) or digit?(c)

def tokenize(source: String) -> Result[List[Token]]
  chars = source.split("")
  size = chars.size
  tokens: List[Token] = []
  i = 0
  line = 1
  col = 1
  while i < size
    c = chars[i]
    if c == "\n"
      tokens = tokens.push(Token(kind: "nl", text: c, line: line, col: col))
      i += 1
      line += 1
      col = 1
    elsif c == " " or c == "\t"
      i += 1
      col += 1
    elsif c == "#"
      while i < size and chars[i] != "\n"
        i += 1
      end
    elsif name_start?(c)
      j = i
      while j < size and name_char?(chars[j])
        j += 1
      end
      word = source.slice(i, j - i)
      kind = "name"
      if KEYWORDS.include?(word)
        kind = "kw"
      end
      tokens = tokens.push(Token(kind: kind, text: word, line: line, col: col))
      col += j - i
      i = j
    elsif digit?(c)
      j = i
      while j < size and digit?(chars[j])
        j += 1
      end
      digits = source.slice(i, j - i)
      number = case digits.to_i
        ok(n) -> n
        error(_) -> -1
      end
      if number < 0
        return fail("E-NUMBER", line, col)
      end
      tokens = tokens.push(Token(kind: "int", text: digits, line: line, col: col, number: number))
      col += j - i
      i = j
    elsif c == "\""
      read = try read_string(chars, i, line, col)
      tokens = tokens.push(read.token)
      col += read.next - i
      i = read.next
    elsif i + 1 < size and PAIRS.include?(c + chars[i + 1])
      tokens = tokens.push(Token(kind: "sym", text: c + chars[i + 1], line: line, col: col))
      i += 2
      col += 2
    elsif SINGLES.include?(c)
      tokens = tokens.push(Token(kind: "sym", text: c, line: line, col: col))
      i += 1
      col += 1
    else
      return fail("E-CHAR", line, col)
    end
  end
  lines = chars.count { |ch| ch == "\n" }
  if size > 0 and chars[size - 1] != "\n"
    lines += 1
  end
  ok(tokens.push(Token(kind: "eof", text: "", line: lines + 1, col: 1)))
end

def read_string(chars: List[String], start: Int, line: Int, col: Int) -> Result[StringAt]
  size = chars.size
  parts: List[Part] = []
  chunk = ""
  i = start + 1
  while i >= size or chars[i] != "\""
    here = col + i - start
    if i >= size or chars[i] == "\n"
      return fail("E-STRING", line, col)
    end
    c = chars[i]
    following = ""
    if i + 1 < size
      following = chars[i + 1]
    end
    if c == "\\"
      if !ESCAPES.key?(following)
        return fail("E-ESCAPE", line, here)
      end
      chunk += ESCAPES[following]
      i += 2
    elsif c == "$" and following == "{"
      j = i + 2
      if j < size and name_start?(chars[j])
        while j < size and name_char?(chars[j])
          j += 1
        end
      end
      name = chars.drop(i + 2).take(j - i - 2).join("")
      if name == "" or KEYWORDS.include?(name) or j >= size or chars[j] != "}"
        return fail("E-ESCAPE", line, here)
      end
      parts = parts.push(Part.Text(chunk)).push(Part.Name(Ref(name: name, line: line, col: here + 2, dollar_col: here)))
      chunk = ""
      i = j + 1
    else
      chunk += c
      i += 1
    end
  end
  text = chars.drop(start).take(i + 1 - start).join("")
  token = Token(kind: "str", text: text, line: line, col: col, parts: parts.push(Part.Text(chunk)))
  ok(StringAt(token: token, next: i + 1))
end
