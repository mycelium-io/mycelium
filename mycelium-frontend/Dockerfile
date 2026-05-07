# syntax=docker/dockerfile:1.7
#
# Mycelium frontend — Next.js production build.
#
# The browser-side bundle has the backend URL baked in at build time
# (NEXT_PUBLIC_API_URL is replaced by Next during `next build`). For the
# default `mycelium install` path the browser runs on the host and reaches
# the backend at http://localhost:<backend_port>, so that's the bake-time
# default. Override at build time for non-default setups:
#
#   docker build --build-arg API_URL=http://my-backend.internal:8000 .
#
# This is the cheapest possible "ship the UI to users" path. A future PR
# can add runtime URL injection (server-side /api/_config endpoint that
# reads the env at request time) for users with remote backends.

# ─── deps ─────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# ─── build ────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app

ARG API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${API_URL}

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ─── runtime ──────────────────────────────────────────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

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
