#!/usr/bin/env bash
# Start the whole stack: Docker infrastructure + native backend + native frontend.
#
# Why a script: two things about this project are easy to get wrong by hand.
#   - uvicorn must be launched from the REPO ROOT, because app/config.py loads
#     ".env" relative to the working directory. Launched from backend/ it
#     silently falls back to Docker hostnames and cannot reach Postgres.
#   - PYTHONPATH must include backend/, because the app imports `app.*`.
#
# Usage:  ./scripts/start-dev.sh           # start everything
#         ./scripts/start-dev.sh --seed    # start, then (re)seed demo data
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- resolve the venv interpreter (Windows layout differs from POSIX) --------
if [ -x "$ROOT/backend/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/backend/.venv/Scripts/python.exe"
elif [ -x "$ROOT/backend/.venv/bin/python" ]; then
  PY="$ROOT/backend/.venv/bin/python"
else
  echo "No virtualenv found at backend/.venv"
  echo "Create it with Python 3.12 (3.13/3.14 have no wheels for the pinned"
  echo "pydantic 2.5.3 / fastapi 0.109):"
  echo "  python3.12 -m venv backend/.venv"
  echo "  backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt"
  exit 1
fi

echo "==> Starting infrastructure (Postgres, mock ERP/compliance, n8n)"
docker compose up -d

echo "==> Waiting for Postgres"
for _ in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U vendoruser -d vendordb >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose exec -T postgres pg_isready -U vendoruser -d vendordb

# --- backend ----------------------------------------------------------------
mkdir -p "$ROOT/logs" "$ROOT/documents/uploads"

if pgrep -f "uvicorn app.main:app" >/dev/null 2>&1; then
  echo "==> Backend already running on :8000"
else
  echo "==> Starting backend on :8000"
  # --reload-dir: with plain --reload uvicorn watches the whole repo, so saving
  # scripts/, n8n/ or docs/ restarts the backend. Narrow it to the code that
  # actually runs -- and keep it off backend/.venv, which is enormous.
  PYTHONPATH="$ROOT/backend" nohup "$PY" -m uvicorn app.main:app --reload \
    --reload-dir "$ROOT/backend/app" \
    --port 8000 --host 127.0.0.1 >"$ROOT/logs/backend.log" 2>&1 &
fi

# --- frontend ---------------------------------------------------------------
if pgrep -f "vite" >/dev/null 2>&1; then
  echo "==> Frontend already running on :5173"
else
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    echo "==> Installing frontend dependencies (first run: a few minutes)"
    (cd "$ROOT/frontend" && npm install)
  fi
  echo "==> Starting frontend on :5173"
  (cd "$ROOT/frontend" && nohup npm run dev >"$ROOT/logs/frontend.log" 2>&1 &)
fi

# --- wait for both to answer ------------------------------------------------
for _ in $(seq 1 60); do
  if curl -s --noproxy '*' -m 2 http://127.0.0.1:8000/health >/dev/null 2>&1 \
     && curl -s --noproxy '*' -m 2 -o /dev/null http://localhost:5173/ 2>/dev/null; then
    break
  fi
  sleep 1
done

# --- optional seed ----------------------------------------------------------
if [ "${1:-}" = "--seed" ]; then
  echo "==> Seeding demo data"
  docker compose exec -T postgres psql -U vendoruser -d vendordb -c \
    "TRUNCATE TABLE approvals, audit_events, documents, extracted_fields, exceptions, onboarding_cases, requirements, risk_assessments, risk_signals, users, vendors RESTART IDENTITY CASCADE;" \
    >/dev/null
  PYTHONPATH="$ROOT/backend" \
    DATABASE_URL="postgresql://vendoruser:vendorpass@localhost:5432/vendordb" \
    LLM_PROVIDER=mock \
    DOCUMENT_STORAGE_PATH="$ROOT/documents/uploads" \
    "$PY" "$ROOT/backend/scripts/seed_demo_data.py"
fi

cat <<EOF

Ready:
  Frontend   http://localhost:5173
  API docs   http://localhost:8000/docs
  n8n        http://localhost:5678   (admin / admin123)

Logs: logs/backend.log, logs/frontend.log
EOF
