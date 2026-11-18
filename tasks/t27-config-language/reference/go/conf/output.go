package conf

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

func quote(text string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, c := range text {
		switch {
		case c == '"':
			b.WriteString(`\"`)
		case c == '\\':
			b.WriteString(`\\`)
		case c == '\n':
			b.WriteString(`\n`)
		case c == '\t':
			b.WriteString(`\t`)
		case c < 0x20:
			fmt.Fprintf(&b, `\u%04x`, c)
		default:
			b.WriteRune(c)
		}
	}
	b.WriteByte('"')
	return b.String()
}

// JSON writes a value as compact JSON, the keys of a record sorted by their bytes.
func JSON(v Value) string {
	switch v := v.(type) {
	case int64:
		return strconv.FormatInt(v, 10)
	case string:
		return quote(v)
	case bool:
		return strconv.FormatBool(v)
	case []Value:
		items := make([]string, len(v))
		for i, item := range v {
			items[i] = JSON(item)
		}
		return "[" + strings.Join(items, ",") + "]"
	}
	rec := v.(*Rec)
	keys := append([]string{}, rec.Keys...)
	sort.Strings(keys)
	entries := make([]string, len(keys))
	for i, k := range keys {
		entries[i] = quote(k) + ":" + JSON(rec.Entries[k])
	}
	return "{" + strings.Join(entries, ",") + "}"
}
