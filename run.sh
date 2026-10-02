#!/usr/bin/env bash
# Starts, resets and checks the support desk's services, in dependency order.
# Stage 2: Postgres, then MCP Toolbox. Later stages add Judge, Masker and Phoenix.
set -euo pipefail
cd "$(dirname "$0")"

TOOLBOX_VERSION=1.13.1
TOOLBOX_PORT=5001   # 5000 is taken by macOS AirPlay Receiver
TOOLBOX_MATCH="--config mcp_toolbox/tools.yaml"

[ -f .env ] || { echo "Missing .env" >&2; exit 1; }
set -a; source .env; set +a
mkdir -p logs

require_docker() {
  docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker Desktop first." >&2; exit 1; }
}

db_status() {
  local health
  health=$(docker inspect -f '{{.State.Health.Status}}' support-db 2>/dev/null || echo "not running")
  echo "postgres  :5434  $health"
}

toolbox_up() { curl -sf "http://127.0.0.1:$TOOLBOX_PORT/" >/dev/null 2>&1; }

toolbox_status() {
  if toolbox_up; then echo "toolbox   :$TOOLBOX_PORT  ok"; else echo "toolbox   :$TOOLBOX_PORT  down"; fi
}

start_toolbox() {
  if toolbox_up; then toolbox_status; return; fi
  nohup npx -y "@toolbox-sdk/server@$TOOLBOX_VERSION" $TOOLBOX_MATCH \
    --enable-api --address 127.0.0.1 --port "$TOOLBOX_PORT" > logs/toolbox.log 2>&1 &
  for _ in $(seq 1 60); do
    toolbox_up && { toolbox_status; return; }
    sleep 1
  done
  echo "toolbox failed to start; last log lines:" >&2
  tail -20 logs/toolbox.log >&2
  exit 1
}

stop_toolbox() { pkill -f -- "$TOOLBOX_MATCH" 2>/dev/null || true; }

case "${1:-}" in
  start)
    require_docker
    docker compose up -d --wait db
    db_status
    start_toolbox
    ;;
  reset)
    require_docker
    stop_toolbox
    docker compose down -v
    docker compose up -d --wait db
    db_status
    start_toolbox
    ;;
  stop)
    stop_toolbox
    require_docker
    docker compose stop
    ;;
  status)
    require_docker
    db_status
    toolbox_status
    ;;
  *)
    echo "usage: ./run.sh {start|reset|stop|status}" >&2
    exit 1
    ;;
esac
