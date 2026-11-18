package main

import (
	"fmt"
	"os"
	"strconv"
)

func scale() int {
	if len(os.Args) > 1 {
		if n, err := strconv.Atoi(os.Args[1]); err == nil {
			return n
		}
	}
	return 1
}

func collatzLength(n int) int {
	steps := 0
	for n != 1 {
		if n%2 == 0 {
			n /= 2
		} else {
			n = 3*n + 1
		}
		steps++
	}
	return steps
}

func main() {
	limit := 2500 * scale()
	total, longest := 0, 0
	for n := 1; n <= limit; n++ {
		steps := collatzLength(n)
		total += steps
		longest = max(longest, steps)
	}
	fmt.Printf("collatz %d: total %d, longest %d\n", limit, total, longest)
}
