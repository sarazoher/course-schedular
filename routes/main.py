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
from models.course_offering import CourseOffering
from models.plan_constraint import PlanConstraint
from models.prerequisite import Prerequisite

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


@main_bp.route("/plans/<int:plan_id>/courses/add", methods=["POST"])
@login_required
def add_course(plan_id: int):
    # 1) Ensure plan belongs to current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # 2) Read and normalize form fields
    code = (request.form.get("code") or "").strip()
    name = (request.form.get("name") or "").strip()
    credits_raw = (request.form.get("credits") or "").strip()
    difficulty_raw = (request.form.get("difficulty") or "").strip()

    if not code or not name:
        flash("Course code and name are required.", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # 3) Validate credits
    # must be an int or .5 increments
    try:
        credits_val = float(credits_raw)
    except ValueError:
        flash("Credits must be a number.", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))
    
    # no negative value, and must be in steps of 0.5 
    # we allow zero, for non-credit requirement courses 
    if credits_val < 0 or (credits_val * 2).is_integer:
        flash("Credits must be an integer OR end with .5", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # 4) Validate difficulty (optional)
    difficulty_val = None
    if difficulty_raw:
        try:
            difficulty_val = int(difficulty_raw)
        except ValueError:
            flash("Difficulty must be a number.", "error")
            return redirect(url_for("main.view_plan", plan_id=plan.id))

    # 5) Duplicate checks inside this plan
    existing_code = Course.query.filter_by(
        degree_plan_id=plan.id,
        code=code,
    ).first()
    if existing_code:
        flash("A course with that code already exists in this plan.", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    existing_name = Course.query.filter_by(
        degree_plan_id=plan.id,
        name=name,
    ).first()
    if existing_name:
        flash("A course with that name already exists in this plan.", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # 6) Create and save the course
    course = Course(
        degree_plan_id=plan.id,
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
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    # GET: show the edit form
    return render_template("edit_course.html", plan=plan, course=course)

@main_bp.route(
    "/plans/<int:plan_id>/courses/<int:course_id>/delete",
    methods=["POST"],
)
@login_required
def delete_course(plan_id: int, course_id: int):
    # 1) Make sure the plan belongs to the current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # 2) Find the course inside this plan
    course = Course.query.filter_by(
        id=course_id,
        degree_plan_id=plan.id,
    ).first()
    if course is None:
        abort(404)

    # 3) Delete all related offerings + prereqs pointing to this course
    CourseOffering.query.filter_by(course_id=course.id).delete()
    Prerequisite.query.filter_by(
        degree_plan_id=plan.id,
        course_id=course.id,
    ).delete()
    Prerequisite.query.filter_by(
        degree_plan_id=plan.id,
        prereq_course_id=course.id,
    ).delete()

    # 4) Delete the course itself
    db.session.delete(course)
    db.session.commit()

    flash("Course deleted.", "success")
    return redirect(url_for("main.view_plan", plan_id=plan.id))


@main_bp.route("/plans/<int:plan_id>/courses/<int:course_id>/offerings", methods=["GET", "POST"])
@login_required
def edit_offerings(plan_id: int, course_id: int):
    # 1) Make sure plan belongs to current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # 2) Make sure course belongs to this plan
    course = Course.query.filter_by(
        id=course_id,
        degree_plan_id=plan.id,
    ).first()
    if course is None:
        abort(404)

    # POST: update offerings based on checkboxes from the tab form
    if request.method == "POST":
        selected_raw = request.form.getlist("semesters")  # list of "1", "2", ...
        try:
            selected_semesters = sorted({int(s) for s in selected_raw})
        except ValueError:
            selected_semesters = []

        # Clear existing offerings for this course
        CourseOffering.query.filter_by(course_id=course.id).delete()

        # Insert the new ones
        for s in selected_semesters:
            db.session.add(
                CourseOffering(
                    course_id=course.id,
                    semester_number=s,
                )
            )

        db.session.commit()
        flash("Offerings updated.", "success")

        # Back to the unified course page with tabs
        return redirect(
            url_for("main.course_detail", plan_id=plan.id, course_id=course.id)
        )

    # GET: we don't show a separate offerings page anymore,
    # just redirect to the course detail (Offerings tab is there)
    return redirect(
        url_for("main.course_detail", plan_id=plan.id, course_id=course.id)
    )
    
    # GET: collect currently selected semesters
    # assumes a relationship Course.offerings exists
    existing_semesters = {o.semester_number for o in course.offerings}

    return render_template(
        "edit_offerings.html",
        plan=plan,
        course=course,
        total_semesters=total_semesters,
        selected_semesters=existing_semesters,
    )
""" 
In function above, every branch here either
        →   aborts with 404
        →   redirects
        → OR renders a template 
    to try and avoid Flask view return error 
""" 
@main_bp.route("/plans/<int:plan_id>/course/<int:course_id>")
@login_required
def course_detail(plan_id: int, course_id: int):
    # 1) Make sure the plan belongs to this user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # 2) Make sure the course belongs to this plan
    course = Course.query.filter_by(
        id=course_id,
        degree_plan_id=plan.id,
    ).first()
    if course is None:
        abort(404)

    # 3) How many semesters? (from PlanConstraint, fallback to 6)
    pc = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()
    if pc and pc.total_semesters:
        total_semesters = pc.total_semesters
    else:
        total_semesters = 6

    # 4) Existing offerings for this course → used to pre-check boxes
    selected_semesters = {o.semester_number for o in course.offerings}

    # 5) Prerequisites for this course
    # incoming: "requires these courses"
    incoming_prereqs = Prerequisite.query.filter_by(
        degree_plan_id=plan.id,
        course_id=course.id,
    ).all()

    # outgoing: "is a prerequisite for these courses"
    outgoing_prereqs = Prerequisite.query.filter_by(
        degree_plan_id=plan.id,
        prereq_course_id=course.id,
    ).all()

    all_courses = Course.query.filter_by(
        degree_plan_id=plan.id
    ).order_by(Course.code).all()
    available_prereq_courses = [c for c in all_courses if c.id != course.id]

    return render_template(
        "course_detail.html",
        plan=plan,
        course=course,
        total_semesters=total_semesters,
        selected_semesters=selected_semesters,
        incoming_prereqs=incoming_prereqs,
        outgoing_prereqs=outgoing_prereqs,
        available_prereq_courses=available_prereq_courses,
    )

@main_bp.route("/plans/<int:plan_id>/course/<int:course_id>/prereqs/add", methods=["POST"])
@login_required
def add_prereq(plan_id: int, course_id: int):
    # Make sure the plan belongs to the current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # Make sure the "target" course belongs to this plan
    course = Course.query.filter_by(
        id=course_id,
        degree_plan_id=plan.id,
    ).first()
    if course is None:
        abort(404)

    prereq_id_raw = (request.form.get("prereq_course_id") or "").strip()
    if not prereq_id_raw:
        flash("Please select a prerequisite course.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    try:
        prereq_course_id = int(prereq_id_raw)
    except ValueError:
        flash("Invalid prerequisite course.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    # Can't be its own prerequisite!
    if prereq_course_id == course.id:
        flash("A course cannot be a prerequisite of itself.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    # Ensure prereq course exists in the same plan
    prereq_course = Course.query.filter_by(
        id=prereq_course_id,
        degree_plan_id=plan.id,
    ).first()
    if prereq_course is None:
        flash("Selected prerequisite course is not in this plan.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    # Avoid duplicate edges
    existing = Prerequisite.query.filter_by(
        degree_plan_id=plan.id,
        course_id=course.id,
        prereq_course_id=prereq_course.id,
    ).first()
    if existing:
        flash("This prerequisite already exists.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    # Create the new prereq edge
    edge = Prerequisite(
        degree_plan_id=plan.id,
        course_id=course.id,
        prereq_course_id=prereq_course.id,
    )
    db.session.add(edge)
    db.session.commit()

    flash("Prerequisite added.", "success")
    return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))


@main_bp.route("/plans/<int:plan_id>/course/<int:course_id>/prereqs/<int:prereq_id>/delete", methods=["POST"])
@login_required
def delete_prereq(plan_id: int, course_id: int, prereq_id: int):
    # Ensure plan belongs to current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # Ensure course belongs to this plan
    course = Course.query.filter_by(
        id=course_id,
        degree_plan_id=plan.id,
    ).first()
    if course is None:
        abort(404)

    # Find the prereq edge and ensure it belongs to this plan+course
    edge = Prerequisite.query.filter_by(
        id=prereq_id,
        degree_plan_id=plan.id,
        course_id=course.id,
    ).first()
    if edge is None:
        abort(404)

    db.session.delete(edge)
    db.session.commit()

    flash("Prerequisite removed.", "success")
    return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))
