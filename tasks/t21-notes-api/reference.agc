import Bond from "pkg/bond/bond"
import Db from "pkg/db/db"
import Sqlite from "pkg/db/sqlite"

SCHEMA = "create table if not exists notes (id integer primary key, title text not null, body text not null)"

struct Note
  id: Int
  title: String
  body: String
end

struct Notes
  notes: List[Note]
end

def main() -> Void
  args = System.args()
  conn = Db.open("sqlite:#{args[0]}", [Sqlite.driver()]).unwrap!
  Db.execute(conn, SCHEMA, []).unwrap!
  on_health = handler do |c| ok(Bond.json(c, 200, JSON.object({"status": JSON.from("ok")}))) end
  on_list = handler do |c| list_notes(conn, c) end
  on_create = handler do |c| create_note(conn, c) end
  on_show = handler do |c| show_note(conn, c) end
  on_delete = handler do |c| delete_note(conn, c) end
  on_missing = handler do |c| ok(not_found(c)) end
  app = (
    Bond.app()
    |> Bond.get("/health", on_health)
    |> Bond.get("/notes", on_list)
    |> Bond.post("/notes", on_create)
    |> Bond.get("/notes/:id", on_show)
    |> Bond.delete("/notes/:id", on_delete)
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

def not_found(conn: Bond.Conn) -> Bond.Conn = error_json(conn, 404, "not found")

def text_of(row: Db.Row, column: String) -> Result[String]
  case try row.get(column).to_result("no #{column}")
    Db.Value.Text(text) -> ok(text)
    _ -> error("#{column} is not text")
  end
end

def note_of(row: Db.Row) -> Result[Note]
  case try row.get("id").to_result("no id")
    Db.Value.Int(id) -> ok(Note(id: id, title: try text_of(row, "title"), body: try text_of(row, "body")))
    _ -> error("id is not an integer")
  end
end

def list_notes(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  rows = try Db.query(db, "select id, title, body from notes order by id", [])
  notes = rows.map do |row| note_of(row).unwrap! end
  ok(Bond.json_as(conn, 200, Notes.codec, Notes(notes: notes)))
end

# The body is a JSON object with a non-empty string `title` and a string `body`; anything else is one 400.
def parse_note(conn: Bond.Conn) -> Result[Note]
  text = try String.from_bytes(conn.body)
  json = try JSON.parse(text)
  return error("not an object") if JSON.kind(json) != "object"

  title = try JSON.string(try JSON.get(json, "title"))
  body = try JSON.string(try JSON.get(json, "body"))
  return error("empty title") if title.empty?

  ok(Note(id: 0, title: title, body: body))
end

def create_note(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  case parse_note(conn)
    error(_) -> ok(error_json(conn, 400, "invalid note"))
    ok(input) ->
      rows = try Db.query(
        db,
        "insert into notes (title, body) values (?, ?) returning id",
        [Db.Value.Text(input.title), Db.Value.Text(input.body)],
      )

      case try rows[0].get("id").to_result("no id")
        Db.Value.Int(id) -> ok(Bond.json_as(conn, 201, Note.codec, input.with(id: id)))
        _ -> error("insert gave no id")
      end
  end
end

# The id of the path, when it is digits and names a note.
def find_note(db: Db.Connection, conn: Bond.Conn) -> Result[Optional[Note]]
  text = try Bond.param(conn, "id")
  return ok(none) if text.empty? or not text.bytes.to_a.all? do |b| b >= 48 and b <= 57 end

  rows = try Db.query(db, "select id, title, body from notes where id = ?", [Db.Value.Int(try text.to_i)])
  return ok(none) if rows.empty?

  ok(some(try note_of(rows[0])))
end

def show_note(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  case try find_note(db, conn)
    some(note) -> ok(Bond.json_as(conn, 200, Note.codec, note))
    none -> ok(not_found(conn))
  end
end

def delete_note(db: Db.Connection, conn: Bond.Conn) -> Result[Bond.Conn]
  case try find_note(db, conn)
    some(note) ->
      try Db.execute(db, "delete from notes where id = ?", [Db.Value.Int(note.id)])
      ok(Bond.json(conn, 200, JSON.object({"deleted": JSON.from(note.id)})))

    none -> ok(not_found(conn))
  end
end
