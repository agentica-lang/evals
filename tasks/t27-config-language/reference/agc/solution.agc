import Loader from "conf/loader"
import Output from "conf/output"

def main() -> Void
  args = System.args()
  path = args[0]
  parts = path.split("/")
  name = parts.last
  folder = parts.take(parts.size - 1).join("/")
  if folder == ""
    folder = "."
  end
  case Loader.run(folder, name)
    ok(value) -> puts(Output.to_json(value))
    error(e) ->
      where = e.message.split(" ")
      puts("error #{where[1]} at #{where[0]}:#{where[2]}:#{where[3]}")
      System.exit(1)
  end
end
