# services/validation.py

from __future__ import annotations
from typing import Dict, List, Optional


def _safe_int(val) -> Optional[int]:
    try:
        if val is None:
            return None
        return int(val)
    except (TypeError, ValueError):
        return None


def validate_inputs_before_solve(inputs: Dict) -> List[str]:
    """
    Validate solver inputs BEFORE calling PuLP.
    Returns a list of readable hints. Empty list => safe to attempt solve.

    Expected keys (from build_inputs_from_plan):
      - courses: List[str]
      - allowed_semesters: Dict[str, List[int]]
      - credits: Dict[str, int]
      - max_credits_per_semester: Dict[int, int]
      - prereqs: Dict[str, List[str]]  (optional)
    """
    hints: List[str] = []

    courses = inputs.get("courses", []) or []
    allowed: Dict[str, List[int]] = inputs.get("allowed_semesters", {}) or {}
    credits: Dict[str, int] = inputs.get("credits", {}) or {}
    max_by_sem: Dict[int, int] = inputs.get("max_credits_per_semester", {}) or {}

    # If there are no courses, this is already handled by your ValueError,
    # but keep it safe anyway.
    if not courses:
        hints.append("This plan has no courses yet. Add courses before solving.")
        return hints

    # Rule 1: Course has no allowed semesters
    for c in courses:
        if not allowed.get(c):
            hints.append(f'Course "{c}" has no allowed semesters (offerings). Add at least one offering.')

    # Derive "total_semesters" from max_credits_per_semester keys (solver universe)
    # This matches how your solver actually reasons about semesters.
    semesters = sorted(max_by_sem.keys())
    total_semesters = max(semesters) if semesters else None

    # Derive a plan-wide max credit limit if it looks constant across semesters
    per_sem_limits = [v for v in max_by_sem.values() if _safe_int(v) is not None]
    max_limit = None
    if per_sem_limits:
        # if limits vary, we can still use the minimum as a safe capacity bound
        max_limit = min(int(v) for v in per_sem_limits)

    # Rule 2: Any course exceeds per-semester max (use min limit as conservative bound)
    if max_limit is not None and max_limit > 0:
        for c in courses:
            c_credits = _safe_int(credits.get(c))
            if c_credits is not None and c_credits > max_limit:
                hints.append(
                    f'Course "{c}" is {c_credits} credits but max per semester is {max_limit}. '
                    "Increase the max or adjust the course."
                )

    # Rule 3: Total credits exceed capacity (only meaningful if we have semesters + max)
    if total_semesters is not None and max_limit is not None and total_semesters > 0 and max_limit > 0:
        total_credits = 0
        unknown = False
        for c in courses:
            c_credits = _safe_int(credits.get(c))
            if c_credits is None:
                unknown = True
            else:
                total_credits += c_credits

        capacity = total_semesters * max_limit
        if total_credits > capacity:
            hints.append(
                f"Total credits in plan ({total_credits}) exceed capacity "
                f"({total_semesters} semesters x {max_limit} max = {capacity}). "
                "Increase total semesters / max credits, or reduce credits."
            )
        elif unknown:
            hints.append("Some courses have missing/invalid credit values; capacity checks may be incomplete.")

    return hints
