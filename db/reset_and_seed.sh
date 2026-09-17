#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${SEED_FILE:?SEED_FILE is required}"
deadline="${RESET_TIMEOUT_SECONDS:-60}"
start=$(date +%s)

until pg_isready -h "${PGHOST}" -U "${PGUSER}" -d "${PGDATABASE}" >/dev/null 2>&1; do
  if [ "$(( $(date +%s) - start ))" -ge "$deadline" ]; then
    echo "database readiness timed out after ${deadline}s" >&2
    exit 1
  fi
  sleep 1
done

echo "atomically replacing the evaluation fixture on ${PGHOST}/${PGDATABASE}..."
psql -v ON_ERROR_STOP=1 -v seed_file="${SEED_FILE}" <<'SQL'
BEGIN;
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
\i :seed_file
GRANT USAGE ON SCHEMA public TO eval_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO eval_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO eval_app;
COMMIT;
SQL
echo "seed complete"
