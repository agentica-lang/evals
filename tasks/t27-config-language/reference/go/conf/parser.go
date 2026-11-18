package conf

var levels = [][]string{{"||"}, {"&&"}, {"==", "!="}, {"<", "<=", ">", ">="}, {"+", "-"}, {"*", "/"}}

// single holds the levels where an operator may appear once without parentheses.
var single = map[int]bool{2: true, 3: true}

type parser struct {
	tokens []Token
	at     int
	spaces []bool // whether newlines are only space: inside ( and [, not at the top or inside {
}

func syntax(t Token) { fail("E-SYNTAX", t.Line, t.Col) }

func (p *parser) peek() Token {
	if p.spaces[len(p.spaces)-1] {
		for p.tokens[p.at].Kind == "nl" {
			p.at++
		}
	}
	return p.tokens[p.at]
}

func (p *parser) take() Token {
	t := p.peek()
	if t.Kind != "eof" {
		p.at++
	}
	return t
}

func (p *parser) expect(text string) Token {
	t := p.take()
	if !t.Is(text) {
		syntax(t)
	}
	return t
}

func (p *parser) expectName() Token {
	t := p.take()
	if t.Kind != "name" {
		syntax(t)
	}
	return t
}

func (p *parser) push(spaces bool) { p.spaces = append(p.spaces, spaces) }
func (p *parser) pop()             { p.spaces = p.spaces[:len(p.spaces)-1] }

func (p *parser) blankLines() {
	for p.peek().Kind == "nl" {
		p.take()
	}
}

func (p *parser) endOfLine() {
	switch t := p.peek(); t.Kind {
	case "nl":
		p.take()
	case "eof":
	default:
		syntax(t)
	}
}

func Parse(tokens []Token) File {
	p := &parser{tokens: tokens, spaces: []bool{false}}
	var file File
	p.blankLines()
	for p.peek().Is("import") {
		p.take()
		path := p.take()
		if path.Kind != "str" {
			syntax(path)
		}
		p.expect("as")
		file.Imports = append(file.Imports, Import{Path: path, Name: p.expectName()})
		p.endOfLine()
		p.blankLines()
	}
	for p.peek().Kind != "eof" {
		file.Statements = append(file.Statements, p.statement())
		p.endOfLine()
		p.blankLines()
	}
	return file
}

func (p *parser) statement() Statement {
	t := p.take()
	isLet := t.Is("let")
	name := t
	if isLet {
		name = p.expectName()
	} else if name.Kind != "name" {
		syntax(name)
	}
	p.expect("=")
	return Statement{IsLet: isLet, Name: name, Value: p.expr()}
}

func (p *parser) expr() Expr {
	if p.peek().Is("if") {
		t := p.take()
		condition := p.expr()
		p.expect("then")
		then := p.expr()
		p.expect("else")
		return If{t, condition, then, p.expr()}
	}
	return p.binary(0)
}

func (p *parser) atLevel(level int) bool {
	t := p.peek()
	for _, op := range levels[level] {
		if t.Kind == "sym" && t.Text == op {
			return true
		}
	}
	return false
}

func (p *parser) binary(level int) Expr {
	if level == len(levels) {
		return p.unary()
	}
	left := p.binary(level + 1)
	for p.atLevel(level) {
		t := p.take()
		left = Binary{t, left, p.binary(level + 1)}
		if single[level] && p.atLevel(level) {
			syntax(p.peek())
		}
	}
	return left
}

func (p *parser) unary() Expr {
	if p.peek().Is("-") || p.peek().Is("!") {
		t := p.take()
		return Unary{t, p.unary()}
	}
	return p.postfix()
}

func (p *parser) postfix() Expr {
	e := p.primary()
	for {
		switch {
		case p.peek().Is("."):
			t := p.take()
			e = Field{t, e, p.expectName()}
		case p.peek().Is("["):
			t := p.take()
			p.push(true)
			index := p.expr()
			p.expect("]")
			p.pop()
			e = Item{t, e, index}
		default:
			return e
		}
	}
}

func (p *parser) primary() Expr {
	t := p.take()
	switch {
	case t.Kind == "int" || t.Kind == "str" || t.Is("true") || t.Is("false"):
		return Literal{t}
	case t.Kind == "name":
		return Name{t}
	case t.Is("("):
		p.push(true)
		inner := p.expr()
		p.expect(")")
		p.pop()
		return inner
	case t.Is("["):
		p.push(true)
		var items []Expr
		for !p.peek().Is("]") {
			items = append(items, p.expr())
			if p.peek().Is(",") {
				p.take()
			} else if !p.peek().Is("]") {
				syntax(p.peek())
			}
		}
		p.take()
		p.pop()
		return List{t, items}
	case t.Is("{"):
		p.push(false)
		var statements []Statement
		for {
			for p.peek().Kind == "nl" || p.peek().Is(",") {
				p.take()
			}
			if p.peek().Is("}") {
				break
			}
			statements = append(statements, p.statement())
			if next := p.peek(); next.Kind != "nl" && !next.Is(",") && !next.Is("}") {
				syntax(next)
			}
		}
		p.take()
		p.pop()
		return Record{t, statements}
	}
	syntax(t)
	return nil
}
