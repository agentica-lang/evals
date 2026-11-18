package conf

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode/utf8"
)

var part = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)

type loader struct {
	folder string
	values map[string]*Rec
}

func (l *loader) read(name string) (string, bool) {
	data, err := os.ReadFile(filepath.Join(l.folder, filepath.FromSlash(name)))
	if err != nil || !utf8.Valid(data) {
		return "", false
	}
	return string(data), true
}

// Run loads the main file `name` of `folder`; a file's name is its path relative to that folder, with `/`.
func Run(folder, name string) (value *Rec, err *Error) {
	l := &loader{folder: folder, values: map[string]*Rec{}}
	text, ok := l.read(name)
	if !ok {
		return nil, &Error{Code: "E-IMPORT-READ", File: name, Line: 1, Col: 1}
	}
	defer func() {
		if r := recover(); r != nil {
			e, ok := r.(*Error)
			if !ok {
				panic(r)
			}
			value, err = nil, e
		}
	}()
	return l.load(name, text, []string{name}), nil
}

func (l *loader) load(name, text string, stack []string) *Rec {
	defer func() {
		if r := recover(); r != nil {
			if e, ok := r.(*Error); ok && e.File == "" {
				e.File = name
			}
			panic(r)
		}
	}()
	file := Parse(Tokenize(text))
	imported := map[string]Value{}
	for _, item := range file.Imports {
		imported[item.Name.Text] = l.loadImport(name, item, stack)
	}
	Check(file)
	value := Evaluate(file, imported)
	l.values[name] = value
	return value
}

func (l *loader) loadImport(importer string, item Import, stack []string) *Rec {
	t := item.Path
	path, valid := "", true
	for _, p := range t.Parts {
		if p.Ref != nil {
			valid = false
		}
		path += p.Text
	}
	parts := strings.Split(path, "/")
	for _, p := range parts {
		valid = valid && part.MatchString(p) && p != "." && p != ".."
	}
	if !valid || !strings.HasSuffix(path, ".conf") {
		at("E-IMPORT-PATH", t)
	}
	name := path
	if i := strings.LastIndex(importer, "/"); i >= 0 {
		name = importer[:i+1] + path
	}
	for _, open := range stack {
		if open == name {
			at("E-IMPORT-CYCLE", t)
		}
	}
	if v, ok := l.values[name]; ok {
		return v
	}
	text, ok := l.read(name)
	if !ok {
		at("E-IMPORT-READ", t)
	}
	return l.load(name, text, append(append([]string{}, stack...), name))
}
