## Writes a value as compact JSON, the keys of a record sorted by their bytes.

import {Value} from "eval"

ESCAPED = {"\"": "\\\"", "\\": "\\\\", "\n": "\\n", "\t": "\\t"}

def escape(c: String) -> String
  if ESCAPED.key?(c)
    return ESCAPED[c]
  end
  if c.code < 32
    return format("\\u%04x", c.code)
  end
  c
end

def quote(text: String) -> String = "\"" + text.split("").map(&escape).join("") + "\""

def to_json(value: Value) -> String
  case value
    Value.Whole(n) -> "#{n}"
    Value.Text(text) -> quote(text)
    Value.Truth(flag) -> "#{flag}"
    Value.Items(items) -> "[" + items.map { |item| to_json(item) }.join(",") + "]"
    Value.Entries(entries) ->
      pairs = entries.keys.sort.map { |key| quote(key) + ":" + to_json(entries[key]) }
      "{" + pairs.join(",") + "}"
  end
end
