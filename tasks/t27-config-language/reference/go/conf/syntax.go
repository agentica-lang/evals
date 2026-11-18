package conf

// Expr is a node of the syntax tree; Token is the token that errors about it point at.
type Expr interface{ token() Token }

type (
	Literal struct{ Tok Token }
	Name    struct{ Tok Token }
	List    struct {
		Tok   Token
		Items []Expr
	}
	Record struct {
		Tok        Token
		Statements []Statement
	}
	Unary struct {
		Tok     Token
		Operand Expr
	}
	Binary struct {
		Tok         Token
		Left, Right Expr
	}
	If struct {
		Tok                        Token
		Condition, Then, Otherwise Expr
	}
	Field struct {
		Tok    Token
		Target Expr
		Name   Token
	}
	Item struct {
		Tok           Token
		Target, Index Expr
	}
)

func (e Literal) token() Token { return e.Tok }
func (e Name) token() Token    { return e.Tok }
func (e List) token() Token    { return e.Tok }
func (e Record) token() Token  { return e.Tok }
func (e Unary) token() Token   { return e.Tok }
func (e Binary) token() Token  { return e.Tok }
func (e If) token() Token      { return e.Tok }
func (e Field) token() Token   { return e.Tok }
func (e Item) token() Token    { return e.Tok }

type Statement struct {
	IsLet bool
	Name  Token
	Value Expr
}

type Import struct{ Path, Name Token }

type File struct {
	Imports    []Import
	Statements []Statement
}
