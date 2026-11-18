package main

import (
	"fmt"
	"os"
	"path/filepath"

	"solution/conf"
)

func main() {
	path := os.Args[1]
	value, err := conf.Run(filepath.Dir(path), filepath.Base(path))
	if err != nil {
		fmt.Printf("error %s at %s:%d:%d\n", err.Code, err.File, err.Line, err.Col)
		os.Exit(1)
	}
	fmt.Println(conf.JSON(value))
}
