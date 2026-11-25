# syntax=docker/dockerfile:1

# ---------- Stage 1: build the static bundle ----------
FROM node:24-slim AS build

WORKDIR /app

# Install dependencies from the lockfile first for layer caching.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
# Empty base URL => the SPA calls same-origin /api/..., which Nginx proxies.
ENV VITE_API_BASE_URL=""
RUN npm run build

# ---------- Stage 2: serve with Nginx ----------
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD wget -q --spider http://127.0.0.1/healthz || exit 1
