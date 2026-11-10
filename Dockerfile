# Ripple API 이미지. 파이썬 의존성은 uv.lock 그대로 설치한다.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY ripple ./ripple
COPY rules ./rules
COPY params ./params
COPY generator ./generator
COPY scripts/generate.py ./scripts/generate.py
COPY deploy/api-entrypoint.py ./deploy/api-entrypoint.py
RUN uv sync --locked --no-dev
# 시연용 합성 지도(시드 20261020)를 이미지 안에 만든다. 실제 데이터는 RIPPLE_SNAPSHOT_PATH로 따로 넣는다
RUN uv run --no-sync python scripts/generate.py

ENV PATH="/app/.venv/bin:$PATH"
# 시연 세계는 실시간: 합성 기본 지도를 한국 시간 오늘로 만들고 날이 바뀌면 다시 만든다(docs/operations.md(서비스) 6절)
ENV RIPPLE_SYNTHETIC_CLOCK=live
# 배포한 커밋(상태 확인의 build). compose·CI는 빌드 인자로, Railway는 실행 때 RAILWAY_GIT_COMMIT_SHA로 준다
ARG RIPPLE_BUILD=""
ENV RIPPLE_BUILD=${RIPPLE_BUILD}
# 가져온 지도·계정·세션(RIPPLE_DATA_DIR 기본 /app/.data)은 볼륨에 둔다. 시작 스크립트가 root로 볼륨 소유권을 맞춘 뒤
# ripple 사용자로 낮춰 서버를 실행한다(deploy/api-entrypoint.py)
RUN useradd --create-home --uid 10001 ripple && mkdir -p /app/.data && chown ripple:ripple /app/.data

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8000'))"
ENTRYPOINT ["python", "/app/deploy/api-entrypoint.py"]
# 포트는 PORT(Railway가 상태 확인에도 씀, 기본 8000), 주소는 RIPPLE_API_HOST(기본 0.0.0.0, 옛 IPv6 전용 사설망이면 ::)
CMD ["sh", "-c", "exec uvicorn ripple.api.app:create_app --factory --host \"${RIPPLE_API_HOST:-0.0.0.0}\" --port \"${PORT:-8000}\""]
