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

func fib(n int) int {
	if n < 2 {
		return n
	}
	return fib(n-1) + fib(n-2)
}

func add(a, b int) int { return a + b }

func mix(total, value int) int { return add(total*31, value) % 1000000007 }

func main() {
	rounds := 2 * scale()
	total := 0
	for round := 0; round < rounds; round++ {
		total = mix(total, fib(20+round%2))
		for i := 0; i < 20000; i++ {
			total = mix(total, i)
		}
	}
	fmt.Printf("calls %d: checksum %d\n", rounds, total)
}
