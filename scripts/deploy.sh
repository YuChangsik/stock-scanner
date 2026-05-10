#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# 댕댕투자 배포 스크립트
# GitHub에서 최신 코드를 받아 서버를 재시작합니다.
# 사용법: ./scripts/deploy.sh
# ──────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_LABEL="com.daengdaeng.stock-scanner"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

echo "▶ [1/4] GitHub에서 최신 코드 받는 중..."
cd "$PROJECT_DIR"
git pull --ff-only

echo "▶ [2/4] 패키지 업데이트 중..."
"$PROJECT_DIR/.venv/bin/pip" install -e . -q

echo "▶ [3/4] 서버 재시작 중..."
if [ -f "$PLIST_PATH" ]; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  sleep 1
  launchctl load -w "$PLIST_PATH"
  echo "✅ LaunchAgent 재시작 완료"
else
  echo "⚠️  LaunchAgent plist가 없습니다. scripts/install-service.sh 를 먼저 실행하세요."
fi

echo "▶ [4/4] 서버 상태 확인 중..."
sleep 3
curl -sf http://localhost:8000/health 2>/dev/null && echo "✅ 서버 정상 응답" || echo "⚠️  서버 응답 없음 (시작 중일 수 있음)"
