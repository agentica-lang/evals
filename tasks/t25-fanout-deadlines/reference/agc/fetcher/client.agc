struct Answer
  status: Int
  body: String
end

# One GET on a TCP connection of its own, read to its end. The socket belongs to the calling task, so cancelling
# that task closes the connection at once.
def get(url: String, timeout_ms: Int) -> Result[Answer]
  started = Time.monotonic_ms()
  rest = url.slice(7, url.length - 7)
  slash = rest.index_of("/").unwrap_or(rest.length)
  authority = rest.slice(0, slash)
  path = "/"
  if slash < rest.length
    path = rest.slice(slash, rest.length - slash)
  end

  parts = authority.split(":")
  port = 80
  if parts.size == 2
    port = try parts[1].to_i
  end

  socket = try TCP.connect(parts[0], port, timeout_ms)
  try TCP.send(socket, "GET #{path} HTTP/1.1\r\nHost: #{authority}\r\nConnection: close\r\n\r\n", timeout_ms)
  pieces: List[Bytes] = []
  open = true
  while open
    left = timeout_ms - (Time.monotonic_ms() - started)
    if left <= 0
      TCP.close(socket)
      return error("timed out")
    end

    piece = try TCP.recv_bytes(socket, 65536, left)
    if piece.size == 0
      open = false
    else
      pieces = pieces.push(piece)
    end
  end

  TCP.close(socket)
  parse(try String.from_bytes(Bytes.concat(pieces)))
end

private

def parse(text: String) -> Result[Answer]
  split = try text.index_of("\r\n\r\n").to_result("no head")
  head = text.slice(0, split).split("\r\n")
  body = text.slice(split + 4, text.length - split - 4)
  words = head[0].split(" ")
  if words.size < 2
    return error("bad status line")
  end

  status = try words[1].to_i
  lengths = head.drop(1).select { |line| line.downcase.start_with?("content-length:") }
  if lengths.size > 0
    expected = try lengths[0].slice(15, lengths[0].length - 15).strip.to_i
    if body.bytesize != expected
      return error("cut body")
    end
  end

  ok(Answer(status: status, body: body))
end
