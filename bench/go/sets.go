package main

import (
	"fmt"
	"maps"
	"os"
	"slices"
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

// orderedSet keeps the first-insertion order that Agentica's Set promises: a removed key stays in keys and is
// skipped, as a Python dict's pop costs no shift either; a key added again after its removal goes to the end.
type orderedSet struct {
	member map[int]bool
	listed map[int]bool
	keys   []int
}

func newSet() *orderedSet { return &orderedSet{member: map[int]bool{}, listed: map[int]bool{}} }

func (s *orderedSet) add(key int) {
	if s.member[key] {
		return
	}
	if s.listed[key] {
		s.keys = slices.DeleteFunc(s.keys, func(k int) bool { return k == key })
	}
	s.member[key] = true
	s.listed[key] = true
	s.keys = append(s.keys, key)
}

func (s *orderedSet) has(key int) bool { return s.member[key] }

func (s *orderedSet) remove(key int) { delete(s.member, key) }

func (s *orderedSet) each(visit func(int)) {
	for _, key := range s.keys {
		if s.member[key] {
			visit(key)
		}
	}
}

func main() {
	rounds := 5 * scale()
	checksum := 0
	for round := 0; round < rounds; round++ {
		seen := newSet()
		for i := 0; i < 6000; i++ {
			seen.add((i*7919 + round) % 1009)
		}
		hits := 0
		for j := 0; j < 6000; j++ {
			if seen.has((j*31 + round) % 2003) {
				hits++
			}
		}
		for k := 0; k < 1009; k += 3 {
			seen.remove(k)
		}
		low := newSet()
		for key := round; key < round+500; key++ {
			low.add(key)
		}
		both, rest := 0, 0
		seen.each(func(key int) {
			if low.has(key) {
				both++
			} else {
				rest++
			}
		})
		either := maps.Clone(seen.member)
		low.each(func(key int) { either[key] = true })
		position := 0
		seen.each(func(key int) {
			position++
			checksum = (checksum + key*position) % 1000000007
		})
		checksum = (checksum + hits + len(seen.member) + both + len(either) + rest) % 1000000007
	}
	fmt.Printf("sets %d: checksum %d\n", rounds, checksum)
}
