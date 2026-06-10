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

# ─── deps ─────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# ─── build ────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ─── runtime ──────────────────────────────────────────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

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
