#!/usr/bin/env bash
set -euo pipefail

# Run Alembic migrations for CricEdge backend.
# Usage:
#   ./scripts/migrate.sh            — upgrade to head
#   ./scripts/migrate.sh downgrade  — downgrade one revision
#   ./scripts/migrate.sh generate "message"  — autogenerate new migration

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

cd "$BACKEND_DIR"

CMD="${1:-upgrade}"
EXTRA="${2:-}"

case "$CMD" in
  upgrade)
    echo "Running migrations: upgrade head"
    python3 -m alembic upgrade head
    ;;
  downgrade)
    echo "Running migrations: downgrade -1"
    python3 -m alembic downgrade -1
    ;;
  generate)
    if [ -z "$EXTRA" ]; then
      echo "Usage: $0 generate \"migration message\""
      exit 1
    fi
    echo "Generating migration: $EXTRA"
    python3 -m alembic revision --autogenerate -m "$EXTRA"
    ;;
  history)
    python3 -m alembic history --verbose
    ;;
  current)
    python3 -m alembic current
    ;;
  *)
    echo "Unknown command: $CMD"
    echo "Usage: $0 [upgrade|downgrade|generate|history|current]"
    exit 1
    ;;
esac
