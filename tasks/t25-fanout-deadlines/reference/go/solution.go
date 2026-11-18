package main

import (
	"fmt"
	"os"
	"strings"
	"time"

	"solution/fetch"
	"solution/job"
)

func main() {
	began := time.Now()
	if len(os.Args) < 2 {
		fmt.Println("error: bad job file")
		os.Exit(2)
	}
	j, err := job.Load(os.Args[1])
	if err != nil {
		fmt.Println("error: bad job file")
		os.Exit(2)
	}
	results := fetch.Run(j, began)
	ok := 0
	for index, result := range results {
		fmt.Printf("%d %s\n", index+1, result)
		if strings.HasPrefix(result, "ok ") {
			ok++
		}
	}
	fmt.Printf("ok %d of %d\n", ok, len(results))
}
