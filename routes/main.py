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

@main_bp.route("/plans/<int:plan_id>/courses/add", methods=["POST"])
@login_required
def add_course(plan_id: int):

    plan = DegreePlan.query.filter_by(
        id = plan_id,
        user_id= current_user.id,
    ).first()
    if plan is None:
        abort(404)

    code = request.form.get("code", "").strip()
    name = request.form.get("name", "").strip()
    credits_raw = request.form.get("credits", "").strip()
    difficulty_raw = request.form.get("difficulty", "").strip()

    if not code or not name:
        flash("course code and name are required", "errorr")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    try:
        credits_val = int(credits_raw) if credits_raw else 0
    except ValueError:
        flash("Credits must be a number", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    #try:
    #    difficulty_val = int(difficulty_raw) if difficulty_raw else None
    #except ValueError:
    #    flash("Difficulty must be a number.", "error")
    #    return redirect(url_for("main.view_plan", plan_id=plan.id))
    difficulty_val = None # temporarily ignoring difficulty 

    #make sure course codes are unique within a specific plan (no duplicates)
    exists = Course.query.filter_by(
        degree_plan_id= plan.id,
        code=code,
    ).first()
    if exists:
        flash("A course with that code already exists in this plan.", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))
    
    course = Course(
        degree_plan_id = plan.id,
        code=code,
        name=name,
        credits=credits_val,
        difficulty=difficulty_val,
    )
    db.session.add(course)
    db.session.commit()

    flash("Course added.", "success")
    return redirect(url_for("main.view_plan", plan_id=plan.id))


@main_bp.route("/plans/<int:plan_id>/courses/<int:course_id>/edit", methods=["GET", "POST"])
@login_required
def edit_course(plan_id: int, course_id: int):
    # 1) Make sure the plan belongs to the current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # 2) Look up the course inside this plan
    course = Course.query.filter_by(
        id=course_id,
        degree_plan_id=plan.id,
    ).first()
    if course is None:
        abort(404)

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        name = request.form.get("name", "").strip()
        credits_raw = request.form.get("credits", "").strip()
        difficulty_raw = request.form.get("difficulty", "").strip()

        if not code or not name:
            flash("Course code and name are required.", "error")
            return redirect(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))

        # parse credits
        try:
            credits_val = int(credits_raw) if credits_raw else 0
        except ValueError:
            flash("Credits must be a number.", "error")
            return redirect(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))

        # parse difficulty (optional)
        try:
            difficulty_val = int(difficulty_raw) if difficulty_raw else None
        except ValueError:
            flash("Difficulty must be a number.", "error")
            return redirect(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))

        # ensure codes are unique within this plan (excluding this course)
        existing = Course.query.filter_by(
            degree_plan_id=plan.id,
            code=code,
        ).first()
        if existing and existing.id != course.id:
            flash("Another course with that code already exists in this plan.", "error")
            return redirect(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))

        # update course
        course.code = code
        course.name = name
        course.credits = credits_val
        course.difficulty = difficulty_val

        db.session.commit()
        flash("Course updated.", "success")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # GET: show the edit form
    return render_template("edit_course.html", plan=plan, course=course)

@main_bp.route("/plan/<int:plan_id>/courses/<int:course_id>/delete", methods=["POST"])
@login_required
def delete_course(plan_id: int, course_id: int):
    # makeing sure plan belomgs to current use
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

        #find the course inside this plan
        course = Course.query.filter_by(
            id=course_id,
            degree_plan_id=plan.id,
        ).first()
        if course is None:
            abort(404)

        # Delete and Save]
        db.session.delete(course)
        db.session.commit()

        flash("Course deleted.", "success")
        return redirect(url_for("main.view_plan", plan_id=plan.id))


