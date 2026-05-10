#!/bin/bash
# 서버 최초 1회 실행 스크립트 (Ubuntu 22.04 기준)
set -e

echo "=== 1. 패키지 업데이트 ==="
apt-get update && apt-get upgrade -y

echo "=== 2. Docker 설치 ==="
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

echo "=== 3. Git 설치 ==="
apt-get install -y git

echo "=== 4. 프로젝트 클론 ==="
mkdir -p /opt/stock-scanner
# ↓ 본인 GitHub repo URL로 변경
git clone https://github.com/YOUR_USERNAME/stock-scanner /opt/stock-scanner
cd /opt/stock-scanner

echo "=== 5. .env 파일 생성 ==="
cp .env.example .env
# JWT_SECRET_KEY 자동 생성
SECRET=$(openssl rand -hex 32)
DB_PASS=$(openssl rand -hex 16)
sed -i "s/CHANGE_THIS_TO_LONG_RANDOM_STRING/$SECRET/" .env
sed -i "s/CHANGE_DB_PASSWORD/$DB_PASS/g" .env

echo ""
echo "✅ 서버 세팅 완료!"
echo "👉 .env 파일 확인: cat /opt/stock-scanner/.env"
echo "👉 서버 시작: cd /opt/stock-scanner && docker compose -f docker-compose.prod.yml up -d"
