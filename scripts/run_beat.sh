#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run celery -A allocation_agent.celery_app beat --loglevel=INFO
