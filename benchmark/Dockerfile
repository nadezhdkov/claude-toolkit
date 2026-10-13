# Clean, reproducible environment for one benchmark run: Claude Code, this
# branch's ctk and plugin, and nothing from the host user's configuration.
# Built by benchmark/run.py (context: the repository root).
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ARG CLAUDE_VERSION=2.1.296
ARG GITLEAKS_VERSION=8.30.1
ARG GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/gitleaks.tgz \
        "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    && echo "${GITLEAKS_SHA256}  /tmp/gitleaks.tgz" | sha256sum -c - \
    && tar -xzf /tmp/gitleaks.tgz -C /usr/local/bin gitleaks \
    && rm /tmp/gitleaks.tgz

RUN useradd --create-home --shell /bin/bash bench \
    && mkdir /work && chown bench:bench /work
USER bench
ENV PATH=/home/bench/.local/bin:$PATH \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_VERSION}" \
    && claude --version \
    && git config --global user.email bench@example.com \
    && git config --global user.name bench \
    && git config --global init.defaultBranch main

# This branch's ctk (stdlib only, so a launcher is enough) and plugin.
USER root
COPY src /opt/ctk/src
COPY plugin /opt/ctk/plugin
RUN printf '#!/bin/sh\nPYTHONPATH=/opt/ctk/src exec python3 -m claude_toolkit.cli "$@"\n' > /usr/local/bin/ctk \
    && chmod +x /usr/local/bin/ctk \
    && ctk --version
USER bench
WORKDIR /work
