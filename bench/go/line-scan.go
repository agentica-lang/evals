package main

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

func scale() int {
	if len(os.Args) > 1 {
		if n, err := strconv.Atoi(os.Args[1]); err == nil {
			return n
		}
	}
	return 1
}

func lineOf(i int) string {
	switch i % 6 {
	case 0:
		return "{"
	case 1:
		return fmt.Sprintf("  \"id\": \"0x%d\",", i)
	case 2:
		if i%12 == 2 {
			return "  \"kind\": \"CallExpr\","
		}
		return "  \"kind\": \"DeclRefExpr\","
	case 3:
		return "  \"inner\": ["
	case 4:
		return "  ]"
	default:
		return "}"
	}
}

func callsIn(lines []string) int {
	n := 0
	for _, line := range lines {
		text := strings.TrimSpace(line)
		if strings.HasPrefix(text, "\"kind\": \"CallExpr\"") || text == "}" {
			n++
		}
	}
	return n
}

func main() {
	count := 300000 * scale()
	path := filepath.Join(os.TempDir(), fmt.Sprintf("agentica-bench-line-scan-%d.json", os.Getpid()))
	file, err := os.Create(path)
	if err != nil {
		panic(err)
	}
	out := bufio.NewWriter(file)
	for i := 0; i < count; i++ {
		out.WriteString(lineOf(i) + "\n")
	}
	if err := out.Flush(); err != nil {
		panic(err)
	}
	file.Close()
	data, err := os.ReadFile(path)
	if err != nil {
		panic(err)
	}
	lines := strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
	found := 0
	for range 5 {
		found += callsIn(lines)
	}
	source, err := os.Open(path)
	if err != nil {
		panic(err)
	}
	scanner := bufio.NewScanner(source)
	calls, depth := 0, 0
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasSuffix(line, "{") {
			depth++
		} else if strings.HasPrefix(strings.TrimSpace(line), "\"kind\": \"CallExpr\"") {
			calls++
		}
	}
	source.Close()
	os.Remove(path)
	fmt.Printf("line-scan %d %d %d %d\n", len(lines), found, calls, depth)
}
