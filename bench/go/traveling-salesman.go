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

type tour struct {
	cost  int
	route []int
}

func search(distances [][]int, visited []bool, path []int, cost int, best tour) tour {
	current := path[len(path)-1]
	if len(path) == len(distances) {
		total := cost + distances[current][0]
		if total < best.cost {
			return tour{total, append(append([]int{}, path...), 0)}
		}
		return best
	}
	for city := 1; city < len(distances); city++ {
		if !visited[city] {
			next := cost + distances[current][city]
			if next < best.cost {
				visited[city] = true
				best = search(distances, visited, append(path, city), next, best)
				visited[city] = false
			}
		}
	}
	return best
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

func makeDistances(count, seed int) [][]int {
	state := seed
	points := make([][2]int, count)
	for i := range points {
		state = (state*1103515245 + 12345) % 2147483648
		x := state / 65536 % 1000
		state = (state*1103515245 + 12345) % 2147483648
		points[i] = [2]int{x, state / 65536 % 1000}
	}
	distances := make([][]int, count)
	for i, a := range points {
		distances[i] = make([]int, count)
		for j, b := range points {
			distances[i][j] = abs(a[0]-b[0]) + abs(a[1]-b[1])
		}
	}
	return distances
}

func main() {
	cities, rounds := 9, scale()
	checksum := 0
	for round := 0; round < rounds; round++ {
		distances := makeDistances(cities, round+7)
		visited := make([]bool, cities)
		visited[0] = true
		best := search(distances, visited, []int{0}, 0, tour{1000000000, nil})
		route := make([]string, len(best.route))
		for i, city := range best.route {
			route[i] = strconv.Itoa(city)
		}
		fmt.Printf("round %d: cost %d, route [%s]\n", round, best.cost, strings.Join(route, ", "))
		checksum = (checksum*31 + best.cost) % 1000000007
	}
	fmt.Printf("traveling-salesman %d: checksum %d\n", rounds, checksum)
}
