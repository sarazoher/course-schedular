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
from extensions import db

from services.catalog_meta import load_catalog_meta

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
    )

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
        enforce_prereqs_val = request.form.get("enforce_prereqs") == "on"
        enforce_credit_limits_val = request.form.get("enforce_credit_limits") == "on"
        minimize_last_semester_val = request.form.get("minimize_last_semester") == "on"

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

