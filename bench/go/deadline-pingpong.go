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

// receive and send wait at most a second, as the Agentica program's calls with a deadline do. Each goroutine
// resets one timer (since Go 1.23 a reset timer delivers no stale tick) instead of making one per call.
func receive(from chan int, timer *time.Timer) int {
	timer.Reset(time.Second)
	select {
	case value := <-from:
		return value
	case <-timer.C:
		panic("receive timed out")
	}
}

func send(to chan int, value int, timer *time.Timer) {
	timer.Reset(time.Second)
	select {
	case to <- value:
	case <-timer.C:
		panic("send timed out")
	}
}

func main() {
	rounds := 50000 * scale()
	a, b := make(chan int, 1), make(chan int, 1)
	echoed := make(chan int)
	go func() {
		timer := time.NewTimer(time.Second)
		total := 0
		for range rounds {
			value := receive(a, timer)
			send(b, value+1, timer)
			total += value
		}
		echoed <- total
	}()
	timer := time.NewTimer(time.Second)
	total := 0
	for i := 0; i < rounds; i++ {
		send(a, i, timer)
		total += receive(b, timer)
	}
	fmt.Printf("deadline-pingpong %d: checksum %d %d\n", rounds, total, <-echoed)
}
