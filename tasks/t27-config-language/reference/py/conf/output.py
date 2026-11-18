from conf.evaluator import Value

ESCAPED = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\t": "\\t"}


def quote(text: str) -> str:
    return '"' + "".join(ESCAPED.get(c, f"\\u{ord(c):04x}" if c < " " else c) for c in text) + '"'


def to_json(value: Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return quote(value)
    if isinstance(value, list):
        return "[" + ",".join(to_json(item) for item in value) + "]"
    keys = sorted(value, key=lambda key: key.encode())
    return "{" + ",".join(f"{quote(key)}:{to_json(value[key])}" for key in keys) + "}"
