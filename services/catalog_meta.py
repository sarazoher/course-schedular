from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import current_app


@lru_cache(maxsize=1)
def load_catalog_meta() -> dict[str, Any]:
    """
    Loads non-schema catalog metadata extracted from XLSX into catalog_meta.json.
    Safe defaults if file missing.
    """
    path = Path(current_app.config["CATALOG_DIR"]) / "catalog_meta.json"
    if not path.exists():
        return {"version": 1, "courses": {}, "degrees": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def meta_for_code(code: str) -> dict[str, Any]:
    meta = load_catalog_meta()
    return (meta.get("courses") or {}).get(str(code), {})


def list_degrees() -> dict[str, Any]:
    meta = load_catalog_meta()
    return meta.get("degrees") or {}
