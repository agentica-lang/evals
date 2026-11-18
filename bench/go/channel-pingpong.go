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
	rounds := 100000 * scale()
	ping, pong := make(chan int, 1), make(chan int, 1)
	echoed := make(chan int)
	go func() {
		count := 0
		for range rounds {
			pong <- <-ping + 1
			count++
		}
		echoed <- count
	}()
	total := 0
	for i := 0; i < rounds; i++ {
		ping <- i
		total += <-pong
	}
	fmt.Printf("channel-pingpong %d: checksum %d %d\n", rounds, total, <-echoed)
}
