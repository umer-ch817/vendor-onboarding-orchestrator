# Build stage: compile the TypeScript bundle.
#
# `npm ci` is used rather than `npm install` so the build is reproducible from
# package-lock.json. The build runs `tsc` before Vite, so a type error fails the
# image build instead of shipping a bundle with a silent contract mismatch.
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# Runtime stage: serve the static bundle.
#
# The SPA needs history-API fallback, so nginx.conf rewrites unknown paths to
# index.html. Without it, a deep link like /cases/12 returns 404 on hard reload
# while working fine via in-app navigation.
FROM nginx:1.25-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost/healthz >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
