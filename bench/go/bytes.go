package main

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"io"
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

func block() []byte {
	items := make([]byte, 65536)
	x := 12345
	for k := range items {
		x = (x*1103515245 + 12345) % 2147483648
		items[k] = byte((x / 65536) % 256)
	}
	return items
}

func zlibRoundTrip(data []byte) int {
	const part = 524288
	same := 0
	for at := 0; at < len(data); at += part {
		piece := data[at:min(at+part, len(data))]
		var packed bytes.Buffer
		writer, _ := gzip.NewWriterLevel(&packed, 6)
		writer.Write(piece)
		writer.Close()
		reader, err := gzip.NewReader(&packed)
		if err != nil {
			continue
		}
		unpacked, err := io.ReadAll(reader)
		if err == nil && bytes.Equal(unpacked, piece) {
			same++
		}
	}
	return same
}

func binarySum(data []byte, size int) int {
	total := 0
	for at := 0; at < size; at += 4 {
		total = (total + int(binary.LittleEndian.Uint32(data[at:]))) % 1000000007
	}
	return total
}

// fileRoundTrip writes data in 1 MiB chunks, reads it back in chunks and hashes what it reads. The Python twin joins
// the chunks before hashing; hashing as they come gives the same digest without the copy.
func fileRoundTrip(data []byte, path string) string {
	const chunk = 1048576
	file, err := os.Create(path)
	if err != nil {
		panic(err)
	}
	for at := 0; at < len(data); at += chunk {
		if _, err := file.Write(data[at:min(at+chunk, len(data))]); err != nil {
			panic(err)
		}
	}
	if err := file.Close(); err != nil {
		panic(err)
	}
	source, err := os.Open(path)
	if err != nil {
		panic(err)
	}
	hash := sha256.New()
	buffer := make([]byte, chunk)
	for {
		n, err := source.Read(buffer)
		hash.Write(buffer[:n])
		if err != nil {
			break
		}
	}
	source.Close()
	os.Remove(path)
	return hex.EncodeToString(hash.Sum(nil))
}

func main() {
	mib := 4 * scale()
	data := bytes.Repeat(block(), 16*mib)
	sum := sha256.Sum256(data)
	digest := hex.EncodeToString(sum[:])
	same := zlibRoundTrip(data)
	total := binarySum(data, 1048576*scale())
	path := filepath.Join(os.TempDir(), fmt.Sprintf("agentica-bench-bytes-%d.bin", os.Getpid()))
	readBack := fileRoundTrip(data, path)
	fmt.Printf("bytes %d: checksum %s %d %d %t\n", mib, digest[:16], same, total, readBack == digest)
}
