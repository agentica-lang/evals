package main

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
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
	lines := 300000 * scale()
	path := filepath.Join(os.TempDir(), fmt.Sprintf("agentica-bench-read-lines-%d.txt", os.Getpid()))
	file, err := os.Create(path)
	if err != nil {
		panic(err)
	}
	out := bufio.NewWriter(file)
	for i := 0; i < lines; i++ {
		fmt.Fprintf(out, "|-DeclRefExpr 0x%d <line:%d:%d> 'int' lvalue Var 'x'\n", i, i, i%80)
	}
	if err := out.Flush(); err != nil {
		panic(err)
	}
	file.Close()
	source, err := os.Open(path)
	if err != nil {
		panic(err)
	}
	scanner := bufio.NewScanner(source)
	count, total := 0, 0
	for scanner.Scan() {
		count++
		total += len(scanner.Text())
	}
	source.Close()
	os.Remove(path)
	fmt.Printf("read-lines %d %d\n", count, total)
}
