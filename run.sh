#!/usr/bin/env bash
# Starts, resets and checks the support desk's services, in dependency order.
# Order: Postgres, MCP Toolbox, Security Judge (A2A), Data Masker (A2A), Phoenix.
set -euo pipefail
cd "$(dirname "$0")"

TOOLBOX_VERSION=1.13.1
TOOLBOX_PORT=5001   # 5000 is taken by macOS AirPlay Receiver
TOOLBOX_MATCH="--config mcp_toolbox/tools.yaml"
JUDGE_PORT=10002
MASKER_PORT=10003
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

judge_up() { curl -sf "http://127.0.0.1:$JUDGE_PORT/.well-known/agent-card.json" >/dev/null 2>&1; }

judge_status() {
  if judge_up; then echo "judge     :$JUDGE_PORT ok"; else echo "judge     :$JUDGE_PORT down"; fi
}

# The Security Judge is its own A2A service, owned apart from the product (J-1).
start_judge() {
  if judge_up; then judge_status; return; fi
  JUDGE_PORT="$JUDGE_PORT" nohup .venv/bin/python -m guards.judge > logs/judge.log 2>&1 &
  for _ in $(seq 1 60); do
    judge_up && { judge_status; return; }
    sleep 1
  done
  echo "judge failed to start; last log lines:" >&2
  tail -20 logs/judge.log >&2
  exit 1
}

stop_judge() {
  pkill -f -- "-m guards.judge" 2>/dev/null || true
  for _ in $(seq 1 20); do judge_up || return 0; sleep 0.5; done
}

masker_up() { curl -sf "http://127.0.0.1:$MASKER_PORT/.well-known/agent-card.json" >/dev/null 2>&1; }

masker_status() {
  if masker_up; then echo "masker    :$MASKER_PORT ok"; else echo "masker    :$MASKER_PORT down"; fi
}

# The Data Masker is the second A2A service the security team owns (K-1).
start_masker() {
  if masker_up; then masker_status; return; fi
  MASKER_PORT="$MASKER_PORT" nohup .venv/bin/python -m guards.masker > logs/masker.log 2>&1 &
  for _ in $(seq 1 60); do
    masker_up && { masker_status; return; }
    sleep 1
  done
  echo "masker failed to start; last log lines:" >&2
  tail -20 logs/masker.log >&2
  exit 1
}

stop_masker() { pkill -f -- "-m guards.masker" 2>/dev/null || true; }

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
    start_judge
    start_masker
    start_phoenix
    ;;
  reset)  # resets the database only; traces are kept
    require_docker
    stop_toolbox
    docker compose down -v
    docker compose up -d --wait db
    db_status
    start_toolbox
    start_judge
    start_masker
    start_phoenix
    ;;
  stop)
    stop_phoenix
    stop_masker
    stop_judge
    stop_toolbox
    require_docker
    docker compose stop
    ;;
  status)
    require_docker
    db_status
    toolbox_status
    judge_status
    masker_status
    phoenix_status
    ;;
  web)  # start every service, then the web UI in the foreground (Ctrl+C stops only the web app)
    require_docker
    docker compose up -d --wait db
    db_status
    start_toolbox
    start_judge
    start_masker
    start_phoenix
    echo "web UI    http://127.0.0.1:8010"
    exec .venv/bin/python -m support.web
    ;;
  stop-judge)  # for the fail-loud check: send a message while the Judge is down
    stop_judge
    judge_status
    ;;
  *)
    echo "usage: ./run.sh {start|reset|stop|status|web|stop-judge}" >&2
    exit 1
    ;;
esac
