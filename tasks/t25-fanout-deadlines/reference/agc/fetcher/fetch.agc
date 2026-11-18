import Client from "client"
import {Job} from "job"

LIMIT = 1024

enum Outcome
  Response(Int, String)
  Failed
end

struct Request
  url: String
  timeout_ms: Int
  inbox: Channel[Outcome]
end


def run(job: Job, ends_at: Int) -> List[String]
  slots = [[job.concurrency, LIMIT].min.unwrap_or(1), 1].max.unwrap_or(1)
  results = Task.map(job.urls, slots, job.deadline_ms + 1000) do |url|
    ok(fetch(url, job, ends_at))
  end
  results.map { |result| result.unwrap_or("error deadline") }
end

private

def fetch(url: String, job: Job, ends_at: Int) -> String
  backoff = job.backoff_ms
  outcome = Outcome.Failed
  for retry in 0..job.retries
    if Time.monotonic_ms() >= ends_at
      return "error deadline"
    end

    outcome = attempt(url, job, ends_at)
    if Time.monotonic_ms() >= ends_at
      return "error deadline"
    end

    if !retryable(outcome)
      return describe(outcome)
    end

    if retry < job.retries
      Task.sleep([backoff, ends_at - Time.monotonic_ms()].min.unwrap_or(0).clamp(0, backoff))
      backoff = backoff * 2
    end
  end

  describe(outcome)
end

def retryable(outcome: Outcome) -> Bool
  case outcome
    Outcome.Response(status, _) -> status >= 500 and status <= 599
    Outcome.Failed -> true
  end
end

def send_request(request: Request) -> Void
  outcome = case Client.get(request.url, request.timeout_ms)
    ok(answer) -> Outcome.Response(answer.status, answer.body)
    error(_) -> Outcome.Failed
  end
  _ = request.inbox.send(outcome, 1000)
end

# One attempt: a request, a hedge after hedge_ms while no answer came, and the first response wins. The other
# request is cancelled, which closes its connection.
def attempt(url: String, job: Job, ends_at: Int) -> Outcome
  inbox: Channel[Outcome] = Channel.new(2)
  timeout = [job.request_timeout_ms, ends_at - Time.monotonic_ms()].min.unwrap_or(1).clamp(1, job.request_timeout_ms)
  tasks = [Task.spawn(&send_request, Request(url: url, timeout_ms: timeout, inbox: inbox))]
  hedge_at = Time.monotonic_ms() + job.hedge_ms
  running = 1
  hedge_pending = job.hedge_ms > 0
  outcome = Outcome.Failed
  while running > 0
    now = Time.monotonic_ms()
    until_next = ends_at - now
    if hedge_pending
      until_next = hedge_at - now
    end

    received = inbox.recv(until_next.clamp(0, until_next.abs))
    case received
      ok(Outcome.Response(status, body)) ->
        outcome = Outcome.Response(status, body)
        running = 0
      ok(Outcome.Failed) ->
        running = running - 1
        if hedge_pending
          running = 0
        end
      error(_) ->
        if hedge_pending and Time.monotonic_ms() < ends_at
          hedge_pending = false
          rest = [job.request_timeout_ms, ends_at - Time.monotonic_ms()].min.unwrap_or(1).clamp(1, job.request_timeout_ms)
          tasks = tasks.push(Task.spawn(&send_request, Request(url: url, timeout_ms: rest, inbox: inbox)))
          running = running + 1
        else
          running = 0
        end
    end
  end

  tasks.each { |task| Task.cancel(task) }
  outcome
end

def describe(outcome: Outcome) -> String
  case outcome
    Outcome.Failed -> "error no response"
    Outcome.Response(status, body) ->
      if status != 200
        "error status #{status}"
      else
        case value(body)
          ok(n) -> "ok #{n}"
          error(_) -> "error body"
        end
      end
  end
end

def value(body: String) -> Result[Int]
  json = try JSON.parse(body)
  field = try JSON.get(json, "value")
  JSON.int(field)
end
