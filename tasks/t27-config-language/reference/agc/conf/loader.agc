## Loads a main file and its imports. A file's name is its path relative to the main file's folder, with `/`. A
## failure is an error whose message is `FILE CODE LINE COL`.

import Checker from "checker"
import Eval from "eval"
import {Value} from "eval"
import Lexer from "lexer"
import {Part} from "lexer"
import Parser from "parser"
import Syntax from "syntax"

PATH_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"

struct Loader
  folder: String
  values: Map[String, Value]
end

struct Loaded
  loader: Loader
  value: Value
end

def read(loader: Loader, name: String) -> Result[String]
  path = try Path.join([loader.folder] + name.split("/"))
  File.read_text(path)
end

def run(folder: String, name: String) -> Result[Value]
  loader = Loader(folder: folder, values: {})
  text = read(loader, name)
  if !text.ok?
    return error("#{name} E-IMPORT-READ 1 1")
  end
  loaded = try load(loader, name, text.unwrap!, [name])
  ok(loaded.value)
end

## A stage's failure gets the file's name; a failure of an import already has its own.
def in_file[T](name: String, result: Result[T]) -> Result[T]
  case result
    ok(value) -> ok(value)
    error(e) if e.message.split(" ").size == 3 -> error("#{name} #{e.message}")
    error(e) -> error(e)
  end
end

def load(loader: Loader, name: String, text: String, stack: List[String]) -> Result[Loaded]
  tokens = try in_file(name, Lexer.tokenize(text))
  program = try in_file(name, Parser.parse(tokens))
  current = loader
  imported: Map[String, Value] = {}
  for item in program.imports
    loaded = try in_file(name, load_import(current, name, item, stack))
    current = loaded.loader
    imported = imported.put(item.name.text, loaded.value)
  end
  try in_file(name, Checker.check(program))
  value = try in_file(name, Eval.evaluate(program, imported))
  ok(Loaded(loader: current.with(values: current.values.put(name, value)), value: value))
end

def valid_path?(path: String) -> Bool
  parts = path.split("/")
  path.end_with?(".conf") and parts.all? do |part|
    part != "" and part != "." and part != ".." and part.split("").all? { |c| PATH_CHARS.include?(c) }
  end
end

def load_import(loader: Loader, importer: String, item: Syntax.Import, stack: List[String]) -> Result[Loaded]
  token = item.path
  path = ""
  plain = true
  for part in token.parts
    case part
      Part.Text(text) -> path += text
      Part.Name(_) -> plain = false
    end
  end
  if !plain or !valid_path?(path)
    return Checker.at("E-IMPORT-PATH", token)
  end
  folder = importer.split("/")
  name = (folder.take(folder.size - 1) + path.split("/")).join("/")
  if stack.include?(name)
    return Checker.at("E-IMPORT-CYCLE", token)
  end
  if loader.values.key?(name)
    return ok(Loaded(loader: loader, value: loader.values[name]))
  end
  text = read(loader, name)
  if !text.ok?
    return Checker.at("E-IMPORT-READ", token)
  end
  load(loader, name, text.unwrap!, stack.push(name))
end
