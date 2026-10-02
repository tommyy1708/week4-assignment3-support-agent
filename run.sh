#!/usr/bin/env bash
# Starts, resets and checks the support desk's services.
# Stage 1: Postgres only. Later stages add Toolbox, Judge, Masker and Phoenix, in that order.
set -euo pipefail
cd "$(dirname "$0")"

require_docker() {
  docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker Desktop first." >&2; exit 1; }
}

db_status() {
  local health
  health=$(docker inspect -f '{{.State.Health.Status}}' support-db 2>/dev/null || echo "not running")
  echo "postgres  :5434  $health"
}

case "${1:-}" in
  start)
    require_docker
    docker compose up -d --wait db
    db_status
    ;;
  reset)
    require_docker
    docker compose down -v
    docker compose up -d --wait db
    db_status
    ;;
  stop)
    require_docker
    docker compose stop
    ;;
  status)
    require_docker
    db_status
    ;;
  *)
    echo "usage: ./run.sh {start|reset|stop|status}" >&2
    exit 1
    ;;
esac
