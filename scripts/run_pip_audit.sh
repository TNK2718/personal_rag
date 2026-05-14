#!/usr/bin/env bash
# Audit Python dependencies in uv.lock for known CVEs via pip-audit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

uv export --frozen --quiet --no-emit-project --format requirements-txt \
  --project "$ROOT" > "$TMP"
uvx pip-audit --disable-pip -r "$TMP"
