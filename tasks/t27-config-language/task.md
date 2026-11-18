# Task: an interpreter for a small configuration language

Write an interpreter for Conf, a small configuration language. It is a whole
program; split it into stages and files the way you would in a real project
(the entry point is `solution.agc`, or `solution.py` in Python).

Examples are in `cases/`: each folder holds a `main.conf`, the files it
imports, and `expected`, the line the program prints. `agentica test
spec_test.agc` (in Python, `python3 -m unittest test_spec`) runs them all. The
hidden cases are many more, one or more for each error code.

The program takes one argument, the path of the main Conf file, and reads
nothing from standard input. It prints the value of the main file as JSON on
one line to standard output and exits with status 0, or prints one error line
to standard output and exits with status 1.

## Files and lines

A Conf file is UTF-8 text. A `#` outside a string starts a comment to the end
of the line. Spaces and tabs separate tokens; a carriage return is not
allowed. A file is a sequence of lines:

```text
import "lib/base.conf" as base
let port = 8000

name = "api"
server = {
  host = "localhost", port = port + 1
  tags = ["a", "b"] + base.tags
}
debug = if port > 1024 then false else true
```

- `import "PATH" as NAME` lines come first, before any other line.
- `let NAME = EXPR` binds a name. It is not part of the value.
- `KEY = EXPR` is an entry of the file's value.
- A newline ends a line, except where the innermost bracket open at that
  point is `(` or `[`: there a newline is only space. Inside `{...}` newlines
  separate statements, as at the top of a file.
- Empty lines and comment-only lines are allowed anywhere.

The value of a file is a record of its entries (`KEY = EXPR`), in the order
written.

## Tokens

- A name is a letter or `_`, then letters, digits or `_` (ASCII). `import`,
  `as`, `let`, `if`, `then`, `else`, `true` and `false` are keywords, not
  names.
- An integer is one or more digits. Its value must fit in a signed 64-bit
  integer (at most 9223372036854775807); negative numbers come from the
  minus operator.
- A string is between double quotes on one line. Escapes: `\"`, `\\`, `\n`,
  `\t` and `\$`. A `${NAME}` inside a string is replaced by the value of
  `NAME` (an integer is written in decimal, a string as it is, a boolean as
  `true` or `false`).
- Symbols: `= + - * / ( ) [ ] { } , . == != < <= > >= && || !`.

## Expressions

From the lowest precedence to the highest:

1. `if C then A else B` (it extends as far to the right as it can)
2. `||`, then `&&` (left to right, short-circuit: the right side is not
   evaluated when the left decides)
3. `==` and `!=` (at most one per level without parentheses)
4. `<`, `<=`, `>`, `>=` (at most one per level without parentheses)
5. `+` and `-`, left to right
6. `*` and `/`, left to right
7. unary `-` and `!`
8. `X.NAME` (a field) and `X[I]` (an item), left to right
9. integers, strings, `true`, `false`, names, `(EXPR)`, lists
   `[A, B, ...]` (a trailing comma is allowed), and records
   `{ STATEMENTS }`

Inside a record, statements are separated by newlines or commas, and extra
newlines and commas are allowed (`{,}` is an empty record). A record may have
`let` statements, which bind names inside it; imports are only at the top of a
file. Its entries make its value. At the top of a file, statements are
separated by newlines only.

The operators:

- `+`: two integers add; two strings join; two lists join.
- `-`, `*`: two integers.
- `/`: two integers, the quotient rounded toward zero (`-7 / 2` is `-3`).
- `==`, `!=`: two values of the same type (integers, strings, booleans,
  lists or records, compared in depth; records with the same entries in
  any order are equal; inside lists and records, values of different types
  are simply not equal).
- `<`, `<=`, `>`, `>=`: two integers, or two strings (compared by their
  UTF-8 bytes).
- `&&`, `||`, `!` and the condition of `if`: booleans.
- unary `-`: an integer.
- `X.NAME`: X a record that has the entry `NAME`.
- `X[I]`: X a list and I an integer from 0 to the length minus 1.

## Names

A name refers to the nearest `let` or import of that name that comes before
it: in the same record or an enclosing one, or at the top of the file. A
name is never an entry. Each file has its own names; an import gives the
imported file's value.

## Imports

An import path is relative to the importing file's folder. It is one or more
parts separated by `/`, each made of letters, digits, `_`, `-` and `.`, and
it is not `.` or `..`; it ends with `.conf`. A file imported twice is read
once and gives the same value.

## Output

The value is printed as compact JSON: no spaces, the entries of a record as an
object with its keys sorted by their bytes, lists as arrays, integers in
decimal, booleans as `true` and `false`. In a string, `"` is `\"`, `\` is
`\\`, a newline is `\n`, a tab is `\t`, other characters below U+0020 are
`\u00XX` (lowercase hexadecimal), and every other character is written as it
is.

## Errors

The program stops at the first error and prints `error CODE at FILE:LINE:COL`,
then exits with status 1. `FILE` is the path of the file relative to the main
file's folder (the main file is its own name), with `/`. `LINE` and `COL`
count from 1; `COL` counts characters (a tab is one).

The order: loading a file means reading it, splitting all of it into tokens,
parsing all of it, loading its imports in the order written (each import's
path is checked, then the file is loaded, unless it was loaded before), then
checking its names in the order they are written, then evaluating it. The main
file is loaded this way. Evaluation goes left to right: the operands of an
operator are evaluated before it is applied, a statement's value before the
next statement. The first error of that order is the one printed.

A newline token is at the position of its newline character. The end of the
file is at column 1 of the line after the last line (a final newline does not
start a new line).

| Code | When | Position |
|---|---|---|
| `E-IMPORT-READ` | an imported file is missing or cannot be read | the import's path string |
| `E-IMPORT-PATH` | an import path that breaks the rules above | the import's path string |
| `E-IMPORT-CYCLE` | a file imports itself, directly or through others | the import's path string |
| `E-CHAR` | a character that starts no token | that character |
| `E-STRING` | a string not closed on its line | its opening quote |
| `E-ESCAPE` | another character after `\`, or `${` not followed by a name and `}` | the `\` or the `$` |
| `E-NUMBER` | an integer literal too large | its first digit |
| `E-SYNTAX` | any other token where the grammar does not allow it, including the end of the file | that token (the end of the file: the line after the last, column 1) |
| `E-NAME` | a name with no binding before it | the name |
| `E-DUPLICATE` | a second entry with the same key in one record, or a second `let` or import of the same name in one record or file | the second key or name |
| `E-TYPE` | an operator, `if`, interpolation, field or item on values of the wrong type | the operator, `if`, `$`, `.` or `[` |
| `E-FIELD` | a field that the record does not have | the field's name |
| `E-INDEX` | an item outside the list | the `[` |
| `E-ZERO` | a division by zero | the `/` |
| `E-OVERFLOW` | an integer result outside the signed 64-bit range | the operator |

An error in an imported file is reported in that file. A main file that cannot
be read prints `error E-IMPORT-READ at FILE:1:1`.

Nesting of up to 300 levels (of parentheses, lists, records and operators
together) is valid and must work.
