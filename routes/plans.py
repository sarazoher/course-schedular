from flask import render_template, redirect, url_for, request, abort, flash, current_app
from flask_login import current_user, login_required
from pathlib import Path
import json

from . import main_bp
from models.course import Course
from models.catalog_course import CatalogCourse
from models.plan_course import PlanCourse
from models.degree_plan import DegreePlan
from models.plan_constraint import PlanConstraint
from models.prerequisite import Prerequisite
from models.plan_solution import PlanSolution
from services.catalog_meta import load_catalog_for_plan, has_plan_catalog_seed
from utils.optional_courses import get_optional_course_codes, is_optional_by_code
from extensions import db


@main_bp.route("/")
def home():
    # If logged in, go to the real entry point (Dashboard)
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("home.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    # Fetch plans for the logged-in user
    degree_plans = DegreePlan.query.filter_by(user_id=current_user.id).all()
    return render_template("dashboard.html", degree_plans=degree_plans)


@main_bp.route("/plans/new", methods=["GET", "POST"])
@login_required
def create_plan():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()

        if not name:
            flash("Plan name is required.", "error")
            return redirect(url_for("main.create_plan"))
        
        # check if this user already has a plan with the same name
        existing = DegreePlan.query.filter_by(
            user_id=current_user.id,
            name=name,
        ).first()
        if existing:
            flash("Plan of this name already exists.", "error")
            return redirect(url_for("main.create_plan"))

        plan = DegreePlan(user_id=current_user.id, name=name)
        db.session.add(plan)
        db.session.commit()

        flash("Degree plan created.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("create_plan.html")


@main_bp.route("/plans/<int:plan_id>")
@login_required
def view_plan(plan_id: int):
   # show a single plan, with its courses listed and a simple 'add course' form
 
    plan = DegreePlan.query.filter_by(
        id = plan_id,
        user_id = current_user.id,
    ).first()
    if plan is None:
        abort(404)
    # Plan courses can be catalog-linked OR legacy/manual
    plan_courses = (
        PlanCourse.query
        .filter_by(plan_id=plan.id)
        .all()
    )

    # Stable sort by visible code
    plan_courses.sort(
        key=lambda pc: str(
            pc.catalog_course.code if pc.catalog_course else (pc.legacy_course.code if pc.legacy_course else '')
        )
    )
    # Count plan courses that are NOT linked to the global catalog
    unlinked_count = sum(1 for pc in plan_courses if pc.catalog_course_id is None)
    constraints = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()

    latest_solution = (
        PlanSolution.query
        .filter_by(plan_id=plan_id)
        .order_by(PlanSolution.created_at.desc())
        .first()
        )
    
    # ---- load sidecar metadata + degree filter ----
    selected_degree = (request.args.get("degree") or "CS").strip()

    catalog = load_catalog_for_plan(plan.id)
    meta_courses = catalog.get("courses") or {}
    using_plan_seed = has_plan_catalog_seed(plan.id)
    
    optional_codes = get_optional_course_codes()

    degrees = catalog.get("degrees") or {"CS": {"label": "Computer Science", "active": True}}

    # Catalog dropdown source:
    # - If plan seed exists: dropdown comes from that plan file (replacement)
    # - Otherwise: dropdown comes from global CatalogCourse DB + global meta
    catalog_courses = []
    if using_plan_seed:
        for code, m in meta_courses.items():
            code_s = str(code).strip()
            if not code_s:
                continue
            mm = m if isinstance(m, dict) else {}
            tags = mm.get("degree_tags") or ["CS"]
            if selected_degree and selected_degree not in tags:
                continue
            catalog_courses.append({
                "code": code_s,
                "name": (mm.get("name") or code_s),
                "credits": mm.get("credits"),
            })
        catalog_courses.sort(key=lambda d: str(d.get("code") or ""))
    else:
        all_catalog_courses = CatalogCourse.query.order_by(CatalogCourse.code.asc()).all()
        for c in all_catalog_courses:
            m = meta_courses.get(str(c.code), {})
            tags = m.get("degree_tags") or ["CS"]
            if selected_degree and selected_degree not in tags:
                continue
            catalog_courses.append(c)

    # Years dropdown helper (based on filtered metadata for selected degree)
    years_set = set()
    for c in catalog_courses:
        code = str(c.get("code") if isinstance(c, dict) else c.code)
        m = meta_courses.get(code, {}) if isinstance(meta_courses.get(code, {}), dict) else {}
        y = m.get("academic_year")
        if y:
            years_set.add(str(y))
    available_years = sorted(years_set, key=lambda s: int(s) if s.isdigit() else 999)

    return render_template(
        "plan_detail.html", 
        plan = plan,
        plan_courses=plan_courses,
        constraints=constraints,
        catalog_courses=catalog_courses,
        latest_solution=latest_solution,
        degrees=degrees,
        selected_degree=selected_degree,
        catalog_meta_courses=meta_courses,
        optional_codes=optional_codes,
        available_years=available_years,
        unlinked_count=unlinked_count,
    )

@main_bp.post("/plans/<int:plan_id>/bulk_add_v2", endpoint="bulk_add_courses_v2")
@login_required
def bulk_add_courses_v2(plan_id: int):
    """
    Bulk add catalog courses into plan (PlanCourse), with safe defaults:
    - optional excluded by default
    - optional included only if checkbox checked
    - skip courses already in the plan

    Conflict-proof: unique URL + endpoint name.
    """
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    selected_degree = (request.form.get("degree") or "CS").strip()
    year_filter = (request.form.get("year") or "").strip()
    include_optional = bool(request.form.get("include_optional"))

    catalog = load_catalog_for_plan(plan.id)
    meta_courses = catalog.get("courses") or {}
    using_plan_seed = has_plan_catalog_seed(plan.id)

    existing_plan_courses = PlanCourse.query.filter_by(plan_id=plan.id).all()
    existing_codes: set[str] = set()
    existing_catalog_ids = set()
    for pc in existing_plan_courses:
        if pc.catalog_course is not None:
            existing_catalog_ids.add(pc.catalog_course_id)
            existing_codes.add(str(pc.catalog_course.code).strip())
        elif pc.legacy_course is not None:
            existing_codes.add(str(pc.legacy_course.code).strip())

    all_catalog = CatalogCourse.query.order_by(CatalogCourse.code.asc()).all() if not using_plan_seed else []

    to_add: list[PlanCourse] = []
    skipped_existing = 0
    skipped_optional = 0
    skipped_degree = 0
    skipped_year = 0

    def _credits_to_int(v) -> int:
        try:
            if v is None:
                return 0
            return int(float(v))
        except Exception:
            return 0

    if using_plan_seed:
        # Bulk add from plan seed catalog file (creates legacy/manual plan courses)
        for code, m in (meta_courses.items() if isinstance(meta_courses, dict) else []):
            code = str(code).strip()
            if not code:
                continue
            if not isinstance(m, dict):
                m = {}

            # Degree filter (metadata tags if present; default CS)
            tags = m.get("degree_tags") or ["CS"]
            if selected_degree and selected_degree not in tags:
                skipped_degree += 1
                continue

            # Year filter (metadata)
            if year_filter:
                if str(m.get("academic_year") or "").strip() != year_filter:
                    skipped_year += 1
                    continue
            # Optional courses are excluded unless explicitly included
            if is_optional_by_code(code) and (not include_optional):
                skipped_optional += 1
                continue
            # Skip duplicates already in plan (by code)
            if code in existing_codes:
                skipped_existing += 1
                continue

            legacy = Course(
                degree_plan_id=plan.id,
                code=code,
                name=(m.get("name") or code),
                credits=_credits_to_int(m.get("credits")),
            )
            db.session.add(legacy)
            db.session.flush()

            to_add.append(
                PlanCourse(
                    plan_id=plan.id,
                    catalog_course_id=None,
                    legacy_course_id=legacy.id,
                )
            )
    else:
        # Bulk add from global DB catalog (existing behavior)
        for c in all_catalog:
            code = str(c.code)
            m = meta_courses.get(code, {})
            if not isinstance(m, dict):
                m = {}
            # Degree filter (metadata tags)
            tags = m.get("degree_tags") or ["CS"]
            if selected_degree and selected_degree not in tags:
                skipped_degree += 1
                continue

            # Year filter (metadata)
            if year_filter:
                if str(m.get("academic_year") or "").strip() != year_filter:
                    skipped_year += 1
                    continue

            # Optional courses are excluded unless explicitly included
            if is_optional_by_code(code) and (not include_optional):
                skipped_optional += 1
                continue

            # Skip duplicates already in plan
            if c.id in existing_catalog_ids:
                skipped_existing += 1
                continue

            to_add.append(
                PlanCourse(
                    plan_id=plan.id,
                    catalog_course_id=c.id,
                    legacy_course_id=None,
                )
            )
            
    if to_add:
        db.session.add_all(to_add)
        db.session.commit()

        flash(f"Bulk import added {len(to_add)} courses.", "success")

        # Show skipped breakdown ONLY when something was added
        total_skipped = skipped_existing + skipped_optional + skipped_degree + skipped_year
        if total_skipped > 0:
            total_skipped = (
                skipped_existing +
                skipped_optional +
                skipped_degree +
                skipped_year
            )

        if total_skipped > 0:
            flash(
                "Skipped — "
                f"already in plan: {skipped_existing}, "
                f"optional excluded: {skipped_optional}, "
                f"degree filter: {skipped_degree}, "
                f"year filter: {skipped_year}.",
                "secondary",
            )

    else:
        flash(
            "Bulk import: nothing to add. Try loosening filters "
            "(e.g., set year to “All years” or enable optional courses).",
            "info",
        )

    return redirect(url_for("main.view_plan", plan_id=plan.id, degree=selected_degree))


@main_bp.post("/plans/<int:plan_id>/bulk_add")
@login_required
def bulk_add_courses(plan_id: int):
    # Backward-compat endpoint: delegate to v2 so we have ONE source of truth.
    return bulk_add_courses_v2(plan_id)


@main_bp.route("/plans/<int:plan_id>/settings", methods=["GET", "POST"])
@login_required
def plan_settings(plan_id: int):
    # 1) Make sure the plan belongs to the current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # 2) Get or create the constraint row for this plan
    pc = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()
    if pc is None:
        pc = PlanConstraint(
            degree_plan_id=plan.id,
            total_semesters=9,  # default
            max_credits_per_semester=None,
            enforce_prereqs=True,
            enforce_credit_limits=True,
            minimize_last_semester=True,
            years=3,                 # optional, in the plan 
            semesters_per_year=3,    # optional, in the plan 
        )
        db.session.add(pc)
        db.session.commit()

    if request.method == "POST":
        # ---- plan structure (optional): labels only ----
        years_raw = (request.form.get("years") or "").strip()
        semesters_per_year_raw = (request.form.get("semesters_per_year") or "").strip()

        years_val = None
        semesters_per_year_val = None

        if years_raw != "" or semesters_per_year_raw != "":
            # If one is provided, require both (keeps it consistent)
            if not years_raw or not semesters_per_year_raw:
                flash("Plan structure requires both Years and Semesters per year (or leave both blank).", "error")
                return redirect(url_for("main.plan_settings", plan_id=plan.id))

            try:
                years_val = int(years_raw)
                semesters_per_year_val = int(semesters_per_year_raw)
            except ValueError:
                flash("Years and semesters per year must be whole numbers.", "error")
                return redirect(url_for("main.plan_settings", plan_id=plan.id))

            if years_val < 1 or years_val > 10:
                flash("Years must be between 1 and 10.", "error")
                return redirect(url_for("main.plan_settings", plan_id=plan.id))

            if semesters_per_year_val < 1 or semesters_per_year_val > 6:
                flash("Semesters per year must be between 1 and 6.", "error")
                return redirect(url_for("main.plan_settings", plan_id=plan.id))

        # ---- total semesters (solver bound; always explicit) ----
        # If plan structure is provided, derive total semesters.
        if years_val is not None and semesters_per_year_val is not None:
            total_semesters_val = years_val * semesters_per_year_val
        else:
            total_semesters_raw = (request.form.get("total_semesters") or "").strip()
            try:
                total_semesters_val = int(total_semesters_raw)
            except ValueError:
                flash("Total semesters must be a whole number.", "error")
                return redirect(url_for("main.plan_settings", plan_id=plan.id))

        # Validate total semesters regardless of source
        if total_semesters_val < 1 or total_semesters_val > 20:
            flash("Total semesters must be between 1 and 20.", "error")
            return redirect(url_for("main.plan_settings", plan_id=plan.id))

        # ---- max credits per semester (blank means no limit) ----
        max_credits_raw = (request.form.get("max_credits_per_semester") or "").strip()
        if max_credits_raw == "":
            max_credits_val = None
        else:
            try:
                max_credits_val = int(max_credits_raw)
            except ValueError:
                flash("Max credits per semester must be a whole number (or left blank).", "error")
                return redirect(url_for("main.plan_settings", plan_id=plan.id))

            if max_credits_val < 1 or max_credits_val > 60:
                flash("Max credits per semester must be between 1 and 60.", "error")
                return redirect(url_for("main.plan_settings", plan_id=plan.id))

        # ---- solver flags ----
        # Checkbox inputs only appear in request.form when checked.
        enforce_prereqs_val = ("enforce_prereqs" in request.form)
        enforce_credit_limits_val = ("enforce_credit_limits" in request.form)
        minimize_last_semester_val = ("minimize_last_semester" in request.form)

        # persist
        pc.years = years_val
        pc.semesters_per_year = semesters_per_year_val
        pc.total_semesters = total_semesters_val
        pc.max_credits_per_semester = max_credits_val
        pc.enforce_prereqs = enforce_prereqs_val
        pc.enforce_credit_limits = enforce_credit_limits_val
        pc.minimize_last_semester = minimize_last_semester_val

        db.session.commit()

        flash("Plan settings updated.", "success")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # GET: render the settings page
    return render_template(
        "plan_settings.html",
        plan=plan,
        constraints=pc,
    )

@main_bp.post("/plans/<int:plan_id>/delete")
@login_required
def delete_plan(plan_id: int):
    plan = DegreePlan.query.get_or_404(plan_id)
    if plan.user_id != current_user.id:
        abort(403)

    has_courses = Course.query.filter_by(degree_plan_id=plan.id).first() is not None
    has_prereqs = Prerequisite.query.filter_by(degree_plan_id=plan.id).first() is not None

    # Do NOT block on PlanConstraint (settings/constraints). This row is typically auto-created
    # per plan and should be cleaned up automatically during plan deletion.
    if has_courses or has_prereqs:
        flash("Delete blocked: delete all courses first (and any prerequisites).", "warning")
        return redirect(url_for("main.view_plan", plan_id=plan.id))
    
    # Cleanup plan-scoped settings row(s) so plan deletion isn't blocked by auto-created metadata.
    PlanConstraint.query.filter_by(degree_plan_id=plan.id).delete()
    
    db.session.delete(plan)
    db.session.commit()
    flash("Plan deleted.", "success")
    return redirect(url_for("main.dashboard"))

