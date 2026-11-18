package main

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

func scale() int {
	if len(os.Args) > 1 {
		if n, err := strconv.Atoi(os.Args[1]); err == nil {
			return n
		}
	}
	return 1
}

func nap(index int) int {
	total := 0
	for k := 0; k < 10; k++ {
		time.Sleep(time.Millisecond)
		total += index + k
	}
	return total
}

func quick(index int) int { return index*3 + 1 }

func main() {
	rounds := 2 * scale()
	total := 0
	for range rounds {
		results := make([]chan int, 100)
		for i := range results {
			results[i] = make(chan int, 1)
			go func() { results[i] <- nap(i) }()
		}
		for _, result := range results {
			total += <-result
		}
		// Phase two: each await has a 60-second deadline, which the finished task beats.
		timer := time.NewTimer(time.Hour)
		for j := 0; j < 3000; j++ {
			result := make(chan int, 1)
			go func() { result <- quick(j) }()
			timer.Reset(60 * time.Second)
			select {
			case value := <-result:
				total += value
			case <-timer.C:
				total--
			}
		}
	}
	fmt.Printf("sleepers %d: checksum %d\n", rounds, total)
}
