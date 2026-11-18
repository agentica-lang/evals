package conf

import (
	"math"
	"strconv"
)

// Value is an int64, a string, a bool, a []Value or a *Rec.
type Value any

// Rec is a record: its keys in the order written, and its entries.
type Rec struct {
	Keys    []string
	Entries map[string]Value
}

func at(code string, t Token) { fail(code, t.Line, t.Col) }

func kind(v Value) string {
	switch v.(type) {
	case int64:
		return "int"
	case string:
		return "string"
	case bool:
		return "bool"
	case []Value:
		return "list"
	}
	return "record"
}

type scopes []map[string]Value

func (s scopes) lookup(name string) Value {
	for i := len(s) - 1; i >= 0; i-- {
		if v, ok := s[i][name]; ok {
			return v
		}
	}
	panic("unchecked name " + name)
}

func Evaluate(file File, imported map[string]Value) *Rec {
	top := map[string]Value{}
	for k, v := range imported {
		top[k] = v
	}
	return evalStatements(file.Statements, scopes{top})
}

func evalStatements(statements []Statement, s scopes) *Rec {
	rec := &Rec{Entries: map[string]Value{}}
	for _, st := range statements {
		v := eval(st.Value, s)
		if st.IsLet {
			s[len(s)-1][st.Name.Text] = v
		} else {
			rec.Keys = append(rec.Keys, st.Name.Text)
			rec.Entries[st.Name.Text] = v
		}
	}
	return rec
}

func equal(a, b Value) bool {
	if kind(a) != kind(b) {
		return false
	}
	switch a := a.(type) {
	case []Value:
		b := b.([]Value)
		if len(a) != len(b) {
			return false
		}
		for i := range a {
			if !equal(a[i], b[i]) {
				return false
			}
		}
		return true
	case *Rec:
		b := b.(*Rec)
		if len(a.Keys) != len(b.Keys) {
			return false
		}
		for _, k := range a.Keys {
			other, ok := b.Entries[k]
			if !ok || !equal(a.Entries[k], other) {
				return false
			}
		}
		return true
	}
	return a == b
}

func eval(e Expr, s scopes) Value {
	switch e := e.(type) {
	case Literal:
		switch e.Tok.Kind {
		case "int":
			return e.Tok.Number
		case "str":
			text := ""
			for _, part := range e.Tok.Parts {
				if part.Ref == nil {
					text += part.Text
					continue
				}
				switch v := s.lookup(part.Ref.Name).(type) {
				case int64:
					text += strconv.FormatInt(v, 10)
				case string:
					text += v
				case bool:
					text += strconv.FormatBool(v)
				default:
					fail("E-TYPE", part.Ref.Line, part.Ref.DollarCol)
				}
			}
			return text
		}
		return e.Tok.Text == "true"
	case Name:
		return s.lookup(e.Tok.Text)
	case List:
		items := []Value{}
		for _, item := range e.Items {
			items = append(items, eval(item, s))
		}
		return items
	case Record:
		return evalStatements(e.Statements, append(append(scopes{}, s...), map[string]Value{}))
	case Unary:
		v := eval(e.Operand, s)
		if n, ok := v.(int64); ok && e.Tok.Text == "-" {
			if n == math.MinInt64 {
				at("E-OVERFLOW", e.Tok)
			}
			return -n
		}
		if b, ok := v.(bool); ok && e.Tok.Text == "!" {
			return !b
		}
		at("E-TYPE", e.Tok)
	case Binary:
		return binary(e, s)
	case If:
		test, ok := eval(e.Condition, s).(bool)
		if !ok {
			at("E-TYPE", e.Tok)
		}
		if test {
			return eval(e.Then, s)
		}
		return eval(e.Otherwise, s)
	case Field:
		rec, ok := eval(e.Target, s).(*Rec)
		if !ok {
			at("E-TYPE", e.Tok)
		}
		v, ok := rec.Entries[e.Name.Text]
		if !ok {
			at("E-FIELD", e.Name)
		}
		return v
	case Item:
		target, index := eval(e.Target, s), eval(e.Index, s)
		items, ok := target.([]Value)
		position, isInt := index.(int64)
		if !ok || !isInt {
			at("E-TYPE", e.Tok)
		}
		if position < 0 || position >= int64(len(items)) {
			at("E-INDEX", e.Tok)
		}
		return items[position]
	}
	return nil
}

func binary(e Binary, s scopes) Value {
	op := e.Tok.Text
	left := eval(e.Left, s)
	if op == "&&" || op == "||" {
		l, ok := left.(bool)
		if !ok {
			at("E-TYPE", e.Tok)
		}
		if l == (op == "||") {
			return l
		}
		r, ok := eval(e.Right, s).(bool)
		if !ok {
			at("E-TYPE", e.Tok)
		}
		return r
	}
	right := eval(e.Right, s)
	lk, rk := kind(left), kind(right)
	switch {
	case op == "==" || op == "!=":
		if lk != rk {
			at("E-TYPE", e.Tok)
		}
		return equal(left, right) == (op == "==")
	case op == "+" && lk == "string" && rk == "string":
		return left.(string) + right.(string)
	case op == "+" && lk == "list" && rk == "list":
		return append(append([]Value{}, left.([]Value)...), right.([]Value)...)
	case lk == "string" && rk == "string" && (op == "<" || op == "<=" || op == ">" || op == ">="):
		return compare(op, left.(string) < right.(string), left == right)
	}
	if lk != "int" || rk != "int" {
		at("E-TYPE", e.Tok)
	}
	a, b := left.(int64), right.(int64)
	switch op {
	case "<", "<=", ">", ">=":
		return compare(op, a < b, a == b)
	case "+":
		if b > 0 && a > math.MaxInt64-b || b < 0 && a < math.MinInt64-b {
			at("E-OVERFLOW", e.Tok)
		}
		return a + b
	case "-":
		if b < 0 && a > math.MaxInt64+b || b > 0 && a < math.MinInt64+b {
			at("E-OVERFLOW", e.Tok)
		}
		return a - b
	case "*":
		if a != 0 && b != 0 && ((a*b)/b != a || a == -1 && b == math.MinInt64 || b == -1 && a == math.MinInt64) {
			at("E-OVERFLOW", e.Tok)
		}
		return a * b
	}
	if b == 0 {
		at("E-ZERO", e.Tok)
	}
	if a == math.MinInt64 && b == -1 {
		at("E-OVERFLOW", e.Tok)
	}
	return a / b
}

func compare(op string, less, same bool) bool {
	switch op {
	case "<":
		return less
	case "<=":
		return less || same
	case ">":
		return !less && !same
	}
	return !less
}
