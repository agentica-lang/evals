import Fetch from "fetcher/fetch"
import Jobs from "fetcher/job"

def main() -> Void
  began = Time.monotonic_ms()
  args = System.args()
  loaded: Result[Jobs.Job] = error("no job file")
  if args.size == 1
    loaded = Jobs.load(args[0])
  end

  case loaded
    error(_) ->
      puts("error: bad job file")
      System.exit(2)
    ok(job) ->
      results = Fetch.run(job, began + job.deadline_ms)
      results.each_with_index do |result, index|
        puts("#{index + 1} #{result}")
      end
      count = results.count { |result| result.start_with?("ok ") }
      puts("ok #{count} of #{results.size}")
  end
end
