//go:build ignore

package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"

	_ "modernc.org/sqlite"
)

const schema = "create table if not exists todos (id integer primary key, title text not null)"

type Todo struct {
	ID    int64  `json:"id"`
	Title string `json:"title"`
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

func failed(w http.ResponseWriter, err error) {
	sendJSON(w, 500, map[string]string{"error": err.Error()})
}

func (s service) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/todos" {
		sendJSON(w, 404, map[string]string{"error": "not found"})
		return
	}
	switch r.Method {
	case "GET":
		s.list(w)
	case "POST":
		s.create(w, r)
	default:
		sendJSON(w, 405, map[string]string{"error": "method not allowed"})
	}
}

func (s service) list(w http.ResponseWriter) {
	rows, err := s.db.Query("select id, title from todos order by id")
	if err != nil {
		failed(w, err)
		return
	}
	defer rows.Close()
	todos := []Todo{}
	for rows.Next() {
		var todo Todo
		if err := rows.Scan(&todo.ID, &todo.Title); err != nil {
			failed(w, err)
			return
		}
		todos = append(todos, todo)
	}
	sendJSON(w, 200, map[string][]Todo{"todos": todos})
}

func (s service) create(w http.ResponseWriter, r *http.Request) {
	raw, err := io.ReadAll(r.Body)
	var body map[string]json.RawMessage
	var title string
	if err != nil || json.Unmarshal(raw, &body) != nil || string(body["title"]) == "null" ||
		json.Unmarshal(body["title"], &title) != nil || title == "" {
		sendJSON(w, 400, map[string]string{"error": "invalid todo"})
		return
	}
	result, err := s.db.Exec("insert into todos (title) values (?)", title)
	if err != nil {
		failed(w, err)
		return
	}
	id, _ := result.LastInsertId()
	sendJSON(w, 201, Todo{id, title})
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
