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

type op interface{ isOp() }

type add struct{ n int }
type sub struct{ n int }
type mul struct{ n int }
type mod struct{ n int }
type neg struct{}
type twice struct{}

func (add) isOp()   {}
func (sub) isOp()   {}
func (mul) isOp()   {}
func (mod) isOp()   {}
func (neg) isOp()   {}
func (twice) isOp() {}

// floorMod is the modulo of Agentica and Python: the sign of the divisor.
func floorMod(a, b int) int { return ((a % b) + b) % b }

func apply(acc int, o op) int {
	switch o := o.(type) {
	case add:
		return acc + o.n
	case sub:
		return acc - o.n
	case mul:
		return acc * o.n
	case mod:
		return floorMod(acc, o.n)
	case neg:
		return -acc
	case twice:
		return acc * 2
	default:
		panic("unknown op")
	}
}

func bucket(value int) int {
	switch floorMod(value, 4) {
	case 0:
		return 3
	case 1:
		return 5
	case 2:
		return 7
	default:
		return 11
	}
}

func main() {
	program := []op{add{7}, mul{13}, twice{}, sub{5}, mod{1000003}, neg{}, add{1000003}, mul{3}, mod{999983}}
	rounds := 5000 * scale()
	acc, checksum := 1, 0
	for range rounds {
		for _, o := range program {
			acc = apply(acc, o)
		}
		checksum = floorMod(checksum+bucket(acc)*acc, 1000000007)
	}
	fmt.Printf("case %d: acc %d, checksum %d\n", rounds, acc, checksum)
}
