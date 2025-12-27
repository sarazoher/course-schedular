"""Solver endpoints

- POST /solve stores the latest solver output as a PlanSolution row
- GET  /schedule renders the latest saved solution (no re-solve)
"""

import json
from typing import Optional, Any

from flask import render_template, redirect, url_for, request, abort, flash
from flask_login import login_required, current_user

from . import main_bp
from extensions import db
from models.degree_plan import DegreePlan
from models.plan_constraint import PlanConstraint
from models.plan_solution import PlanSolution
from services.solver import build_inputs_from_plan, solve_plan as solve_plan_service
from services.validation import validate_inputs_before_solve
from services.catalog_meta import load_catalog_meta 
from utils.semesters import format_semester_label

def _is_optional_by_code(code: str) -> bool:
    s = str(code).strip()
    if s.startswith("851"):
        return True
    if s.startswith("850"):
        return False
    return True

def _save_latest_solution(
    *,
    plan_id: int,
    status: str,
    semesters: list[int],
    semester_labels: dict[int, str],
    courses_by_semester: dict[int, list[dict[str, Any]]],
    infeasible_hints: Optional[list[str]],
    objective_value: Optional[float] = None,
    warnings: Optional[list[dict[str, Any]]] = None,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    """Keep the latest solver output for a plan.

    MVV policy: keep exactly ONE latest solution per plan.
    (Delete old rows and insert one fresh snapshot.)

    Notes:
    - `solution_json` stores the schedule payload used by plan_schedule.html
    - `warnings_json` stores ignored external/unresolved prereq leaves...
    - We intentionally do NOT re-solve in GET /schedule
    """
    # Delete previous snapshots for this plan (keep only the latest one)
    PlanSolution.query.filter_by(plan_id=plan_id).delete()

    # JSON forces dict keys to strings, so store keys as strings explicitly.
    payload = {
        "semesters": semesters,
        "semester_labels": {str(k): v for k, v in (semester_labels or {}).items()},
        "courses_by_semester": {str(k): v for k, v in (courses_by_semester or {}).items()},
        "infeasible_hints": infeasible_hints or [],
    }

    sol = PlanSolution(
        plan_id=plan_id,
        status=status,
        objective_value=objective_value,
        solution_json=json.dumps(payload, ensure_ascii=False),
        warnings_json=json.dumps(warnings or [], ensure_ascii=False),
        meta_json=json.dumps(meta or {}, ensure_ascii=False),
    )

    db.session.add(sol)
    db.session.commit()


@main_bp.get("/plans/<int:plan_id>/schedule")
@login_required
def view_saved_schedule(plan_id: int):
    """Render the latest saved schedule for a plan (no re-solve)."""

    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    latest = (
        PlanSolution.query.filter_by(plan_id=plan.id)
        .order_by(PlanSolution.created_at.desc())
        .first()
    )
    if latest is None or not latest.solution_json:
        flash("No saved schedule for this plan yet. Click Solve first.", "info")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    payload = json.loads(latest.solution_json)

    # Convert keys back to ints for template logic.
    semester_labels = {int(k): v for k, v in (payload.get("semester_labels") or {}).items()}
    courses_by_semester = {int(k): v for k, v in (payload.get("courses_by_semester") or {}).items()}
    warnings = json.loads(latest.warnings_json) if latest.warnings_json else []
    meta = json.loads(latest.meta_json) if latest.meta_json else {}

    # Optional codes for badges in schedule view
    cat = load_catalog_meta()
    meta_courses = cat.get("courses") or {}
    optional_codes = {str(code) for code in meta_courses.keys() if _is_optional_by_code(code)}

    return render_template(
        "plan_schedule.html",
        plan=plan,
        status=latest.status,
        semesters=payload.get("semesters", []),
        semester_labels=semester_labels,
        courses_by_semester=courses_by_semester,
        infeasible_hints=payload.get("infeasible_hints", []),
        warnings=warnings,
        meta=meta,
        optional_codes=optional_codes,
    )


@main_bp.route("/plans/<int:plan_id>/solve", methods=["GET", "POST"])
@login_required
def solve_plan(plan_id: int):
    """User-facing route.

    behavior:
    - Builds solver inputs from DB (legacy offerings/credits)
    - Runs the solver service which enforces catalog prereq IR (ReqAnd/ReqOr) at solve-time
    - Persists ONE latest PlanSolution snapshot (schedule + warnings)
    - Redirects to the saved schedule view (no re-solve on GET)
    """
    # Safety: intended to be triggered from a POST button.
    if request.method == "GET":
        flash("Use the 'Solve' button to run the solver.", "info")
        return redirect(url_for("main.view_plan", plan_id=plan_id))

    # Plan must belong to current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # Plan constraints (flags)
    pc: Optional[PlanConstraint] = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()
    use_prereqs = True if pc is None else bool(pc.enforce_prereqs)
    use_credit_limits = True if pc is None else bool(pc.enforce_credit_limits)
    minimize_last_semester = True if pc is None else bool(pc.minimize_last_semester)

    # Build inputs from DB (keeping, still useful for prechecks and rendering payload)
    try:
        inputs = build_inputs_from_plan(plan.id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("main.view_plan", plan_id=plan_id))

    # Sidecar metadata (display-only)
    cat = load_catalog_meta()
    meta_courses = cat.get("courses") or {}

    # Pre-solve validation (existing guardrails)
    precheck_hints = validate_inputs_before_solve(inputs)
    if precheck_hints:
        # Persist as an infeasible snapshot so /schedule shows the hints immediately
        semesters = sorted(inputs["max_credits_per_semester"].keys())
        semesters_per_year = pc.semesters_per_year if pc and pc.semesters_per_year else None
        semester_labels = {s: format_semester_label(s, semesters_per_year) for s in semesters}

        _save_latest_solution(
            plan_id=plan.id,
            status="Not solved",
            semesters=semesters,
            semester_labels=semester_labels,
            courses_by_semester={s: [] for s in semesters},
            infeasible_hints=precheck_hints,
            objective_value=None,
            warnings=[],
            meta={
                "use_prereqs": use_prereqs,
                "use_credit_limits": use_credit_limits,
                "minimize_last_semester": minimize_last_semester,
                "phase": "precheck",
            },
        )
        return redirect(url_for("main.view_saved_schedule", plan_id=plan.id))

    # call solver service (IR prereqs enforced inside services/solver.py)
    result = solve_plan_service(
        plan.id,
        use_credit_limits=use_credit_limits,
        use_prereqs_ir=use_prereqs,
        minimize_last_semester=minimize_last_semester,
        msg=False,
    )

    status: str = result.get("status", "error")
    schedule: dict[str, Optional[int]] = result.get("schedule", {})  # course_code -> semester
    warnings: list[dict[str, Any]] = result.get("warnings", [])

    semesters = sorted(inputs["max_credits_per_semester"].keys())
    semesters_per_year = pc.semesters_per_year if pc and pc.semesters_per_year else None
    semester_labels = {s: format_semester_label(s, semesters_per_year) for s in semesters}

    courses_by_semester: dict[int, list[dict[str, Any]]] = {s: [] for s in semesters}
    infeasible_hints: list[str] = []

    if status == "Optimal":
        # Map course_code -> Course row for display (title/credits...)
        course_by_code = {c.code: c for c in plan.courses}

        for code, chosen_sem in schedule.items():
            if chosen_sem is None:
                continue
            if chosen_sem not in courses_by_semester:
                # Out-of-range semester (should not happen, but keep safe)
                continue

            course_row = course_by_code.get(code)
            m = meta_courses.get(str(code), {})
            coreq_text = m.get("coreq_text") if isinstance(m, dict) else None

            courses_by_semester[chosen_sem].append(
                {
                    "code": code,
                    "name": course_row.name if course_row else code,
                    "credits": course_row.credits if course_row else None,
                    "coreq_text": coreq_text,  # display-only (NOT enforced)
                }
            )

        # Stable ordering in UI
        for s in semesters:
            courses_by_semester[s].sort(key=lambda d: (d.get("code") or ""))
    else:
        # Minimal infeasible hints. More detailed diagnosis will be added later.
        allowed = inputs.get("allowed_semesters", {})
        no_offerings = [c for c in inputs.get("courses", []) if not allowed.get(c)]
        if no_offerings:
            infeasible_hints.append(
                "Some courses have no offerings (no allowed semesters). "
                "Add offerings for: " + ", ".join(no_offerings)
            )

        if status == "Infeasible":
            infeasible_hints.append(
                "The solver could not find a feasible schedule with the current offerings, constraints, and prerequisites."
            )
        else:
            infeasible_hints.append(
                f"Solver status: {status}. Try adjusting offerings/constraints, then solve again."
            )

    _save_latest_solution(
        plan_id=plan.id,
        status=status,
        semesters=semesters,
        semester_labels=semester_labels,
        courses_by_semester=courses_by_semester,
        infeasible_hints=infeasible_hints,
        objective_value=None,  # objective capture postponed 
        warnings=warnings,
        meta={
            "use_prereqs": use_prereqs,
            "use_credit_limits": use_credit_limits,
            "minimize_last_semester": minimize_last_semester,
            "phase": "solve_day4_ir",
        },
    )

    return redirect(url_for("main.view_saved_schedule", plan_id=plan.id))
