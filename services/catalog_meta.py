from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

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

def _plan_seed_path(plan_id: int) -> Path:
    uploads = Path(current_app.instance_path) / "uploads"
    return uploads / f"plan_{plan_id}_catalog_meta.json"


def has_plan_catalog_seed(plan_id: int) -> bool:
    """
    True if this plan has its own uploaded catalog seed file.
    """
    try:
        return _plan_seed_path(plan_id).exists()
    except Exception:
        return False


def load_catalog_for_plan(plan_id: int) -> Dict[str, Any]:
    """
    Catalog source selector (spec-locked):

    - If instance/uploads/plan_<id>_catalog_meta.json exists:
        treat it as the FULL catalog seed for this plan (replacement).
        Do NOT merge course data with the global catalog.

    - Otherwise:
        use global catalog_meta.json.
    """
    base = load_catalog_meta()
    try:
        seed_path = _plan_seed_path(plan_id)
        if not seed_path.exists():
            return base

        seed = json.loads(seed_path.read_text(encoding="utf-8")) or {}
        courses = seed.get("courses") or {}
        if not isinstance(courses, dict):
            return base

        # Ensure expected top-level keys exist. We do NOT merge course dicts.
        out: Dict[str, Any] = dict(seed)
        out["version"] = out.get("version") or 1
        out["courses"] = courses

        # Degrees are used for UI filtering; most plan seeds don't include them.
        # This is not a course-data merge (no mixing of course truths).
        if "degrees" not in out or not isinstance(out.get("degrees"), dict):
            out["degrees"] = base.get("degrees") or {}
        return out
    except Exception:
        # Fail-soft: never break the app due to a bad seed file
        return base


# Backward compatibility: older code calls this name.
def load_catalog_meta_for_plan(plan_id: int) -> Dict[str, Any]:
    return load_catalog_for_plan(plan_id)


def meta_for_code(code: str) -> dict[str, Any]:
    meta = load_catalog_meta()
    return (meta.get("courses") or {}).get(str(code), {})

def meta_for_code_for_plan(plan_id: int, code: str) -> dict[str, Any]:
    """
    Course metadata lookup using the catalog source selected for this plan
    (plan seed if present, otherwise global catalog).
    """
    meta = load_catalog_for_plan(plan_id)
    return (meta.get("courses") or {}).get(str(code), {})

def list_degrees() -> dict[str, Any]:
    meta = load_catalog_meta()
    return meta.get("degrees") or {}
