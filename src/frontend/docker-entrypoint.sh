#!/bin/sh
set -eu

API_URL="${PAPERLENS_API_URL:-${PAPERLENS_API_BASE:-http://127.0.0.1:8000}}"
AUTH_URL="${SUPABASE_AUTH_URL:-}"
ANON_KEY="${SUPABASE_ANON_KEY:-}"
escaped_api="$(printf '%s' "$API_URL" | sed 's/[&|]/\\&/g')"
escaped_auth="$(printf '%s' "$AUTH_URL" | sed 's/[&|]/\\&/g')"
escaped_anon="$(printf '%s' "$ANON_KEY" | sed 's/[&|]/\\&/g')"
sed \
  -e "s|\${PAPERLENS_API_URL}|$escaped_api|g" \
  -e "s|\${SUPABASE_AUTH_URL}|$escaped_auth|g" \
  -e "s|\${SUPABASE_ANON_KEY}|$escaped_anon|g" \
  /usr/share/nginx/html/config.template.js \
  > /usr/share/nginx/html/config.js

exec /docker-entrypoint.sh nginx -g "daemon off;"
