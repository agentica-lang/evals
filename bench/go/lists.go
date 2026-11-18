package main

import (
	"fmt"
	"os"
	"slices"
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
	rounds := 30 * scale()
	total := 0
	for round := 0; round < rounds; round++ {
		xs := make([]int, 1000)
		for i := range xs {
			xs[i] = (i*7919 + round*104729) % 10007
		}
		evens := []int{}
		for _, x := range xs {
			if x%2 == 0 {
				evens = append(evens, x)
			}
		}
		squares := 0
		for _, x := range evens {
			squares += x * x
		}
		ordered := slices.Clone(xs)
		slices.Sort(ordered)
		big := slices.ContainsFunc(xs, func(x int) bool { return x > 10000 })
		count := 0
		for _, x := range ordered {
			if x > ordered[500] {
				break
			}
			count++
		}
		total = (total + squares + ordered[0] + ordered[len(ordered)-1] + len(evens) + count) % 1000000007
		if big {
			total++
		}
	}
	fmt.Printf("lists %d: checksum %d\n", rounds, total)
}
