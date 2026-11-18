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
const addPriority = "alter table todos add column priority integer not null default 2"

type Todo struct {
	ID       int64  `json:"id"`
	Title    string `json:"title"`
	Priority int64  `json:"priority"`
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
		s.list(w, r)
	case "POST":
		s.create(w, r)
	default:
		sendJSON(w, 405, map[string]string{"error": "method not allowed"})
	}
}

func (s service) list(w http.ResponseWriter, r *http.Request) {
	query := "select id, title, priority from todos order by id"
	args := []any{}
	if values, ok := r.URL.Query()["priority"]; ok {
		priority, valid := map[string]int64{"1": 1, "2": 2, "3": 3}[values[0]]
		if !valid {
			sendJSON(w, 400, map[string]string{"error": "invalid priority"})
			return
		}
		query = "select id, title, priority from todos where priority = ? order by id"
		args = append(args, priority)
	}
	rows, err := s.db.Query(query, args...)
	if err != nil {
		failed(w, err)
		return
	}
	defer rows.Close()
	todos := []Todo{}
	for rows.Next() {
		var todo Todo
		if err := rows.Scan(&todo.ID, &todo.Title, &todo.Priority); err != nil {
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
	priority, valid := int64(2), true
	if text, given := body["priority"]; given {
		priority, valid = map[string]int64{"1": 1, "2": 2, "3": 3}[string(text)]
	}
	if !valid {
		sendJSON(w, 400, map[string]string{"error": "invalid todo"})
		return
	}
	result, err := s.db.Exec("insert into todos (title, priority) values (?, ?)", title, priority)
	if err != nil {
		failed(w, err)
		return
	}
	id, _ := result.LastInsertId()
	sendJSON(w, 201, Todo{id, title, priority})
}

// migrate creates the table, and adds the priority column to a table of the old version.
func migrate(db *sql.DB) error {
	if _, err := db.Exec(schema); err != nil {
		return err
	}
	var count int
	err := db.QueryRow("select count(*) from pragma_table_info('todos') where name = 'priority'").Scan(&count)
	if err == nil && count == 0 {
		_, err = db.Exec(addPriority)
	}
	return err
}

func main() {
	db, err := sql.Open("sqlite", os.Args[1])
	if err == nil {
		err = migrate(db)
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
