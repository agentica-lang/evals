// Package conf reads, checks and evaluates Conf files. Inside the package a failure panics with an *Error, which Run
// recovers, so each stage stops at the first error.
package conf

import (
	"math/big"
	"strings"
)

type Error struct {
	Code      string
	File      string
	Line, Col int
}

func fail(code string, line, col int) { panic(&Error{Code: code, Line: line, Col: col}) }

type Ref struct {
	Name                 string
	Line, Col, DollarCol int
}

// A Part of a string is its text or, when Ref is set, an interpolated name.
type Part struct {
	Text string
	Ref  *Ref
}

type Token struct {
	Kind      string // name, kw, int, str, sym, nl, eof
	Text      string
	Line, Col int
	Number    int64
	Parts     []Part
}

func (t Token) Is(text string) bool { return (t.Kind == "sym" || t.Kind == "kw") && t.Text == text }

var keywords = map[string]bool{"import": true, "as": true, "let": true, "if": true, "then": true, "else": true,
	"true": true, "false": true}
var escapes = map[rune]string{'"': `"`, '\\': `\`, 'n': "\n", 't': "\t", '$': "$"}
var maxInt = big.NewInt(1<<63 - 1)

func nameStart(c rune) bool { return c == '_' || c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' }
func digit(c rune) bool     { return c >= '0' && c <= '9' }
func nameChar(c rune) bool  { return nameStart(c) || digit(c) }

func Tokenize(source string) []Token {
	text := []rune(source)
	var tokens []Token
	at := func(i int) rune {
		if i < len(text) {
			return text[i]
		}
		return 0
	}
	i, line, col := 0, 1, 1
	for i < len(text) {
		c := text[i]
		switch {
		case c == '\n':
			tokens = append(tokens, Token{Kind: "nl", Text: "\n", Line: line, Col: col})
			i, line, col = i+1, line+1, 1
		case c == ' ' || c == '\t':
			i, col = i+1, col+1
		case c == '#':
			for i < len(text) && text[i] != '\n' {
				i, col = i+1, col+1
			}
		case nameStart(c):
			j := i
			for j < len(text) && nameChar(text[j]) {
				j++
			}
			word := string(text[i:j])
			kind := "name"
			if keywords[word] {
				kind = "kw"
			}
			tokens = append(tokens, Token{Kind: kind, Text: word, Line: line, Col: col})
			i, col = j, col+j-i
		case digit(c):
			j := i
			for j < len(text) && digit(text[j]) {
				j++
			}
			number, _ := new(big.Int).SetString(string(text[i:j]), 10)
			if number.Cmp(maxInt) > 0 {
				fail("E-NUMBER", line, col)
			}
			tokens = append(tokens, Token{Kind: "int", Text: string(text[i:j]), Line: line, Col: col, Number: number.Int64()})
			i, col = j, col+j-i
		case c == '"':
			token, end := readString(text, i, line, col)
			tokens = append(tokens, token)
			i, col = end, col+end-i
		case pair(c, at(i+1)):
			tokens = append(tokens, Token{Kind: "sym", Text: string(text[i : i+2]), Line: line, Col: col})
			i, col = i+2, col+2
		case strings.ContainsRune("=+-*/()[]{},.<>!", c):
			tokens = append(tokens, Token{Kind: "sym", Text: string(c), Line: line, Col: col})
			i, col = i+1, col+1
		default:
			fail("E-CHAR", line, col)
		}
	}
	lines := strings.Count(source, "\n")
	if source != "" && !strings.HasSuffix(source, "\n") {
		lines++
	}
	return append(tokens, Token{Kind: "eof", Line: lines + 1, Col: 1})
}

func pair(a, b rune) bool {
	switch string([]rune{a, b}) {
	case "==", "!=", "<=", ">=", "&&", "||":
		return true
	}
	return false
}

func readString(text []rune, start, line, col int) (Token, int) {
	var parts []Part
	var chunk strings.Builder
	i := start + 1
	for {
		here := col + i - start
		if i >= len(text) || text[i] == '\n' {
			fail("E-STRING", line, col)
		}
		c := text[i]
		if c == '"' {
			break
		}
		next := rune(0)
		if i+1 < len(text) {
			next = text[i+1]
		}
		switch {
		case c == '\\':
			escaped, ok := escapes[next]
			if !ok {
				fail("E-ESCAPE", line, here)
			}
			chunk.WriteString(escaped)
			i += 2
		case c == '$' && next == '{':
			j := i + 2
			if j < len(text) && nameStart(text[j]) {
				for j < len(text) && nameChar(text[j]) {
					j++
				}
			}
			name := string(text[i+2 : j])
			if name == "" || keywords[name] || j >= len(text) || text[j] != '}' {
				fail("E-ESCAPE", line, here)
			}
			parts = append(parts, Part{Text: chunk.String()}, Part{Ref: &Ref{Name: name, Line: line, Col: here + 2, DollarCol: here}})
			chunk.Reset()
			i = j + 1
		default:
			chunk.WriteRune(c)
			i++
		}
	}
	parts = append(parts, Part{Text: chunk.String()})
	return Token{Kind: "str", Text: string(text[start : i+1]), Line: line, Col: col, Parts: parts}, i + 1
}
