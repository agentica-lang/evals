import Bond from "pkg/bond/bond"
import Db from "pkg/db/db"
import Sqlite from "pkg/db/sqlite"

SCHEMA = "create table if not exists todos (id integer primary key, title text not null)"

struct Todo
  id: Int
  title: String
end

struct Todos
  todos: List[Todo]
end

def main() -> Void
  args = System.args()
  conn = Db.open("sqlite:#{args[0]}", [Sqlite.driver()]).unwrap!
  Db.execute(conn, SCHEMA, []).unwrap!
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

def list_todos(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  rows = try Db.query(db, "select id, title from todos order by id", [])
  todos = rows.map do |row| Todo(id: column_int(row, "id").unwrap!, title: column_text(row, "title").unwrap!) end
  ok(Bond.json_as(conn, 200, Todos.codec, Todos(todos: todos)))
end

def parse_title(conn: Bond.Conn) -> Result[String]
  json = try JSON.parse(try String.from_bytes(conn.body))
  return error("not an object") if JSON.kind(json) != "object"

  title = try JSON.string(try JSON.get(json, "title"))
  return error("empty title") if title.empty?

  ok(title)
end

def create_todo(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  case parse_title(conn)
    error(_) -> ok(error_json(conn, 400, "invalid todo"))
    ok(title) ->
      rows = try Db.query(db, "insert into todos (title) values (?) returning id", [Db.Value.Text(title)])
      ok(Bond.json_as(conn, 201, Todo.codec, Todo(id: try column_int(rows[0], "id"), title: title)))
  end
end
