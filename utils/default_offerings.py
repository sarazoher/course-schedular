from __future__ import annotations

from typing import Any, Optional, List, Dict


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


def default_semesters_for_meta(
    *,
    meta: Optional[Dict[str, Any]],
    total_semesters: int,
    semesters_per_year: Optional[int],
) -> List[int]:
    """Compute the *default* allowed semester numbers for a course.

    Policy:
      - If metadata includes academic_year and semesters_per_year is set (or assumed 2),
        allow that year's semester window.
      - Otherwise allow all semesters 1..total_semesters.

    Shared between:
      - solver inputs (when no explicit DB offerings exist)
      - Offerings UI ("Default (auto)" mode)
    """
    if total_semesters < 1:
        return []

    sp = semesters_per_year or 2
    m = meta if isinstance(meta, dict) else {}

    # 0) Explicit offered semesters override everything else
    offered = m.get("offered_semesters")
    if isinstance(offered, list):
        cleaned: List[int] = []
        for v in offered:
            iv = _safe_int(v)
            if iv is not None and 1 <= iv <= total_semesters:
                cleaned.append(iv)
        if cleaned:
            return sorted(set(cleaned))

    # 1) Otherwise: be permissive by default.
    #
    # Stage A policy: "academic_year" is a *recommendation*, not a hard offering constraint.
    # If you want tighter offerings, provide explicit "offered_semesters" in metadata
    # (or override offerings in the DB UI).
    return list(range(1, total_semesters + 1))


def default_semesters_for_code(
    *,
    code: str,
    meta_courses: Dict[str, Any],
    total_semesters: int,
    semesters_per_year: Optional[int],
) -> List[int]:
    """Same as default_semesters_for_meta, but looks up metadata by course code."""
    meta = (meta_courses or {}).get(str(code).strip(), {})
    if not isinstance(meta, dict):
        meta = {}
    return default_semesters_for_meta(
        meta=meta,
        total_semesters=total_semesters,
        semesters_per_year=semesters_per_year,
    )
