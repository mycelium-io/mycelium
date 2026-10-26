# syntax=docker/dockerfile:1.7
#
# Mycelium frontend — Next.js production build.
#
# The browser never talks to the backend directly. All `/api/*` requests are
# proxied by the Next.js server (see next.config.ts `rewrites()`) so the
# image is portable across deployments — no build-time URL baking.
#
# At runtime, the Next.js server reaches the backend via
# `MYCELIUM_INTERNAL_API_URL` (defaults to `http://mycelium-backend:8000`,
# the compose service name). For host-mode deployments, override at
# container start:
#
#   docker run -e MYCELIUM_INTERNAL_API_URL=http://host.docker.internal:8000 ...

# Every stage takes Node from this one image, pinned by digest, so the
# binary the runner copies is the one the build stages ran. Bump the two
# together: ALPINE_IMAGE is the Alpine release this node image is built on
# (`cat /etc/alpine-release` in it), so its libraries match the binary.
ARG NODE_IMAGE=node:22.23.4-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914
ARG ALPINE_IMAGE=alpine:3.24.3@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a

# ─── node ─────────────────────────────────────────────────────────────────────
FROM ${NODE_IMAGE} AS node

# ─── deps ─────────────────────────────────────────────────────────────────────
FROM ${NODE_IMAGE} AS deps
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# ─── build ────────────────────────────────────────────────────────────────────
FROM ${NODE_IMAGE} AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ─── runtime ──────────────────────────────────────────────────────────────────
# The runner ships no npm, yarn or corepack: it only runs `node server.js`.
# It starts from plain Alpine and copies in the node binary alone, because
# the node image's own layers carry the npm it bundles, and deleting that
# in a later layer only hides it (#1331). node needs libstdc++ and libgcc
# on Alpine.
FROM ${ALPINE_IMAGE} AS runner
WORKDIR /app

RUN apk add --no-cache libstdc++ libgcc
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN node --version

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
# Default proxy target — matches the compose service name. Override at
# container start for non-compose deployments.
ENV MYCELIUM_INTERNAL_API_URL=http://mycelium-backend:8000

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

# next.config.ts has output: "standalone", so .next/standalone is a self-
# contained server bundle (small subset of node_modules + server.js).
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
