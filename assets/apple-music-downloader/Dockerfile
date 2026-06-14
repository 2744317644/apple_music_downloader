ARG REGISTRY_MIRROR=docker.m.daocloud.io
ARG GOVERSION=1.23

FROM --platform=$BUILDPLATFORM ${REGISTRY_MIRROR}/library/golang:${GOVERSION}-alpine AS builder
ARG TARGETOS
ARG TARGETARCH
WORKDIR /app
RUN --mount=type=cache,target=/go/pkg/mod/ \
    --mount=type=bind,target=. \
    CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -o /bin/apple-music-dl main.go

FROM ${REGISTRY_MIRROR}/library/ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN sed -i "s@http://.*archive.ubuntu.com@http://mirrors.tuna.tsinghua.edu.cn@g" /etc/apt/sources.list.d/ubuntu.sources && \
    sed -i "s@http://.*security.ubuntu.com@http://mirrors.tuna.tsinghua.edu.cn@g" /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates gpac ffmpeg && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /bin/apple-music-dl /usr/local/bin/apple-music-dl
WORKDIR /app
COPY config.yaml.example config.yaml
RUN echo 'alac-save-folder: "/downloads/ALAC"' >> config.yaml \
    && echo 'atmos-save-folder: "/downloads/Atmos"' >> config.yaml \
    && echo 'aac-save-folder: "/downloads/AAC"' >> config.yaml
ENTRYPOINT ["/usr/local/bin/apple-music-dl"]
