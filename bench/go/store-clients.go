package main

import (
	"fmt"
	"os"
	"strconv"
	"sync"
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

func main() {
	clients, per := 50, 1000*scale()
	inbox := make(chan request, 64)
	stored := make(chan int)
	go func() {
		total := 0
		for range clients * per {
			asked := <-inbox
			for k := 0; k < 60; k++ {
				total += k % 3
			}
			total += asked.value
			asked.reply <- total
		}
		stored <- total
	}()
	answered := make([]int, clients)
	var wg sync.WaitGroup
	for index := range answered {
		wg.Add(1)
		go func() {
			defer wg.Done()
			reply := make(chan int, 1)
			for i := 0; i < per; i++ {
				inbox <- request{i, reply}
				<-reply
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
