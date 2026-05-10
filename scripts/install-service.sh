#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# 댕댕투자 macOS LaunchAgent 설치 스크립트
# 맥북 로그인 시 서버가 자동으로 시작됩니다.
# 사용법: ./scripts/install-service.sh
# ──────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_LABEL="com.daengdaeng.stock-scanner"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"
mkdir -p "$HOME/Library/LaunchAgents"

echo "▶ LaunchAgent plist 생성 중..."
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${PROJECT_DIR}/scripts/start.sh</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>

  <!-- 로그인 시 자동 시작 -->
  <key>RunAtLoad</key>
  <true/>

  <!-- 크래시 시 자동 재시작 -->
  <key>KeepAlive</key>
  <true/>

  <!-- 재시작 대기 시간(초) -->
  <key>ThrottleInterval</key>
  <integer>10</integer>

  <!-- stdout / stderr 로그 -->
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/server.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/server.err</string>

  <!-- 환경변수 -->
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/opt/postgresql@16/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key>
    <string>${HOME}</string>
    <key>LANG</key>
    <string>en_US.UTF-8</string>
  </dict>
</dict>
</plist>
EOF

echo "▶ LaunchAgent 등록 중..."
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load -w "$PLIST_PATH"

sleep 3

echo ""
echo "──────────────────────────────────────────────"
echo "✅ 댕댕투자 서버가 백그라운드에서 시작되었습니다!"
echo ""
echo "  주소:     http://localhost:8000"
echo "  로그:     tail -f ${LOG_DIR}/server.log"
echo "  에러로그: tail -f ${LOG_DIR}/server.err"
echo ""
echo "  중지:  launchctl unload $PLIST_PATH"
echo "  시작:  launchctl load -w $PLIST_PATH"
echo "  배포:  ./scripts/deploy.sh"
echo "──────────────────────────────────────────────"
