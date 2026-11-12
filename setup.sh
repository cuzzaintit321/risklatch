#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  umask 077
  printf 'SECRET_KEY=%s\nADMIN_PASSWORD=%s\nSECURE_COOKIE=0\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 16)" > .env
fi
docker compose up -d --build
printf 'Local URL: http://localhost:8125\n'
grep '^ADMIN_PASSWORD=' .env
