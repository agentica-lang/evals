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
	n := 20000 * scale()
	xs := []int{}
	for i := 0; i < n; i++ {
		xs = append(xs, (i*7919)%10007)
	}
	for j := 0; j < n; j++ {
		xs[(j*7919)%n] = j
	}
	total := 0
	for _, x := range xs {
		total = (total*31 + x) % 1000000007
	}
	fmt.Printf("list-build %d: checksum %d\n", n, total)
}
