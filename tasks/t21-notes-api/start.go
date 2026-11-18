//go:build ignore

package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"

	_ "modernc.org/sqlite"
)

const schema = "create table if not exists notes (id integer primary key, title text not null, body text not null)"

type service struct {
	db *sql.DB
}

func sendJSON(w http.ResponseWriter, status int, value any) {
	data, _ := json.Marshal(value)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	w.Write(data)
}

func (s service) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/health" && r.Method == "GET" {
		sendJSON(w, 200, map[string]string{"status": "ok"})
		return
	}
	sendJSON(w, 404, map[string]string{"error": "not found"})
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
