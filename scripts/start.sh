#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# 댕댕투자 서버 시작 스크립트
# LaunchAgent 또는 수동 실행 모두 지원
# ──────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
UVICORN="$PROJECT_DIR/.venv/bin/uvicorn"
ENV_FILE="$PROJECT_DIR/.env"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

# .env 파일 로드
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

cd "$PROJECT_DIR"

exec "$UVICORN" app.main:app \
  --host 0.0.0.0 \
  --port "${APP_PORT:-8000}" \
  --log-level "${LOG_LEVEL:-info}" \
  --access-log
