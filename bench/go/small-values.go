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

const blanks = " \t\n\f\r"

func main() {
	rounds := 2 * scale()
	text := strings.Join(slices.Repeat([]string{"ab,cd ef,,g"}, 3000), " ")
	n := len(text)
	checksum := 0
	for range rounds {
		// One-character Strings: at, slice, from_code and split("").
		for i := 0; i < n; i++ {
			checksum += int(text[i]) + int(text[i : i+1][0]) + int(string(rune(97 + i%26))[0])
		}
		checksum += len(strings.Split(text, ""))

		// Empty Strings: pieces between separators, a slice of no characters, blanks trimmed away and a join of nothing.
		for _, piece := range strings.Split(text, ",") {
			checksum += len(piece[0:0]) + len(strings.Trim("  ", blanks)) + len(strings.Trim(piece, blanks)) +
				len(strings.Join([]string{}, ","))
		}

		// Empty Lists and Maps: a default for a missing key, a seed for reduce, a filter that keeps nothing.
		groups := map[int][]int{}
		for j := 0; j < 8000; j++ {
			groups[j%101] = append(append([]int{}, groups[j%101]...), j)
		}
		counts := map[int]int{}
		for _, word := range strings.Split(text, " ") {
			counts[len(word)]++
		}
		drops := 0
		for k := 0; k < 8000; k++ {
			kept := []int{}
			for _, x := range []int{k, k + 1, k + 2, k + 3} {
				if x < 0 {
					kept = append(kept, x)
				}
			}
			drops += len(kept)
		}
		checksum += len(groups) + len(groups[7]) + len(counts) + counts[2] + drops

		// Empty Sets: a Set built from nothing, the last element deleted and a difference with nothing left.
		seen := 0
		for m := 0; m < 8000; m++ {
			one := map[int]bool{m: true}
			minusM := map[int]bool{}
			for key := range one {
				if key != m {
					minusM[key] = true
				}
			}
			minusOne := map[int]bool{}
			for key := range one {
				if !one[key] {
					minusOne[key] = true
				}
			}
			seen += len(map[int]bool{}) + len(minusM) + len(minusOne)
		}
		checksum = (checksum + seen) % 1000000007
	}
	fmt.Printf("small-values %d: checksum %d\n", rounds, checksum)
}
