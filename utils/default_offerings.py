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

    y = _safe_int(m.get("academic_year"))
    if y is None or y < 1:
        return list(range(1, total_semesters + 1))

    start = (y - 1) * sp + 1
    end = min(total_semesters, y * sp)
    if start > total_semesters:
        return list(range(1, total_semesters + 1))

    return list(range(start, end + 1))


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
