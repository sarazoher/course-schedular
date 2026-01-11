#!/usr/bin/env bash
set -e

DB_PATH="instance/app.db"
UPLOAD_DIR="instance/uploads"

echo "==> Removing dev DB..."
rm -f "$DB_PATH"

echo "==> Recreating schema..."
python init_db.py

echo "==> Checking for uploaded catalog..."
mkdir -p "$UPLOAD_DIR"

# Safely find the most recent uploaded .xlsx/.xlsm (if any)
LATEST_XLSX="$(
  find "$UPLOAD_DIR" -maxdepth 1 -type f \( -name '*.xlsx' -o -name '*.xlsm' \) -print0 \
    | xargs -0 ls -1t 2>/dev/null \
    | head -n 1 || true
)"

if [ -n "$LATEST_XLSX" ]; then
  echo "==> Found uploaded catalog: $LATEST_XLSX"
  echo "==> DB is empty after reset."
  echo "==> Preferred flow: import via UI (admin upload)."

  if [ "${FORCE_SEED:-0}" = "1" ]; then
    echo "==> FORCE_SEED=1 set; seeding anyway."
    python seed_catalog_db.py 2>/dev/null || python seed_vatalog_db.py 2>/dev/null || \
      echo "==> No seed script found. Skipping."
    echo "==> Seed attempt complete."
  else
    echo "==> Skipping seed (upload exists). To seed anyway: FORCE_SEED=1 ./scripts/rebuild_dev_db.sh"
  fi
else
  echo "==> No uploaded catalog found."
  echo "==> Seeding catalog (bootstrap)..."
  python seed_catalog_db.py 2>/dev/null || python seed_vatalog_db.py 2>/dev/null || \
    echo "==> No seed script found. Skipping."
  echo "==> Seed attempt complete."
fi

echo "==> Done. Run: python app.py"
