struct Job
  concurrency: Int
  request_timeout_ms: Int
  deadline_ms: Int
  hedge_ms: Int
  retries: Int
  backoff_ms: Int
  urls: List[String]
end

def load(path: String) -> Result[Job]
  text = try File.read_text(path)
  job = try JSON.decode(text, Job)
  positive = [job.concurrency, job.request_timeout_ms, job.deadline_ms, job.backoff_ms].all? { |n| n >= 1 }
  if !positive or job.hedge_ms < 0 or job.retries < 0
    return error("bad job file")
  end

  web = job.urls.all? { |url| url.start_with?("http://") }
  if !web
    return error("bad job file")
  end

  ok(job)
end
