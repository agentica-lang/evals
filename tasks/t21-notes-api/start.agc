import Bond from "pkg/bond/bond"
import Db from "pkg/db/db"
import Sqlite from "pkg/db/sqlite"

SCHEMA = "create table if not exists notes (id integer primary key, title text not null, body text not null)"

def main() -> Void
  args = System.args()
  conn = Db.open("sqlite:#{args[0]}", [Sqlite.driver()]).unwrap!
  Db.execute(conn, SCHEMA, []).unwrap!
  on_health = handler do |c| ok(Bond.json(c, 200, JSON.object({"status": JSON.from("ok")}))) end
  app = Bond.app() |> Bond.get("/health", on_health)
  server = Bond.start(app, "127.0.0.1", 0).unwrap!
  puts("listening #{Bond.local_port(server)}")
  IO.flush()
  Bond.wait(server).unwrap!
end

# Gives a `do` block the type of a handler, so that a name can hold it before the pipeline that uses it.
def handler(f: Bond.Handler) -> Bond.Handler = f
