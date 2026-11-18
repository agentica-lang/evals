package job

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"strings"
)

type Job struct {
	Concurrency      int
	RequestTimeoutMs int
	DeadlineMs       int
	HedgeMs          int
	Retries          int
	BackoffMs        int
	URLs             []string
}

var ErrBadJob = errors.New("bad job file")

var least = map[string]int{"concurrency": 1, "request_timeout_ms": 1, "deadline_ms": 1, "hedge_ms": 0, "retries": 0,
	"backoff_ms": 1}

func Load(path string) (Job, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Job{}, ErrBadJob
	}
	var raw map[string]json.RawMessage
	if json.Unmarshal(data, &raw) != nil {
		return Job{}, ErrBadJob
	}
	values := map[string]int{}
	for name, min := range least {
		value, ok := integer(raw[name])
		if !ok || value < min {
			return Job{}, ErrBadJob
		}
		values[name] = value
	}
	var urls []string
	if raw["urls"] == nil || json.Unmarshal(raw["urls"], &urls) != nil || urls == nil && string(raw["urls"]) != "[]" {
		return Job{}, ErrBadJob
	}
	for _, url := range urls {
		if !strings.HasPrefix(url, "http://") {
			return Job{}, ErrBadJob
		}
	}
	return Job{values["concurrency"], values["request_timeout_ms"], values["deadline_ms"], values["hedge_ms"],
		values["retries"], values["backoff_ms"], urls}, nil
}

func integer(raw json.RawMessage) (int, bool) {
	text := bytes.TrimSpace(raw)
	if len(text) == 0 || bytes.ContainsAny(text, ".eE") {
		return 0, false
	}
	var value int
	if json.Unmarshal(text, &value) != nil {
		return 0, false
	}
	return value, true
}
