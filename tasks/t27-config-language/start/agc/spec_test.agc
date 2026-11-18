## Runs the examples in cases/: agentica test spec_test.agc

def run_case(name: String) -> Result[Void]
  folder = "cases/#{name}"
  expected = try File.read_text("#{folder}/expected")
  child = try Process.spawn_captured("agentica", ["solution.agc", "#{folder}/main.conf"])
  output = try Process.output(child, 30000)
  code = try Process.wait(child, 30000)
  try Test.eq(output.stdout, expected)
  wanted = 0
  if expected.start_with?("error ")
    wanted = 1
  end
  Test.eq(code, wanted)
end

def test_cases() -> Result[Void]
  names = try Dir.list("cases")
  for name in names
    try run_case(name)
  end
  ok()
end
