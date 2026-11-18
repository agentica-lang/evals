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

// table is a map behind a lock, the Go form of Agentica's ATS; eight goroutines write it at once.
type table struct {
	mu   sync.Mutex
	data map[int]int
}

func (t *table) add(key, delta int) {
	t.mu.Lock()
	t.data[key] += delta
	t.mu.Unlock()
}

func (t *table) put(key, value int) {
	t.mu.Lock()
	t.data[key] = value
	t.mu.Unlock()
}

func (t *table) remove(key int) {
	t.mu.Lock()
	delete(t.data, key)
	t.mu.Unlock()
}

func main() {
	rounds := 20000 * scale()
	shared := &table{data: map[int]int{}}
	done := make([]int, 8)
	var wg sync.WaitGroup
	for task := range done {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < rounds; i++ {
				shared.add(i%16, 1)
				own := 1000*(task+1) + i%500
				shared.put(own, i)
				if i%2 == 0 {
					shared.remove(own)
				}
			}
			done[task] = rounds
		}()
	}
	wg.Wait()
	total, sum := 0, 0
	for _, n := range done {
		total += n
	}
	for key := 0; key < 16; key++ {
		sum += shared.data[key]
	}
	fmt.Printf("ats-writers %d: checksum %d %d %d\n", rounds, total, sum, len(shared.data))
}
