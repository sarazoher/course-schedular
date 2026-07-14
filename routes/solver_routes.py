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
from models.plan_course import PlanCourse
from models.catalog_course import CatalogCourse
from models.course import Course
from services.solver import build_inputs_from_plan, solve_plan as solve_plan_service
from services.validation import validate_inputs_before_solve
from services.catalog_meta import load_catalog_for_plan
from utils.semesters import format_semester_label
from utils.optional_courses import get_optional_course_codes
from utils.prereq_display import extract_recognized_courses

def _dedupe_warnings(warnings: list[Any]) -> list[Any]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Any] = []
    for w in warnings or []:
        if isinstance(w, dict):
            course = str(w.get("course") or "").strip()
            kind = str(w.get("kind") or w.get("type") or "").strip()
            raw = str(w.get("raw") or w.get("message") or w.get("detail") or "").strip()
            key = (course, kind, raw)
        else:
            key = ("", "", str(w))

        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


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
    has_solution = bool(latest and latest.solution_json)

    payload = {}
    semester_labels = {}
    courses_by_semester = {}
    warnings = []
    meta = {}
    status = None
    semesters = []
    infeasible_hints = []

    if has_solution:
        payload = json.loads(latest.solution_json)
        status = latest.status
        semesters = payload.get("semesters", [])
        infeasible_hints = payload.get("infeasible_hints", [])

        # Convert keys back to ints for template logic.
        semester_labels = {int(k): v for k, v in (payload.get("semester_labels") or {}).items()}
        courses_by_semester = {int(k): v for k, v in (payload.get("courses_by_semester") or {}).items()}
        warnings = json.loads(latest.warnings_json) if latest.warnings_json else []
        meta = json.loads(latest.meta_json) if latest.meta_json else {}
    optional_codes = get_optional_course_codes()

    catalog_meta = load_catalog_for_plan(plan.id)
    catalog_meta_courses = catalog_meta.get("courses") or {}

    # Code -> name mapping from DB (used to show names in Warnings for both
    # the course being scheduled and the raw prereq/missing course code)
    catalog_rows = CatalogCourse.query.with_entities(CatalogCourse.code, CatalogCourse.name).all()
    course_name_by_code = {str(code): (name or "") for code, name in catalog_rows}
     
    # Collect which courses have warnings (for schedule highlighting + counts)
    warn_courses: set[str] = set()
    warn_counts_by_kind: dict[str, int] = {}

    for w in warnings or []:
        if isinstance(w, dict):
            c = str(w.get("course") or "").strip()
            if c:
                warn_courses.add(c)

            kind = str(w.get("kind") or w.get("type") or "").strip() or "warning"
            warn_counts_by_kind[kind] = warn_counts_by_kind.get(kind, 0) + 1
        else:
            warn_counts_by_kind["warning"] = warn_counts_by_kind.get("warning", 0) + 1

    # Display-only prereq/coreq helpers for Schedule (UI readability only).
    # Map course_code -> [(req_code, req_name), ...]
    prereq_refs_by_code: dict[str, list[tuple[str, str]]] = {}
    coreq_refs_by_code: dict[str, list[tuple[str, str]]] = {}

    for code, meta_row in (catalog_meta_courses or {}).items():
        code_s = str(code).strip()
        prereq_refs_by_code[code_s] = extract_recognized_courses(
            meta_row.get("prereq_text"),
            course_name_by_code,
        )
        coreq_refs_by_code[code_s] = extract_recognized_courses(
            meta_row.get("coreq_text"),
            course_name_by_code,
        )

    return render_template(
        "plan_schedule.html",
        plan=plan,
        has_solution=has_solution,
        status=status,
        semesters=semesters,
        semester_labels=semester_labels,
        courses_by_semester=courses_by_semester,
        infeasible_hints=infeasible_hints,
        warnings=warnings,
        warn_courses=warn_courses,
        warn_counts_by_kind=warn_counts_by_kind,
        optional_codes=optional_codes,
        meta=meta,
        catalog_meta_courses=catalog_meta_courses,
        course_name_by_code=course_name_by_code,
        prereq_refs_by_code=prereq_refs_by_code,
        coreq_refs_by_code=coreq_refs_by_code,
    )


