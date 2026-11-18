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

// table is a map behind a lock, the Go form of Agentica's ATS (a table that tasks share).
type table struct {
	mu   sync.Mutex
	data map[int]int
}

func (t *table) add(key, delta int) {
	t.mu.Lock()
	t.data[key] += delta
	t.mu.Unlock()
}

func (t *table) get(key int) int {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.data[key]
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
	rounds := 5 * scale()
	checksum := 0
	for round := 0; round < rounds; round++ {
		counts := &table{data: map[int]int{}}
		for i := 0; i < 6000; i++ {
			key := (i*7919 + round) % 1009
			if i%2 == 0 {
				counts.add(key, 1)
			} else {
				counts.put(key, counts.get(key)+1)
			}
		}
		for j := 0; j < 1009; j += 3 {
			counts.remove(j)
		}
		counts.mu.Lock()
		for key, count := range counts.data {
			checksum = (checksum + key*count) % 1000000007
		}
		checksum = (checksum + len(counts.data)) % 1000000007
		counts.mu.Unlock()
	}
	fmt.Printf("ats %d: checksum %d\n", rounds, checksum)
}
