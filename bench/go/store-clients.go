package main

import (
	"fmt"
	"os"
	"strconv"
	"sync"
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

type request struct {
	value int
	reply chan int
}

// receive and send wait at most 60 seconds, as the Agentica program's channel calls with a deadline do: a select on a
// timer that each goroutine resets (since Go 1.23 a reset timer delivers no stale tick).
func receive[T any](from chan T, timer *time.Timer) (T, bool) {
	timer.Reset(60 * time.Second)
	select {
	case value := <-from:
		return value, true
	case <-timer.C:
		var zero T
		return zero, false
	}
}

func send[T any](to chan T, value T, timer *time.Timer) bool {
	timer.Reset(60 * time.Second)
	select {
	case to <- value:
		return true
	case <-timer.C:
		return false
	}
}

func main() {
	clients, per := 50, 1000*scale()
	inbox := make(chan request, 64)
	stored := make(chan int)
	go func() {
		timer := time.NewTimer(time.Hour)
		total := 0
		for range clients * per {
			asked, ok := receive(inbox, timer)
			if !ok {
				stored <- -1
				return
			}
			for k := 0; k < 60; k++ {
				total += k % 3
			}
			total += asked.value
			send(asked.reply, total, timer)
		}
		stored <- total
	}()
	answered := make([]int, clients)
	var wg sync.WaitGroup
	for index := range answered {
		wg.Add(1)
		go func() {
			defer wg.Done()
			timer := time.NewTimer(time.Hour)
			reply := make(chan int, 1)
			for i := 0; i < per; i++ {
				send(inbox, request{i, reply}, timer)
				if _, ok := receive(reply, timer); !ok {
					answered[index] = -1
					return
				}
				answered[index]++
			}
		}()
	}
	wg.Wait()
	sum := 0
	for _, n := range answered {
		sum += n
	}
	fmt.Printf("store-clients %d: %d %d\n", clients*per, <-stored, sum)
}
