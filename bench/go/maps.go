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

func main() {
	rounds := 5 * scale()
	checksum := 0
	for round := 0; round < rounds; round++ {
		counts := map[int]int{}
		for i := 0; i < 6000; i++ {
			counts[(i*7919+round)%1009]++
		}
		for j := 0; j < 1009; j += 3 {
			delete(counts, j)
		}
		for key, count := range counts {
			checksum = (checksum + key*count) % 1000000007
		}
		checksum = (checksum + len(counts)) % 1000000007
	}
	fmt.Printf("maps %d: checksum %d\n", rounds, checksum)
}
