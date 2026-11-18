import Bond from "pkg/bond/bond"
import Db from "pkg/db/db"
import Sqlite from "pkg/db/sqlite"

SCHEMA = [
  "create table if not exists customers (id integer primary key, name text not null unique)",
  "create table if not exists orders (id integer primary key, customer_id integer not null references customers (id), item text not null, quantity integer not null, cents integer not null)",
]

struct Order
  id: Int
  customer: String
  item: String
  quantity: Int
  cents: Int
end

struct CustomerOrders
  customer: String
  orders: List[Order]
  total_cents: Int
end

struct Entry
  customer: String
  orders: Int
  total_cents: Int
end

struct Report
  customers: List[Entry]
end

def main() -> Void
  args = System.args()
  conn = Db.open("sqlite:#{args[0]}", [Sqlite.driver()]).unwrap!
  SCHEMA.each do |statement| Db.execute(conn, statement, []).unwrap! end
  on_create = handler do |c| create_order(conn, c) end
  on_customer = handler do |c| customer_orders(conn, c) end
  on_report = handler do |c| report(conn, c) end
  on_missing = handler do |c| ok(error_json(c, 404, "not found")) end
  app = (
    Bond.app()
    |> Bond.post("/orders", on_create)
    |> Bond.get("/customers/:name/orders", on_customer)
    |> Bond.get("/report", on_report)
    |> Bond.not_found(on_missing)
  )

  server = Bond.start(app, "127.0.0.1", 0).unwrap!
  puts("listening #{Bond.local_port(server)}")
  IO.flush()
  Bond.wait(server).unwrap!
end

def handler(f: Bond.Handler) -> Bond.Handler = f

def error_json(conn: Bond.Conn, status: Int, message: String) -> Bond.Conn
  Bond.json(conn, status, JSON.object({"error": JSON.from(message)}))
end

def column_int(row: Db.Row, column: String) -> Result[Int]
  case try row.get(column).to_result("no #{column}")
    Db.Value.Int(number) -> ok(number)
    _ -> error("#{column} is not an integer")
  end
end

def column_text(row: Db.Row, column: String) -> Result[String]
  case try row.get(column).to_result("no #{column}")
    Db.Value.Text(text) -> ok(text)
    _ -> error("#{column} is not text")
  end
end

def text_field(json: JSON.Value, key: String) -> Result[String]
  text = try JSON.string(try JSON.get(json, key))
  return error("#{key} is empty") if text.empty?

  ok(text)
end

# An integer of at least `least`: not a boolean, not a decimal.
def int_field(json: JSON.Value, key: String, least: Int) -> Result[Int]
  number = try JSON.int(try JSON.get(json, key))
  return error("#{key} is below #{least}") if number < least

  ok(number)
end

def parse_order(conn: Bond.Conn) -> Result[Order]
  json = try JSON.parse(try String.from_bytes(conn.body))
  return error("not an object") if JSON.kind(json) != "object"

  ok(
    Order(
      id: 0,
      customer: try text_field(json, "customer"),
      item: try text_field(json, "item"),
      quantity: try int_field(json, "quantity", 1),
      cents: try int_field(json, "cents", 0),
    ),
  )
end

def create_order(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  case parse_order(conn)
    error(_) -> ok(error_json(conn, 400, "invalid order"))
    ok(input) ->
      name = Db.Value.Text(input.customer)
      try Db.execute(db, "insert or ignore into customers (name) values (?)", [name])
      found = try Db.query(db, "select id from customers where name = ?", [name])
      customer_id = try column_int(found[0], "id")
      rows = try Db.query(
        db,
        "insert into orders (customer_id, item, quantity, cents) values (?, ?, ?, ?) returning id",
        [
          Db.Value.Int(customer_id),
          Db.Value.Text(input.item),
          Db.Value.Int(input.quantity),
          Db.Value.Int(input.cents),
        ],
      )

      ok(Bond.json_as(conn, 201, Order.codec, input.with(id: try column_int(rows[0], "id"))))
  end
end

def customer_orders(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  name = try Bond.param(conn, "name")
  found = try Db.query(db, "select id from customers where name = ?", [Db.Value.Text(name)])
  return ok(error_json(conn, 404, "not found")) if found.empty?

  rows = try Db.query(
    db,
    "select id, item, quantity, cents from orders where customer_id = ? order by id",
    [Db.Value.Int(try column_int(found[0], "id"))],
  )

  orders = rows.map do |row|
    Order(
      id: column_int(row, "id").unwrap!,
      customer: name,
      item: column_text(row, "item").unwrap!,
      quantity: column_int(row, "quantity").unwrap!,
      cents: column_int(row, "cents").unwrap!,
    )
  end

  total = orders.reduce(0) do |sum, order| sum + order.quantity * order.cents end
  ok(Bond.json_as(conn, 200, CustomerOrders.codec, CustomerOrders(customer: name, orders: orders, total_cents: total)))
end

def report(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  rows = try Db.query(
    db,
    "select c.name as name, count(*) as orders, sum(o.quantity * o.cents) as total from orders o join customers c on c.id = o.customer_id group by c.id order by total desc, c.name",
    [],
  )

  entries = rows.map do |row|
    Entry(
      customer: column_text(row, "name").unwrap!,
      orders: column_int(row, "orders").unwrap!,
      total_cents: column_int(row, "total").unwrap!,
    )
  end

  ok(Bond.json_as(conn, 200, Report.codec, Report(customers: entries)))
end
