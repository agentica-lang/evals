package fetch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"

	"solution/job"
)

type answer struct {
	status int
	body   []byte
	ok     bool
}

var client = &http.Client{
	Transport:     &http.Transport{DisableKeepAlives: true},
	CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
}

func get(ctx context.Context, url string, timeout time.Duration) answer {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return answer{}
	}
	response, err := client.Do(request)
	if err != nil {
		return answer{}
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return answer{}
	}
	return answer{response.StatusCode, body, true}
}

// attempt sends a request, a hedge after HedgeMs when no answer came, and takes the first response.
func attempt(ctx context.Context, url string, j job.Job) answer {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	timeout := time.Duration(j.RequestTimeoutMs) * time.Millisecond
	results := make(chan answer, 2)
	send := func() { results <- get(ctx, url, timeout) }
	go send()
	running := 1
	var hedge <-chan time.Time
	if j.HedgeMs > 0 {
		timer := time.NewTimer(time.Duration(j.HedgeMs) * time.Millisecond)
		defer timer.Stop()
		hedge = timer.C
	}
	hedged := false
	for running > 0 {
		select {
		case <-hedge:
			hedge = nil
			hedged = true
			running++
			go send()
		case result := <-results:
			running--
			if result.ok {
				return result
			}
			if !hedged {
				return answer{}
			}
		case <-ctx.Done():
			return answer{}
		}
	}
	return answer{}
}

func describe(a answer) string {
	if !a.ok {
		return "error no response"
	}
	if a.status != 200 {
		return fmt.Sprintf("error status %d", a.status)
	}
	var data map[string]json.RawMessage
	if json.Unmarshal(a.body, &data) != nil || data == nil {
		return "error body"
	}
	raw := bytes.TrimSpace(data["value"])
	var value int64
	if len(raw) == 0 || bytes.ContainsAny(raw, ".eE") || json.Unmarshal(raw, &value) != nil {
		return "error body"
	}
	return fmt.Sprintf("ok %d", value)
}

func one(ctx context.Context, url string, j job.Job) (string, bool) {
	backoff := time.Duration(j.BackoffMs) * time.Millisecond
	var last answer
	for retry := 0; retry <= j.Retries; retry++ {
		last = attempt(ctx, url, j)
		if ctx.Err() != nil {
			return "", false
		}
		if last.ok && (last.status < 500 || last.status > 599) {
			break
		}
		if retry < j.Retries {
			select {
			case <-time.After(backoff):
			case <-ctx.Done():
				return "", false
			}
			backoff *= 2
		}
	}
	return describe(last), true
}

// Run fetches every URL, at most Concurrency at a time, until the deadline.
func Run(j job.Job, began time.Time) []string {
	ctx, cancel := context.WithDeadline(context.Background(), began.Add(time.Duration(j.DeadlineMs)*time.Millisecond))
	defer cancel()
	results := make([]string, len(j.URLs))
	var lock sync.Mutex
	var group sync.WaitGroup
	slots := make(chan struct{}, j.Concurrency)
	for index := range j.URLs {
		results[index] = "error deadline"
	}
	// URLs start in list order: the next one takes the first free slot.
	for index, url := range j.URLs {
		select {
		case slots <- struct{}{}:
		case <-ctx.Done():
		}
		if ctx.Err() != nil {
			break
		}
		group.Add(1)
		go func(index int, url string) {
			defer group.Done()
			defer func() { <-slots }()
			if result, done := one(ctx, url, j); done {
				lock.Lock()
				results[index] = result
				lock.Unlock()
			}
		}(index, url)
	}
	group.Wait()
	lock.Lock()
	defer lock.Unlock()
	return append([]string(nil), results...)
}
