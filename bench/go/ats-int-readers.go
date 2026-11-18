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

// table is a map behind a read-write lock, the Go form of Agentica's ATS; eight goroutines read it at once.
type table struct {
	mu   sync.RWMutex
	data map[int]int
}

func (t *table) get(key int) int {
	t.mu.RLock()
	defer t.mu.RUnlock()
	return t.data[key]
}

func main() {
	rounds := 150000 * scale()
	shared := &table{data: map[int]int{}}
	for n := 0; n < 1000; n++ {
		shared.data[n] = n
	}
	parts := make([]int, 8)
	var wg sync.WaitGroup
	for task := range parts {
		wg.Add(1)
		go func() {
			defer wg.Done()
			part := 0
			for i := 0; i < rounds; i++ {
				part = (part + shared.get((i*31+task)%1000)) % 1000000007
			}
			parts[task] = part
		}()
	}
	wg.Wait()
	total := 0
	for _, part := range parts {
		total += part
	}
	fmt.Printf("ats-int-readers %d: checksum %d\n", rounds, total%1000000007)
}
