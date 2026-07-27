# Gov-panel production image. Same shape as super-panel — see comments there.
# Public booking + verify routes are part of this build (no separate image).

ARG VITE_API_BASE_URL=https://kiosk-api.example.uz

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine AS runtime
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
# 127.0.0.1, not localhost: nginx.conf has `listen 80` (IPv4 only), while
# alpine resolves `localhost` to ::1 first — so the probe got "connection
# refused" and the container sat permanently unhealthy even though it served
# every request fine. A healthcheck that always fails is worse than none: it
# teaches everyone to ignore the word "unhealthy".
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
