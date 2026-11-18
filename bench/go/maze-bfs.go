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

func makeMaze(width, height, seed int) map[int]bool {
	cells := map[int]bool{}
	state := seed
	for square := 0; square < width*height; square++ {
		state = (state*1103515245 + 12345) % 2147483648
		if state/65536%100 < 70 || square == 0 || square == width*height-1 {
			cells[square] = true
		}
	}
	return cells
}

func neighbors(width, height, square int) []int {
	x, y := square%width, square/width
	result := []int{}
	if y > 0 {
		result = append(result, square-width)
	}
	if x+1 < width {
		result = append(result, square+1)
	}
	if y+1 < height {
		result = append(result, square+width)
	}
	if x > 0 {
		result = append(result, square-1)
	}
	return result
}

func shortest(cells map[int]bool, width, height, start, goal int) int {
	queue := []int{start}
	previous := map[int]int{}
	seen := map[int]bool{start: true}
	for len(queue) > 0 {
		current := queue[0]
		queue = queue[1:]
		if current == goal {
			length := 0
			for current != start {
				current = previous[current]
				length++
			}
			return length
		}
		for _, next := range neighbors(width, height, current) {
			if cells[next] && !seen[next] {
				seen[next] = true
				previous[next] = current
				queue = append(queue, next)
			}
		}
	}
	return -1
}

func main() {
	rounds := 4 * scale()
	width, height := 40, 40
	checksum, solved := 0, 0
	for round := 0; round < rounds; round++ {
		cells := makeMaze(width, height, round+1)
		distance := shortest(cells, width, height, 0, width*height-1)
		if distance >= 0 {
			solved++
		}
		checksum = (checksum*1000 + distance + 1) % 1000000007
	}
	fmt.Printf("maze-bfs %d: solved %d, checksum %d\n", rounds, solved, checksum)
}
