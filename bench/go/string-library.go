package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

func scale() int {
	if len(os.Args) > 1 {
		if n, err := strconv.Atoi(os.Args[1]); err == nil {
			return n
		}
	}
	return 1
}

// upper and lower add the Unicode special casing that Agentica and Python apply and Go's ToUpper and ToLower do
// not: ß upper-cases to SS, and a capital sigma at the end of a word lower-cases to the final ς.
func upper(text string) string { return strings.ReplaceAll(strings.ToUpper(text), "ß", "SS") }

func lower(text string) string {
	runes := []rune(text)
	out := []rune(strings.ToLower(text))
	for i, r := range runes {
		if r == 'Σ' && i > 0 && unicode.IsLetter(runes[i-1]) && (i+1 == len(runes) || !unicode.IsLetter(runes[i+1])) {
			out[i] = 'ς'
		}
	}
	return string(out)
}

func main() {
	base := "Crème brûlée, naïve café; Straße ΟΔΥΣΣΕΥΣ 😀 smörgåsbord, jalapeño"
	rounds := 300 * scale()
	checksum := 0
	last := ""
	for round := 0; round < rounds; round++ {
		text := fmt.Sprintf("%d: %s, %s", round, base, base)
		parts := strings.Split(text, ", ")
		for i, part := range parts {
			parts[i] = upper(strings.TrimSpace(part))
		}
		swapped := lower(strings.ReplaceAll(strings.Join(parts, " | "), "É", "e"))
		if at := strings.Index(swapped, "smörgåsbord"); at >= 0 {
			checksum += utf8.RuneCountInString(swapped[:at])
		} else {
			checksum--
		}
		for _, c := range swapped {
			checksum += int(c) % 7
		}
		last = swapped
	}
	fmt.Printf("string-library %d: %d\n", rounds, checksum)
	fmt.Println(last)
}
