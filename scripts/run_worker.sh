#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run celery -A allocation_agent.worker worker \
  --loglevel=INFO \
  -Q select,apply,feedback \
  --concurrency=4 \
  -E
