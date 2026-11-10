# syntax=docker/dockerfile:1
# Frontend image. Dependencies are installed inside the image (Linux), never from the
# synced node_modules folder, so it builds the same on Windows and macOS.

FROM node:24-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Live-reload dev server, used by docker-compose.dev.yml (the source is mounted over /app).
FROM deps AS dev
ENV VITE_POLL=1
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM deps AS build
COPY . .
RUN npm run build

# Default target: the built app served by nginx, which also proxies the API.
FROM nginx:1.27-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
