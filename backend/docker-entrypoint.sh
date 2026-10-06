#!/bin/sh
# Apply database migrations (safe with many replicas: an advisory lock lets one
# replica migrate while the others wait), then start the API.
set -eu

if [ -n "${DATABASE_URL:-}" ]; then
  echo "Applying database migrations..."
  python -m backend.db.migrate
fi

exec uvicorn backend.securityos_main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips '*' \
  --no-server-header
