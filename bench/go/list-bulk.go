package main

import (
	"fmt"
	"os"
	"slices"
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
	rounds := 4 * scale()
	total := 0
	for round := 0; round < rounds; round++ {
		filled := slices.Repeat([]int{round}, 500000)
		numbers := make([]int, 500000)
		for i := range numbers {
			numbers[i] = i
		}
		backwards := slices.Clone(numbers)
		slices.Reverse(backwards)
		head := slices.Clone(backwards[:250000])
		tail := slices.Clone(backwards[250000:])
		joined := slices.Concat(head, tail)
		text := strings.Join(slices.Repeat([]string{"x"}, 300000), "")
		letters := strings.Split(text, "")
		ordered := slices.Clone(backwards[:60000])
		slices.Sort(ordered)
		total = (total + filled[round] + numbers[round] + backwards[round] + len(head) + len(tail) +
			joined[499999] + len(letters) + len(text) + ordered[round]) % 1000000007
	}
	fmt.Printf("list-bulk %d: checksum %d\n", rounds, total)
}
