import Bond from "pkg/bond/bond"
import Db from "pkg/db/db"
import Sqlite from "pkg/db/sqlite"

SCHEMA = "create table if not exists todos (id integer primary key, title text not null)"
ADD_PRIORITY = "alter table todos add column priority integer not null default 2"
PRIORITIES = {"1": 1, "2": 2, "3": 3}

struct Todo
  id: Int
  title: String
  priority: Int
end

struct Todos
  todos: List[Todo]
end

def main() -> Void
  args = System.args()
  conn = Db.open("sqlite:#{args[0]}", [Sqlite.driver()]).unwrap!
  migrate(conn).unwrap!
  on_list = handler do |c| list_todos(conn, c) end
  on_create = handler do |c| create_todo(conn, c) end
  on_missing = handler do |c| ok(error_json(c, 404, "not found")) end
  app = (
    Bond.app()
    |> Bond.get("/todos", on_list)
    |> Bond.post("/todos", on_create)
    |> Bond.not_found(on_missing)
  )

  server = Bond.start(app, "127.0.0.1", 0).unwrap!
  puts("listening #{Bond.local_port(server)}")
  IO.flush()
  Bond.wait(server).unwrap!
end

# Creates the table, and adds the priority column to a table of the old version.
def migrate(db: Db.Connection) -> Result[Void]
  try Db.execute(db, SCHEMA, [])
  found = try Db.query(db, "select name from pragma_table_info('todos') where name = 'priority'", [])
  if found.empty?
    try Db.execute(db, ADD_PRIORITY, [])
  end

  ok()
end

# The `priority` of a query string, `none` when it has none.
def query_priority(query: String) -> Optional[String]
  found = query.split("&").find do |pair| pair == "priority" or pair.start_with?("priority=") end
  case found
    error(_) -> none
    ok(pair) ->
      parts = pair.split("=")
      return some("") if parts.size < 2

      some(parts[1])
  end
end

# Gives a `do` block the type of a handler, so that a name can hold it before the pipeline that uses it.
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

def todo_of(row: Db.Row) -> Todo
  Todo(
    id: column_int(row, "id").unwrap!,
    title: column_text(row, "title").unwrap!,
    priority: column_int(row, "priority").unwrap!,
  )
end

def list_todos(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  case query_priority(conn.query)
    none -> send_todos(conn, try Db.query(db, "select id, title, priority from todos order by id", []))
    some(text) ->
      case PRIORITIES.get(text)
        none -> ok(error_json(conn, 400, "invalid priority"))
        some(priority) ->
          send_todos(
            conn,
            try Db.query(
              db,
              "select id, title, priority from todos where priority = ? order by id",
              [Db.Value.Int(priority)],
            ),
          )
      end
  end
end

def send_todos(conn: Bond.Conn, rows: List[Db.Row]) -> Result[Bond.Conn]
  ok(Bond.json_as(conn, 200, Todos.codec, Todos(todos: rows.map do |row| todo_of(row) end)))
end

# A title that is a non-empty string, and a priority that is an integer from 1 to 3 (2 when it is missing).
def parse_todo(conn: Bond.Conn) -> Result[Todo]
  json = try JSON.parse(try String.from_bytes(conn.body))
  return error("not an object") if JSON.kind(json) != "object"

  title = try JSON.string(try JSON.get(json, "title"))
  return error("empty title") if title.empty?

  priority = 2
  case JSON.get(json, "priority")
    ok(value) -> priority = try JSON.int(value)
    error(_) -> priority = 2
  end
  return error("priority out of range") if priority < 1 or priority > 3

  ok(Todo(id: 0, title: title, priority: priority))
end

def create_todo(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  case parse_todo(conn)
    error(_) -> ok(error_json(conn, 400, "invalid todo"))
    ok(input) ->
      rows = try Db.query(
        db,
        "insert into todos (title, priority) values (?, ?) returning id",
        [Db.Value.Text(input.title), Db.Value.Int(input.priority)],
      )

      ok(Bond.json_as(conn, 201, Todo.codec, input.with(id: try column_int(rows[0], "id"))))
  end
end
