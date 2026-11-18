package main

import (
	"bufio"
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
	lines := 200000 * scale()
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()
	for i := 0; i < lines; i++ {
		fmt.Fprintf(out, "line number %d with some text\n", i%1000)
	}
	fmt.Fprintf(out, "print-lines %d\n", lines)
}
