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

// receive and send wait at most 5 seconds, as the Agentica program's channel calls with a deadline do: a select on a
// timer that each goroutine resets (since Go 1.23 a reset timer delivers no stale tick).
func receive[T any](from chan T, timer *time.Timer) (T, bool) {
	timer.Reset(5 * time.Second)
	select {
	case value := <-from:
		return value, true
	case <-timer.C:
		var zero T
		return zero, false
	}
}

func send[T any](to chan T, value T, timer *time.Timer) bool {
	timer.Reset(5 * time.Second)
	select {
	case to <- value:
		return true
	case <-timer.C:
		return false
	}
}

func main() {
	rounds := 100000 * scale()
	ping, pong := make(chan int, 1), make(chan int, 1)
	echoed := make(chan int)
	go func() {
		timer := time.NewTimer(time.Hour)
		count := 0
		for range rounds {
			value, ok := receive(ping, timer)
			if !ok {
				echoed <- -1
				return
			}
			send(pong, value+1, timer)
			count++
		}
		echoed <- count
	}()
	timer := time.NewTimer(time.Hour)
	total := 0
	for i := 0; i < rounds; i++ {
		send(ping, i, timer)
		value, ok := receive(pong, timer)
		if !ok {
			return
		}
		total += value
	}
	fmt.Printf("channel-pingpong %d: checksum %d %d\n", rounds, total, <-echoed)
}
