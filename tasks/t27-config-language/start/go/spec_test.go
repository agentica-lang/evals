// Runs the examples in cases/: go test
package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestCases(t *testing.T) {
	binary := filepath.Join(t.TempDir(), "solution")
	if out, err := exec.Command("go", "build", "-o", binary, ".").CombinedOutput(); err != nil {
		t.Fatalf("go build: %v\n%s", err, out)
	}
	cases, _ := filepath.Glob(filepath.Join("cases", "*"))
	for _, dir := range cases {
		t.Run(filepath.Base(dir), func(t *testing.T) {
			want, err := os.ReadFile(filepath.Join(dir, "expected"))
			if err != nil {
				t.Fatal(err)
			}
			out, _ := exec.Command(binary, filepath.Join(dir, "main.conf")).Output()
			if string(out) != string(want) {
				t.Errorf("got %q, want %q", out, want)
			}
		})
	}
}
