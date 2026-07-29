#!/bin/sh
set -eu

API_URL="${PAPERLENS_API_URL:-${PAPERLENS_API_BASE:-http://127.0.0.1:8000}}"
escaped="$(printf '%s' "$API_URL" | sed 's/[&|]/\\&/g')"
sed "s|\${PAPERLENS_API_URL}|$escaped|g" \
  /usr/share/nginx/html/config.template.js \
  > /usr/share/nginx/html/config.js

exec /docker-entrypoint.sh nginx -g "daemon off;"