@main_bp.route("/plans/<int:plan_id>/schedule/edit", methods=["GET", "POST"])
@login_required
def edit_semesters(plan_id: int):
    """Allow manual overrides of course -> semester assignments on top of
    the latest saved solution.

    This does NOT re-run the solver. It simply reshuffles courses between
    existing semester buckets and keeps the same number of semesters.
    """
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
        flash("No existing schedule to edit. Solve the plan first.", "warning")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    payload = json.loads(latest.solution_json)

    # Current semesters and labels from the stored payload
    raw_semesters = payload.get("semesters") or []
    semesters: list[int] = []
    for s in raw_semesters:
        if isinstance(s, int):
            semesters.append(s)
        else:
            try:
                semesters.append(int(s))
            except (TypeError, ValueError):
                continue
    semesters = sorted(set(semesters))

    raw_semester_labels = payload.get("semester_labels") or {}
    semester_labels: dict[int, str] = {}
    for k, v in raw_semester_labels.items():
        try:
            key_int = int(k)
        except (TypeError, ValueError):
            continue
        semester_labels[key_int] = v

    raw_buckets = payload.get("courses_by_semester") or {}
    courses_by_semester: dict[int, list[dict[str, Any]]] = {}
    for k, bucket in raw_buckets.items():
        try:
            sem = int(k)
        except (TypeError, ValueError):
            continue
        if sem not in semesters:
            semesters.append(sem)
        if not isinstance(bucket, list):
            continue
        courses_by_semester.setdefault(sem, [])
        for c in bucket:
            if isinstance(c, dict):
                courses_by_semester[sem].append(c)

    semesters = sorted(courses_by_semester.keys() or semesters)

    # Flatten courses (one row per code) in a stable order
    course_rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for sem in semesters:
        for c in courses_by_semester.get(sem, []):
            code = str(c.get("code") or "").strip()
            if not code:
                continue
            if code in seen_codes:
                continue
            seen_codes.add(code)
            course_rows.append(
                {
                    "code": code,
                    "name": c.get("name") or code,
                    "credits": c.get("credits"),
                    "current_semester": sem,
                }
            )

    course_rows.sort(key=lambda r: (r["current_semester"], r["code"]))

    if request.method == "POST":
        # Read new semester choices from the form
        new_schedule: dict[str, int] = {}
        for row in course_rows:
            code = row["code"]
            field_name = f"sem_{code}"
            raw_val = request.form.get(field_name)

            if not raw_val:
                # Treat empty as "unassigned" (course dropped from schedule)
                continue

            try:
                sem = int(raw_val)
            except ValueError:
                continue

            if sem not in semesters:
                # Out-of-range semester (should not happen with our UI)
                continue

            new_schedule[code] = sem

        if not new_schedule:
            flash("No semester assignments were provided; keeping the existing schedule.", "warning")
            return redirect(url_for("main.view_saved_schedule", plan_id=plan.id))

        # Rebuild courses_by_semester using current plan data
        cat = load_catalog_for_plan(plan.id)
        meta_courses = cat.get("courses") or {}

        plan_courses = (
            PlanCourse.query
            .filter_by(plan_id=plan.id)
            .outerjoin(CatalogCourse, PlanCourse.catalog_course_id == CatalogCourse.id)
            .outerjoin(Course, PlanCourse.legacy_course_id == Course.id)
            .all()
        )

        display_by_code: dict[str, dict[str, Any]] = {}
        for pc in plan_courses:
            code = None
            name = None
            credits = None

            # Prefer legacy (plan-local overrides) when present
            if pc.legacy_course is not None:
                code = str(pc.legacy_course.code).strip()
                name = pc.legacy_course.name
                credits = pc.legacy_course.credits
            elif pc.catalog_course is not None:
                code = str(pc.catalog_course.code).strip()
                name = pc.catalog_course.name
                credits = (
                    float(pc.catalog_course.credits)
                    if pc.catalog_course.credits is not None
                    else None
                )

            if code:
                display_by_code[code] = {"name": name or code, "credits": credits}

        new_courses_by_semester: dict[int, list[dict[str, Any]]] = {
            s: [] for s in semesters
        }

        for code, sem in new_schedule.items():
            if sem not in new_courses_by_semester:
                continue

            m = meta_courses.get(str(code), {})
            coreq_text = m.get("coreq_text") if isinstance(m, dict) else None

            d = display_by_code.get(str(code).strip(), {})

            new_courses_by_semester[sem].append(
                {
                    "code": code,
                    "name": d.get("name") or code,
                    "credits": d.get("credits"),
                    "coreq_text": coreq_text,
                }
            )

        for s in semesters:
            new_courses_by_semester[s].sort(
                key=lambda d: (str(d.get("code") or ""))
            )

        # Carry forward previous meta/warnings but mark this as a manual override
        meta_old: dict[str, Any] = {}
        if getattr(latest, "meta_json", None):
            try:
                raw_meta = json.loads(latest.meta_json)
                if isinstance(raw_meta, dict):
                    meta_old = raw_meta
            except Exception:
                meta_old = {}

        meta_old = dict(meta_old or {})
        meta_old["phase"] = "manual_override"
        meta_old["manual_override"] = True

        warnings_old: list[dict[str, Any]] = []
        if getattr(latest, "warnings_json", None):
            try:
                raw_w = json.loads(latest.warnings_json)
                if isinstance(raw_w, list):
                    warnings_old = raw_w
            except Exception:
                warnings_old = []

        _save_latest_solution(
            plan_id=plan.id,
            status=getattr(latest, "status", None) or "ManualOverride",
            semesters=semesters,
            semester_labels=semester_labels,
            courses_by_semester=new_courses_by_semester,
            infeasible_hints=payload.get("infeasible_hints") or [],
            objective_value=None,
            warnings=warnings_old,
            meta=meta_old,
        )

        flash("Semester assignments updated.", "success")
        return redirect(url_for("main.view_saved_schedule", plan_id=plan.id))

    # GET: show edit form
    return render_template(
        "edit_semesters.html",
        plan=plan,
        has_solution=True,
        semesters=semesters,
        semester_labels=semester_labels,
        courses=course_rows,
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

# ------------------------------------------------------------
# Solver behavior flags (Plan constraints)
#
# These flags come from PlanConstraint, which is persisted via
# the Plan Settings page.
#
# Flow:
#   Plan Settings (UI checkbox)
#     → routes/plans.py (save to DB)
#     → PlanConstraint fields
#     → read here at solve-time
#     → passed into services/solver.py
#
# If no constraint row exists yet, we default to the "safe"
# behavior (all enforcement ON, prefer earlier completion).
# ------------------------------------------------------------
    pc: Optional[PlanConstraint] = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()
    use_prereqs = True if pc is None else bool(pc.enforce_prereqs)
    use_credit_limits = True if pc is None else bool(pc.enforce_credit_limits)

    # When True:
    #   Solver minimizes the final semester used (finish ASAP),
    #   then packs courses earlier within that horizon.
    #
    # When False:
    #   Solver simply packs courses earlier overall.
    minimize_last_semester = True if pc is None else bool(pc.minimize_last_semester)

    # Build inputs from DB (keeping, still useful for prechecks and rendering payload)
    try:
        inputs = build_inputs_from_plan(plan.id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("main.view_plan", plan_id=plan_id))

    # Sidecar metadata (display-only)
    cat = load_catalog_for_plan(plan.id)
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
    warnings = _dedupe_warnings(warnings)

    semesters = sorted(inputs["max_credits_per_semester"].keys())
    semesters_per_year = pc.semesters_per_year if pc and pc.semesters_per_year else None
    semester_labels = {s: format_semester_label(s, semesters_per_year) for s in semesters}

    courses_by_semester: dict[int, list[dict[str, Any]]] = {s: [] for s in semesters}
    infeasible_hints: list[str] = []

    if status == "Optimal":
        # Map course_code -> display info (works for catalog-linked AND legacy/manual)
        plan_courses = (
            PlanCourse.query
            .filter_by(plan_id=plan.id)
            .outerjoin(CatalogCourse, PlanCourse.catalog_course_id == CatalogCourse.id)
            .outerjoin(Course, PlanCourse.legacy_course_id == Course.id)
            .all()
        )

        display_by_code: dict[str, dict[str, Any]] = {}
        for pc in plan_courses:
            code = None
            name = None
            credits = None

            # Prefer legacy (plan-local overrides) when present
            if pc.legacy_course is not None:
                code = str(pc.legacy_course.code).strip()
                name = pc.legacy_course.name
                credits = pc.legacy_course.credits
            elif pc.catalog_course is not None:
                code = str(pc.catalog_course.code).strip()
                name = pc.catalog_course.name
                credits = float(pc.catalog_course.credits) if pc.catalog_course.credits is not None else None

            if code:
                display_by_code[code] = {"name": name or code, "credits": credits}

        for code, chosen_sem in schedule.items():
            if chosen_sem is None:
                continue
            if chosen_sem not in courses_by_semester:
                # Out-of-range semester (should not happen, but keep safe)
                continue

            m = meta_courses.get(str(code), {})
            coreq_text = m.get("coreq_text") if isinstance(m, dict) else None

            d = display_by_code.get(str(code).strip(), {})

            courses_by_semester[chosen_sem].append(
                {
                    "code": code,
                    "name": d.get("name") or code,
                    "credits": d.get("credits"),
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
