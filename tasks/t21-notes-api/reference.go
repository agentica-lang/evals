package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"strings"

	_ "modernc.org/sqlite"
)

const schema = "create table if not exists notes (id integer primary key, title text not null, body text not null)"

var digits = regexp.MustCompile(`^[0-9]+$`)

type Note struct {
	ID    int64  `json:"id"`
	Title string `json:"title"`
	Body  string `json:"body"`
}

type service struct {
	db *sql.DB
}

func sendJSON(w http.ResponseWriter, status int, value any) {
	data, _ := json.Marshal(value)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	w.Write(data)
}

func notFound(w http.ResponseWriter) {
	sendJSON(w, 404, map[string]string{"error": "not found"})
}

func notAllowed(w http.ResponseWriter) {
	sendJSON(w, 405, map[string]string{"error": "method not allowed"})
}

func (s service) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	path := r.URL.Path
	switch {
	case path == "/health":
		if r.Method != "GET" {
			notAllowed(w)
			return
		}
		sendJSON(w, 200, map[string]string{"status": "ok"})
	case path == "/notes":
		switch r.Method {
		case "GET":
			s.list(w)
		case "POST":
			s.create(w, r)
		default:
			notAllowed(w)
		}
	case strings.HasPrefix(path, "/notes/") && !strings.Contains(path[len("/notes/"):], "/"):
		if r.Method != "GET" && r.Method != "DELETE" {
			notAllowed(w)
			return
		}
		s.one(w, r.Method, path[len("/notes/"):])
	default:
		notFound(w)
	}
}

func (s service) list(w http.ResponseWriter) {
	rows, err := s.db.Query("select id, title, body from notes order by id")
	if err != nil {
		sendJSON(w, 500, map[string]string{"error": err.Error()})
		return
	}
	defer rows.Close()
	notes := []Note{}
	for rows.Next() {
		var note Note
		if err := rows.Scan(&note.ID, &note.Title, &note.Body); err != nil {
			sendJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}
		notes = append(notes, note)
	}
	sendJSON(w, 200, map[string][]Note{"notes": notes})
}

func (s service) create(w http.ResponseWriter, r *http.Request) {
	var body map[string]json.RawMessage
	var title, text string
	raw, err := io.ReadAll(r.Body)
	if err != nil || json.Unmarshal(raw, &body) != nil || json.Unmarshal(body["title"], &title) != nil ||
		json.Unmarshal(body["body"], &text) != nil || title == "" ||
		string(body["title"]) == "null" || string(body["body"]) == "null" {
		sendJSON(w, 400, map[string]string{"error": "invalid note"})
		return
	}
	result, err := s.db.Exec("insert into notes (title, body) values (?, ?)", title, text)
	if err != nil {
		sendJSON(w, 500, map[string]string{"error": err.Error()})
		return
	}
	id, _ := result.LastInsertId()
	sendJSON(w, 201, Note{id, title, text})
}

func (s service) one(w http.ResponseWriter, method, text string) {
	if !digits.MatchString(text) {
		notFound(w)
		return
	}
	id, err := strconv.ParseInt(text, 10, 64)
	if err != nil {
		notFound(w)
		return
	}
	var note Note
	err = s.db.QueryRow("select id, title, body from notes where id = ?", id).Scan(&note.ID, &note.Title, &note.Body)
	if err == sql.ErrNoRows {
		notFound(w)
		return
	}
	if err != nil {
		sendJSON(w, 500, map[string]string{"error": err.Error()})
		return
	}
	if method == "DELETE" {
		if _, err := s.db.Exec("delete from notes where id = ?", id); err != nil {
			sendJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}
		sendJSON(w, 200, map[string]int64{"deleted": id})
		return
	}
	sendJSON(w, 200, note)
}

func main() {
	db, err := sql.Open("sqlite", os.Args[1])
	if err == nil {
		_, err = db.Exec(schema)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Printf("listening %d\n", listener.Addr().(*net.TCPAddr).Port)
	http.Serve(listener, service{db})
}
