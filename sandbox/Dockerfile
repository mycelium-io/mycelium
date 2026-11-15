# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# The whole product from one worktree, in one container: `mycelium desktop
# serve` starts herdr, a SLIM node, the hub, the UI and the runner from this
# checkout's code, and a real agent CLI can be started in a herdr pane inside
# it. Everything that is one per machine (ports, ~/.mycelium, herdr's session,
# the runner) is the container's own. Built and run by `sandbox/sandbox.sh`,
# which passes the versions the desktop app ships (stage-sidecars.sh).

FROM python:3.12-slim-bookworm

ARG TARGETARCH
ARG HERDR_TAG
ARG SLIMCTL_TAG
ARG NODE_VERSION
ARG PI_VERSION
ARG EMBEDDING_MODEL

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git socat procps tini xz-utils less \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# The programs the desktop app carries, at the same versions, for Linux.
RUN set -eux; \
    case "$TARGETARCH" in \
      arm64) herdr=herdr-linux-aarch64; slim=slimctl-linux-arm64-gnu.tar.gz; node=linux-arm64 ;; \
      amd64) herdr=herdr-linux-x86_64; slim=slimctl-linux-amd64-gnu.tar.gz; node=linux-x64 ;; \
      *) echo "no build for $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    gh=https://github.com; \
    curl -fsSL "$gh/herdrdev/herdr/releases/download/$HERDR_TAG/$herdr" -o /usr/local/bin/herdr; \
    chmod +x /usr/local/bin/herdr; \
    curl -fsSL "$gh/agntcy/slim/releases/download/$SLIMCTL_TAG/$slim" | tar -xz -C /tmp; \
    install -m 0755 "$(find /tmp -type f -name slimctl | head -n 1)" /usr/local/bin/slimctl; \
    curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-$node.tar.xz" \
      | tar -xJ -C /usr/local --strip-components=1; \
    npm install -g --no-fund --no-audit pnpm \
      "@earendil-works/pi-coding-agent@$PI_VERSION" @anthropic-ai/claude-code; \
    rm -rf /tmp/* /root/.npm

# Agent CLIs won't skip their prompts as root, and nothing here needs it.
RUN useradd --create-home --uid 1000 --shell /bin/bash sandbox \
 && mkdir -p /src /work && chown sandbox:sandbox /src /work
USER sandbox
ENV HOME=/home/sandbox \
    PATH=/home/sandbox/.local/bin:$PATH \
    UV_LINK_MODE=copy

WORKDIR /src

# Dependencies first, from the lockfiles alone, so a change to the code
# rebuilds only the layers after the source is copied in.
COPY --chown=sandbox:sandbox fastapi-backend/pyproject.toml fastapi-backend/uv.lock fastapi-backend/
RUN uv sync --project fastapi-backend --frozen --no-install-project
COPY --chown=sandbox:sandbox mycelium-frontend/package.json mycelium-frontend/pnpm-lock.yaml mycelium-frontend/
RUN cd mycelium-frontend && pnpm install --frozen-lockfile

# The hub's search model, where the desktop supervisor looks for it.
RUN uv run --project fastapi-backend --no-sync python -c \
      "from fastembed import TextEmbedding; TextEmbedding('$EMBEDDING_MODEL', cache_dir='$HOME/.mycelium/models')"

COPY --chown=sandbox:sandbox . /src

# The client is generated, not committed; then the CLI as a tool and the hub
# itself, on the dependencies already installed.
RUN SPEC_FILE=openapi.json ./scripts/gen-mycelium-client.sh \
 && uv tool install -e mycelium-cli --with mycelium-backend-client@./mycelium-client \
 && uv sync --project fastapi-backend --frozen \
 && (cd mycelium-frontend && pnpm install --frozen-lockfile --offline)

# A folder agents may start in, as a git repository like a real one, and
# Claude Code past its first-run screens (the folder's trust prompt is the
# runner's to answer, as on a real machine).
RUN git config --global user.name sandbox \
 && git config --global user.email sandbox@example.com \
 && git config --global init.defaultBranch main \
 && git -C /work init -q \
 && echo '{"hasCompletedOnboarding": true, "theme": "dark"}' > "$HOME/.claude.json"

EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--", "/src/sandbox/entrypoint.sh"]
