#!/usr/bin/env bash
set -e

DB_PATH="instance/app.db"
UPLOAD_DIR="instance/uploads"

echo "==> Removing dev DB..."
rm -f "$DB_PATH"

mkdir -p "$UPLOAD_DIR"

# -----------------------------------------
# Optional: clear plan-scoped upload artifacts
#
# Usage:
#   CLEAR_UPLOADS=1 ./scripts/rebuild_dev_db.sh
#   NUKE_UPLOADS=1  ./scripts/rebuild_dev_db.sh
# -----------------------------------------
if [ "${NUKE_UPLOADS:-0}" = "1" ]; then
  echo "==> NUKE_UPLOADS=1: removing ALL files in $UPLOAD_DIR ..."
  rm -f "$UPLOAD_DIR"/*
elif [ "${CLEAR_UPLOADS:-0}" = "1" ]; then
  echo "==> CLEAR_UPLOADS=1: removing plan-scoped artifacts in $UPLOAD_DIR ..."
  rm -f "$UPLOAD_DIR"/plan_*_catalog_meta.json \
        "$UPLOAD_DIR"/plan_*_manual_schedule.json \
        "$UPLOAD_DIR"/plan_*_catalog_raw.xlsx 2>/dev/null || true
fi

echo "==> Recreating schema..."
python3 init_db.py

echo "==> Checking for uploaded catalog..."
LATEST_XLSX="$(
  find "$UPLOAD_DIR" -maxdepth 1 -type f \( -name '*.xlsx' -o -name '*.xlsm' \) -print0 \
    | xargs -0 ls -1t 2>/dev/null \
    | head -n 1 || true
)"

if [ "${SKIP_SEED:-0}" = "1" ]; then
  echo "==> SKIP_SEED=1 set; skipping seed."
  if [ -n "$LATEST_XLSX" ]; then
    echo "==> Note: uploads exist (latest: $LATEST_XLSX) but DB will stay empty."
  fi
else
  echo "==> Seeding catalog (bootstrap)..."
  python3 seed_catalog_db.py 2>/dev/null || python3 seed_vatalog_db.py 2>/dev/null || \
    echo "==> No seed script found. Skipping."
  echo "==> Seed attempt complete."
fi

echo "==> Done. Run: python3 app.py"
