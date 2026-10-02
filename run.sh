#!/usr/bin/env bash
# Starts, resets and checks the support desk's services, in dependency order.
# Stage 5: Postgres, MCP Toolbox, Phoenix. Later stages add Judge and Masker before Phoenix.
set -euo pipefail
cd "$(dirname "$0")"

TOOLBOX_VERSION=1.13.1
TOOLBOX_PORT=5001   # 5000 is taken by macOS AirPlay Receiver
TOOLBOX_MATCH="--config mcp_toolbox/tools.yaml"
PHOENIX_PORT=6006
# Phoenix keeps traces in a SQLite file here, so they survive restarts (O-1, SPEC §11 R-10).
PHOENIX_DIR="$PWD/phoenix_data"

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

phoenix_up() { curl -sf "http://127.0.0.1:$PHOENIX_PORT/healthz" >/dev/null 2>&1; }

phoenix_status() {
  if phoenix_up; then echo "phoenix   :$PHOENIX_PORT  ok"; else echo "phoenix   :$PHOENIX_PORT  down"; fi
}

# Its own long-lived process; the CLI and web app never start or stop it (O-1).
start_phoenix() {
  if phoenix_up; then phoenix_status; return; fi
  mkdir -p "$PHOENIX_DIR"
  PHOENIX_WORKING_DIR="$PHOENIX_DIR" PHOENIX_HOST=127.0.0.1 PHOENIX_PORT="$PHOENIX_PORT" \
    nohup .venv/bin/phoenix serve > logs/phoenix.log 2>&1 &
  for _ in $(seq 1 60); do
    phoenix_up && { phoenix_status; return; }
    sleep 1
  done
  echo "phoenix failed to start; last log lines:" >&2
  tail -20 logs/phoenix.log >&2
  exit 1
}

stop_phoenix() { pkill -f -- "phoenix serve" 2>/dev/null || true; }

case "${1:-}" in
  start)
    require_docker
    docker compose up -d --wait db
    db_status
    start_toolbox
    start_phoenix
    ;;
  reset)  # resets the database only; traces are kept
    require_docker
    stop_toolbox
    docker compose down -v
    docker compose up -d --wait db
    db_status
    start_toolbox
    start_phoenix
    ;;
  stop)
    stop_phoenix
    stop_toolbox
    require_docker
    docker compose stop
    ;;
  status)
    require_docker
    db_status
    toolbox_status
    phoenix_status
    ;;
  *)
    echo "usage: ./run.sh {start|reset|stop|status}" >&2
    exit 1
    ;;
esac
