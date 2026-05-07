# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# CLI tools commonly needed when poking around in a remote shell.
# Keep this list reasonable so the image stays small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        wget \
        git \
        nano \
        vim \
        less \
        procps \
        htop \
        net-tools \
        iputils-ping \
        dnsutils \
        openssh-client \
        unzip \
        zip \
        tree \
        jq \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENV SHELL=/bin/bash \
    TERM=xterm-256color \
    PORT=8080

EXPOSE 8080

# tini reaps the shell child processes spawned by PTY sessions
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "server.py"]
