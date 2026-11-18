package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"regexp"

	_ "modernc.org/sqlite"
)

var schema = []string{
	"create table if not exists customers (id integer primary key, name text not null unique)",
	"create table if not exists orders (id integer primary key, customer_id integer not null references customers (id), " +
		"item text not null, quantity integer not null, cents integer not null)",
}

var customerOrders = regexp.MustCompile(`^/customers/([^/]+)/orders$`)

type Order struct {
	ID       int64  `json:"id"`
	Customer string `json:"customer"`
	Item     string `json:"item"`
	Quantity int64  `json:"quantity"`
	Cents    int64  `json:"cents"`
}

type CustomerOrders struct {
	Customer   string  `json:"customer"`
	Orders     []Order `json:"orders"`
	TotalCents int64   `json:"total_cents"`
}

type Entry struct {
	Customer   string `json:"customer"`
	Orders     int64  `json:"orders"`
	TotalCents int64  `json:"total_cents"`
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
	path := r.URL.Path
	found := customerOrders.FindStringSubmatch(path)
	wanted := ""
	switch {
	case path == "/orders":
		wanted = "POST"
	case found != nil || path == "/report":
		wanted = "GET"
	default:
		sendJSON(w, 404, map[string]string{"error": "not found"})
		return
	}
	if r.Method != wanted {
		sendJSON(w, 405, map[string]string{"error": "method not allowed"})
		return
	}
	switch {
	case path == "/orders":
		s.create(w, r)
	case found != nil:
		s.customer(w, found[1])
	default:
		s.report(w)
	}
}

// whole reads a JSON integer of at least least: not a boolean, not a decimal.
func whole(raw json.RawMessage, least int64) (int64, bool) {
	var number json.Number
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&number) != nil {
		return 0, false
	}
	value, err := number.Int64()
	return value, err == nil && value >= least
}

func text(raw json.RawMessage) (string, bool) {
	var value string
	if raw == nil || string(raw) == "null" || json.Unmarshal(raw, &value) != nil {
		return "", false
	}
	return value, value != ""
}

func (s service) create(w http.ResponseWriter, r *http.Request) {
	raw, err := io.ReadAll(r.Body)
	var body map[string]json.RawMessage
	if err != nil || json.Unmarshal(raw, &body) != nil {
		sendJSON(w, 400, map[string]string{"error": "invalid order"})
		return
	}
	customer, okCustomer := text(body["customer"])
	item, okItem := text(body["item"])
	quantity, okQuantity := whole(body["quantity"], 1)
	cents, okCents := whole(body["cents"], 0)
	if !okCustomer || !okItem || !okQuantity || !okCents {
		sendJSON(w, 400, map[string]string{"error": "invalid order"})
		return
	}
	if _, err := s.db.Exec("insert or ignore into customers (name) values (?)", customer); err != nil {
		failed(w, err)
		return
	}
	var customerID int64
	if err := s.db.QueryRow("select id from customers where name = ?", customer).Scan(&customerID); err != nil {
		failed(w, err)
		return
	}
	result, err := s.db.Exec("insert into orders (customer_id, item, quantity, cents) values (?, ?, ?, ?)",
		customerID, item, quantity, cents)
	if err != nil {
		failed(w, err)
		return
	}
	id, _ := result.LastInsertId()
	sendJSON(w, 201, Order{id, customer, item, quantity, cents})
}

func (s service) customer(w http.ResponseWriter, name string) {
	var customerID int64
	err := s.db.QueryRow("select id from customers where name = ?", name).Scan(&customerID)
	if err == sql.ErrNoRows {
		sendJSON(w, 404, map[string]string{"error": "not found"})
		return
	}
	if err != nil {
		failed(w, err)
		return
	}
	rows, err := s.db.Query("select id, item, quantity, cents from orders where customer_id = ? order by id", customerID)
	if err != nil {
		failed(w, err)
		return
	}
	defer rows.Close()
	answer := CustomerOrders{Customer: name, Orders: []Order{}}
	for rows.Next() {
		order := Order{Customer: name}
		if err := rows.Scan(&order.ID, &order.Item, &order.Quantity, &order.Cents); err != nil {
			failed(w, err)
			return
		}
		answer.Orders = append(answer.Orders, order)
		answer.TotalCents += order.Quantity * order.Cents
	}
	sendJSON(w, 200, answer)
}

func (s service) report(w http.ResponseWriter) {
	rows, err := s.db.Query("select c.name, count(*), sum(o.quantity * o.cents) as total from orders o " +
		"join customers c on c.id = o.customer_id group by c.id order by total desc, c.name")
	if err != nil {
		failed(w, err)
		return
	}
	defer rows.Close()
	entries := []Entry{}
	for rows.Next() {
		var entry Entry
		if err := rows.Scan(&entry.Customer, &entry.Orders, &entry.TotalCents); err != nil {
			failed(w, err)
			return
		}
		entries = append(entries, entry)
	}
	sendJSON(w, 200, map[string][]Entry{"customers": entries})
}

func main() {
	db, err := sql.Open("sqlite", os.Args[1])
	for _, statement := range schema {
		if err == nil {
			_, err = db.Exec(statement)
		}
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
