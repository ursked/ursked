FROM node:20.18.1-alpine AS deps

WORKDIR /app
COPY package.json package-lock.json* ./
# `npm ci` installs exactly what the lockfile pins; `npm install` may drift.
RUN npm ci


# Development stage: full deps + next dev with hot reload. Source is bind-
# mounted over /app at runtime (see docker-compose.lan.yml); node_modules stays
# on an anonymous volume so these baked deps are used.
FROM node:20.18.1-alpine AS dev

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=development \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN apk add --no-cache curl
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]


FROM node:20.18.1-alpine AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG API_INTERNAL_URL=http://backend:8000
ENV API_INTERNAL_URL=${API_INTERNAL_URL}
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build


FROM node:20.18.1-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN apk add --no-cache curl \
    && addgroup -g 10001 -S nodejs \
    && adduser -u 10001 -S nextjs -G nodejs

# `output: standalone` produces a minimal server plus only the modules it uses.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
