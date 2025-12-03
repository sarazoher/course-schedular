from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    abort,
)

from flask_login import login_required, current_user
from extensions import db
from models.degree_plan import DegreePlan
from models.course import Course

from services.solver import build_inputs_from_plan, build_model
from pulp import PULP_CBC_CMD, LpStatus


main_bp = Blueprint("main", __name__)


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
        name = request.form.get("name")

        if not name:
            flash("Plan name is required.")
            return redirect(url_for("main.create_plan"))

        plan = DegreePlan(user_id=current_user.id, name=name)
        db.session.add(plan)
        db.session.commit()

        flash("Degree plan created.")
        return redirect(url_for("main.dashboard"))

    return render_template("create_plan.html")


@main_bp.route("/plans/<int:plan_id>/solve")
@login_required
def solve_plan(plan_id: int):
    """
    User-facing route:
    - checks the plan belongs to the current user
    - builds solver inputs from the DB
    - runs the MILP solver
    - renders a semester-by-semester schedule
    """
    # ensure the plan exists and belongs to the current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # Build inputs from DB
    try:
        inputs = build_inputs_from_plan(plan.id)
    except ValueError as e:
        # This is where "No courses defined for plan_id=..." will land
        flash(str(e), "error")
        return redirect(url_for("main.dashboard"))

    # Build and solve the model
    model, x = build_model(
        inputs["courses"],
        inputs["prereqs"],
        inputs["allowed_semesters"],
        inputs["credits"],
        inputs["max_credits_per_semester"],
        use_credit_limits=True,
        use_prereqs=True,
        minimize_last_semester=True,
    )

    model.solve(PULP_CBC_CMD(msg=0))
    status = LpStatus[model.status]

    # Map course_code → Course row (for names, difficulty, etc.)
    course_rows = Course.query.filter_by(degree_plan_id=plan.id).all()
    course_by_code = {c.code: c for c in course_rows}

    # Extract chosen semester per course
    assignments = []
    for c in inputs["courses"]:
        chosen_semester = None
        for s in inputs["allowed_semesters"][c]:
            var = x[c][s]
            if var.varValue is not None and var.varValue > 0.5:
                chosen_semester = s
                break

        course_obj = course_by_code.get(c)
        assignments.append(
            {
                "code": c,
                "name": course_obj.name if course_obj else c,
                "credits": inputs["credits"][c],
                "difficulty": getattr(course_obj, "difficulty", None),
                "semester": chosen_semester,
            }
        )

    # Group by semester for easier templating
    semesters = sorted(inputs["max_credits_per_semester"].keys())
    courses_by_semester = {s: [] for s in semesters}
    for a in assignments:
        if a["semester"] is not None:
            courses_by_semester[a["semester"]].append(a)

    return render_template(
        "plan_schedule.html",
        plan=plan,
        status=status,
        semesters=semesters,
        courses_by_semester=courses_by_semester,
    )