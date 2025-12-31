from flask import render_template, redirect, url_for, request, abort, flash
from flask_login import current_user, login_required

from . import main_bp
from models.course import Course
from models.catalog_course import CatalogCourse
from models.plan_course import PlanCourse
from models.degree_plan import DegreePlan
from models.plan_constraint import PlanConstraint
from models.prerequisite import Prerequisite
from models.plan_solution import PlanSolution
from services.catalog_meta import load_catalog_meta
from utils.optional_courses import get_optional_course_codes, is_optional_by_code
from extensions import db


@main_bp.route("/")
def home():
    # uses templates/home.html
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
    # Plan course list now comes from PlanCourse (backed by CatalogCourse)
    plan_courses = (
        PlanCourse.query
        .filter_by(plan_id=plan.id)
        .join(CatalogCourse, PlanCourse.catalog_course_id == CatalogCourse.id)
        .order_by(CatalogCourse.code.asc())
        .all()
    )

    unlinked_count = sum(1 for pc in plan_courses if not pc.legacy_course_id)

    constraints = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()

    latest_solution = (
        PlanSolution.query
        .filter_by(plan_id=plan_id)
        .order_by(PlanSolution.created_at.desc())
        .first()
        )
    
    # ---- load sidecar metadata + degree filter ----
    selected_degree = (request.args.get("degree") or "CS").strip()

    meta = load_catalog_meta()
    meta_courses = meta.get("courses") or {}

    optional_codes = get_optional_course_codes()

    degrees = meta.get("degrees") or {"CS": {"label": "Computer Science", "active": True}}

    # read-only dropdown from DB catalog (filtered by degree)
    all_catalog_courses = CatalogCourse.query.order_by(CatalogCourse.code.asc()).all()

    catalog_courses = []
    for c in all_catalog_courses:
        m = meta_courses.get(str(c.code), {})
        tags = m.get("degree_tags") or ["CS"]
        if selected_degree and selected_degree not in tags:
            continue
        catalog_courses.append(c)

    # Years dropdown helper (based on filtered metadata for selected degree)
    years_set = set()
    for c in catalog_courses:
        m = meta_courses.get(str(c.code), {}) if isinstance(meta_courses.get(str(c.code), {}), dict) else {}
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
    mandatory_only = bool(request.form.get("mandatory_only"))
    include_optional = bool(request.form.get("include_optional"))

    meta = load_catalog_meta()
    meta_courses = meta.get("courses") or {}

    existing_catalog_ids = {
        pc.catalog_course_id
        for pc in PlanCourse.query.filter_by(plan_id=plan.id).all()
    }

    all_catalog = CatalogCourse.query.order_by(CatalogCourse.code.asc()).all()

    to_add: list[PlanCourse] = []
    skipped_existing = 0
    skipped_optional = 0
    skipped_degree = 0
    skipped_year = 0

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
            total_semesters=6,  # default
            max_credits_per_semester=None,
            enforce_prereqs=True,
            enforce_credit_limits=True,
            minimize_last_semester=True,
            years=None,                 # optional, in the plan 
            semesters_per_year=None,    # optional, in the plan 
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
    has_constraints = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first() is not None

    if has_courses or has_prereqs or has_constraints:
        flash("Delete blocked: delete all courses first (and any prerequisites/settings).", "warning")
        return redirect(url_for("main.view_plan", plan_id=plan.id))
    db.session.delete(plan)
    db.session.commit()
    flash("Plan deleted.", "success")
    return redirect(url_for("main.dashboard"))

