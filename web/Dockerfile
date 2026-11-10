# Ripple 화면 이미지(docs/operations.md(배포)): 화면을 빌드해 Caddy로 내보내고 /api는 API 서비스로 넘긴다(같은 출처 — CORS 없음).
# 빌드 맥락은 web/ 폴더다(Railway 화면 서비스의 루트 디렉터리 /web, compose의 build.context ./web).
FROM node:22.23.3-bookworm-slim AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# 배포한 커밋: compose·CI는 RIPPLE_BUILD, Railway는 빌드 인자로 RAILWAY_GIT_COMMIT_SHA를 준다(dist/version.json)
ARG RIPPLE_BUILD=""
ARG RAILWAY_GIT_COMMIT_SHA=""
RUN BUILD="${RIPPLE_BUILD:-${RAILWAY_GIT_COMMIT_SHA:-local}}" \
    && npm run build \
    && printf '{"build":"%s"}\n' "$BUILD" > dist/version.json

FROM caddy:2.11.4-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
# API 주소: compose는 api:8000, Railway는 ${{api.RAILWAY_PRIVATE_DOMAIN}}:8000(서비스 변수로 덮음)
ENV RIPPLE_API_UPSTREAM=api:8000
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -q -O /dev/null "http://127.0.0.1:${PORT:-8080}/healthz" || exit 1
