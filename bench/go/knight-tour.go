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

var moves = [][2]int{{1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}}

func destinations(size, square int, visited []bool) []int {
	result := []int{}
	for _, move := range moves {
		x := square%size + move[0]
		y := square/size + move[1]
		if 0 <= x && x < size && 0 <= y && y < size && !visited[y*size+x] {
			result = append(result, y*size+x)
		}
	}
	return result
}

func search(size, square int, visited []bool, path *[]int) bool {
	visited[square] = true
	*path = append(*path, square)
	if len(*path) == size*size {
		return true
	}
	candidates := destinations(size, square, visited)
	onward := make([]int, len(candidates))
	for i, candidate := range candidates {
		onward[i] = len(destinations(size, candidate, visited))
	}
	order := make([]int, len(candidates))
	for i := range order {
		order[i] = i
	}
	slices.SortStableFunc(order, func(a, b int) int { return onward[a] - onward[b] })
	for _, index := range order {
		if search(size, candidates[index], visited, path) {
			return true
		}
	}
	visited[square] = false
	*path = (*path)[:len(*path)-1]
	return false
}

func main() {
	size, rounds := 8, scale()
	tours, checksum := 0, 0
	for range rounds {
		for start := 0; start < size*size; start += 3 {
			path := []int{}
			if search(size, start, make([]bool, size*size), &path) {
				tours++
				for step, square := range path {
					checksum = (checksum*31 + square*(step+1)) % 1000000007
				}
			}
		}
	}
	fmt.Printf("knight-tour %d: tours %d, checksum %d\n", rounds, tours, checksum)
}
