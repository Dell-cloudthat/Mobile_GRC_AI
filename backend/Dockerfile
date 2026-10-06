# SecurityOS API — production image.
# Build from the REPO ROOT (the API reads compliance/controls/catalog.json):
#   docker build -f backend/Dockerfile -t securityos-api .
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY compliance/ compliance/
COPY backend/ backend/

# Run as an unprivileged user.
RUN useradd --system --uid 10001 --home-dir /app securityos \
    && chmod +x backend/docker-entrypoint.sh \
    && chown -R securityos /app
USER 10001

ENV ENV=prod PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)"

ENTRYPOINT ["backend/docker-entrypoint.sh"]
