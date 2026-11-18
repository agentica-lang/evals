package main

import (
	"fmt"
	"os"
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

func main() {
	words := []string{"alpha", "beta", "gamma", "delta", "epsilon"}
	rounds := 2000 * scale()
	distinct := 0
	last := ""
	for round := 0; round < rounds; round++ {
		var line strings.Builder
		fmt.Fprintf(&line, "%d:", round)
		for k, word := range words {
			fmt.Fprintf(&line, " %s=%d", word, (round*31+k*7)%97)
		}
		for i := 0; i < 10; i++ {
			fmt.Fprintf(&line, "[%d]", i*round%13)
		}
		if line.String() != last {
			distinct++
		}
		last = line.String()
	}
	fmt.Printf("strings %d: distinct %d\n", rounds, distinct)
	fmt.Println(last)
}
