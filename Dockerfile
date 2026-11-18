ARG GO_VERSION=1.27.4
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 AS go
ARG GO_VERSION
ARG GO_SHA256=7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840
ADD --checksum=sha256:${GO_SHA256} https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz /go.tar.gz
RUN tar -C /usr/local -xzf /go.tar.gz

FROM node:22-trixie-slim@sha256:68c76cfad89921b927eae28ba21407475e29d0ce450afcdbe70c1532db042b64

ARG PI_VERSION=1.3.0
ARG MYPY_VERSION=2.3.1
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates coreutils libgc1 libssl3t64 libz1 python3 python3-venv ripgrep \
    && npm install --global @earendil-works/pi-coding-agent@${PI_VERSION} \
    && npm cache clean --force \
    && python3 -m venv /opt/typecheck \
    && /opt/typecheck/bin/pip install --no-cache-dir \
        mypy==${MYPY_VERSION} \
        mypy_extensions==1.1.0 \
        typing_extensions==4.16.0 \
        pathspec==1.1.1 \
        librt==0.16.0 \
        ast_serialize==0.13.0 \
    && ln -s /opt/typecheck/bin/mypy /usr/local/bin/mypy \
    && rm -rf /var/lib/apt/lists/* /root/.cache \
    && usermod --login agent --home /home/agent --move-home node

ARG GO_VERSION
COPY --from=go /usr/local/go /usr/local/go
# The root file system is read-only at run time, so the build cache is warmed here for the whole public standard
# library (`go list std` without internal, vendor and cmd): Go reads a read-only cache but cannot add to it, and a
# package it has never indexed is then "not in std". The module index is off (GODEBUG=goindex=0): Go indexes a
# folder of the workspace whose files are older than two seconds and fails when it cannot write that index.
ENV GOCACHE=/opt/go-cache GOPATH=/tmp/go GOFLAGS=-mod=mod GOPROXY=off GOTOOLCHAIN=local CGO_ENABLED=0 GODEBUG=goindex=0
RUN ln -s /usr/local/go/bin/go /usr/local/go/bin/gofmt /usr/local/bin/ \
    && mkdir /opt/go-warm && cd /opt/go-warm && printf 'module warm\n\ngo %s\n' "${GO_VERSION%.*}" > go.mod \
    && { printf 'package main\n\nimport (\n'; \
         go list std | grep -vE '(^|/)(internal|vendor)(/|$)|^cmd/|^(runtime/cgo|runtime/race|plugin)$' \
           | sed 's/.*/\t_ "&"/'; \
         printf ')\n\nfunc main() {}\n'; } > main.go \
    && go vet . && go build -o /dev/null . \
    && chmod -R a+rX /opt/go-cache && rm -rf /opt/go-warm /tmp/go

# The one module outside the standard library, for the ecosystem tasks: modernc.org/sqlite (pure Go), pinned by
# ecosystem/go.sum. The build downloads it into a read-only module cache and warms the build cache for it; at run time
# GOPROXY stays off.
ENV GOMODCACHE=/opt/go-mod
COPY ecosystem/go.mod ecosystem/go.sum /opt/go-warm/
RUN umask 022 && cd /opt/go-warm \
    && printf 'package main\n\nimport (\n\t"database/sql"\n\n\t_ "modernc.org/sqlite"\n)\n\nfunc main() { sql.Drivers() }\n' > main.go \
    && GOPROXY=https://proxy.golang.org GOFLAGS=-mod=readonly go build -o /dev/null . && go vet . \
    && rm -rf /opt/go-warm /tmp/go /opt/go-mod/cache/download/*/*/@v/*.zip /opt/go-mod/cache/download/*/*/*/@v/*.zip

ENV HOME=/home/agent
ENV PATH=/workspace/bin:/usr/local/bin:/usr/bin:/bin
USER agent
WORKDIR /workspace
