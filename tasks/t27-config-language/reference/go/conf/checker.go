package conf

func duplicate(t Token) { fail("E-DUPLICATE", t.Line, t.Col) }

// Check fails unless every name has a binding before it and no scope binds a name, or a record a key, twice.
func Check(file File) {
	top := map[string]bool{}
	for _, item := range file.Imports {
		if top[item.Name.Text] {
			duplicate(item.Name)
		}
		top[item.Name.Text] = true
	}
	checkStatements(file.Statements, []map[string]bool{top})
}

func checkStatements(statements []Statement, scopes []map[string]bool) {
	keys := map[string]bool{}
	scope := scopes[len(scopes)-1]
	for _, s := range statements {
		seen := keys
		if s.IsLet {
			seen = scope
		}
		if seen[s.Name.Text] {
			duplicate(s.Name)
		}
		if !s.IsLet {
			keys[s.Name.Text] = true
		}
		checkExpr(s.Value, scopes)
		if s.IsLet {
			scope[s.Name.Text] = true
		}
	}
}

func bound(name string, line, col int, scopes []map[string]bool) {
	for _, scope := range scopes {
		if scope[name] {
			return
		}
	}
	fail("E-NAME", line, col)
}

func checkExpr(e Expr, scopes []map[string]bool) {
	switch e := e.(type) {
	case Literal:
		for _, part := range e.Tok.Parts {
			if part.Ref != nil {
				bound(part.Ref.Name, part.Ref.Line, part.Ref.Col, scopes)
			}
		}
	case Name:
		bound(e.Tok.Text, e.Tok.Line, e.Tok.Col, scopes)
	case List:
		for _, item := range e.Items {
			checkExpr(item, scopes)
		}
	case Record:
		inner := append(append([]map[string]bool{}, scopes...), map[string]bool{})
		checkStatements(e.Statements, inner)
	case Unary:
		checkExpr(e.Operand, scopes)
	case Binary:
		checkExpr(e.Left, scopes)
		checkExpr(e.Right, scopes)
	case If:
		checkExpr(e.Condition, scopes)
		checkExpr(e.Then, scopes)
		checkExpr(e.Otherwise, scopes)
	case Field:
		checkExpr(e.Target, scopes)
	case Item:
		checkExpr(e.Target, scopes)
		checkExpr(e.Index, scopes)
	}
}
