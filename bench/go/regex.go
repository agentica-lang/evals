package main

import (
	"fmt"
	"os"
	"regexp"
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

func makeLog(lines int) string {
	levels := []string{"INFO", "INFO", "INFO", "WARN", "INFO", "ERROR", "INFO", "DEBUG"}
	users := []string{"alice", "bob", "carol", "dave", "erin"}
	parts := make([]string, lines)
	for i := range parts {
		tail := "ok"
		if i%97 == 0 {
			tail = "timeout after 30s"
		}
		stamp := fmt.Sprintf("2026-11-01T12:%d:%d", (i/60)%60, i%60)
		parts[i] = fmt.Sprintf("%s %s user=%s id=%d path=/api/items/%d %s", stamp, levels[i%8], users[i%5], i*7, i%1000, tail)
	}
	return strings.Join(parts, "\n")
}

func main() {
	log := makeLog(15000 * scale())
	head := log[:min(100000, len(log))]
	literal := regexp.MustCompile("timeout")
	word := regexp.MustCompile("[a-z]+")
	words := regexp.MustCompile(`\b(?:alpha|bravo|charlie|delta|echo|foxtrot|golf|hotel|india|user)\b`)
	scan := regexp.MustCompile(`(?m)^(\S+) ERROR user=(\w+) id=(\d+)`)
	redos := regexp.MustCompile(`(a+)+$`)
	ids := 0
	for _, match := range scan.FindAllStringSubmatch(log, -1) {
		id, _ := strconv.Atoi(match[3])
		ids += id
	}
	found := redos.MatchString(strings.Repeat("a", 20) + "!")
	fmt.Printf("regex %d: %d %d %d %d %t\n", len(log), len(literal.FindAllStringIndex(log, -1)),
		len(word.FindAllStringIndex(head, -1)), len(words.FindAllStringIndex(head, -1)), ids, found)
}
