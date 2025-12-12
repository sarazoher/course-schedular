from flask import render_template, redirect, url_for, request, abort, flash
from flask_login import login_required, current_user


from . import main_bp
from models.course import Course
from models.degree_plan import DegreePlan
from models.plan_constraint import PlanConstraint
from extensions import db

from services.solver import build_inputs_from_plan, build_model
from pulp import PULP_CBC_CMD, LpStatus

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
    courses = Course.query.filter_by(degree_plan_id=plan.id).order_by(Course.id).all()

    return render_template(
        "plan_detail.html", 
        plan = plan,
        courses = courses,
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
        )
        db.session.add(pc)
        db.session.commit()

    if request.method == "POST":
        total_semesters_raw = (request.form.get("total_semesters") or "").strip()

        try:
            total_semesters_val = int(total_semesters_raw)
        except ValueError:
            flash("Total semesters must be a whole number.", "error")
            return redirect(url_for("main.plan_settings", plan_id=plan.id))

        if total_semesters_val < 1 or total_semesters_val > 20:
            flash("Total semesters must be between 1 and 20.", "error")
            return redirect(url_for("main.plan_settings", plan_id=plan.id))

        pc.total_semesters = total_semesters_val
        db.session.commit()

        flash("Plan settings updated.", "success")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # GET: render the settings page
    return render_template(
        "plan_settings.html",
        plan=plan,
        constraints=pc,
    )
