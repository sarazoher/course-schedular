from flask import render_template, redirect, url_for, request, abort, flash
from flask_login import login_required, current_user

from . import main_bp
from models.degree_plan import DegreePlan
from models.course import Course
from models.course_offering import CourseOffering
from models.prerequisite import Prerequisite
from models.plan_constraint import PlanConstraint
from extensions import db

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

    # 2) Normalize inputs
    code = (request.form.get("code") or "").strip()
    name = (request.form.get("name") or "").strip()
    credits_raw = (request.form.get("credits") or "").strip()
    difficulty_raw = (request.form.get("difficulty") or "").strip()

    if not code or not name:
        flash("Course and name are required.", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # 3) Duplicate checks (inside this plan)
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

    # 4) Credit validation
    if not credits_raw:
        flash("Credits are required.", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    try:
        credits_val = float(credits_raw)
    except ValueError:
        flash("Credits must be a number.", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    if credits_val <= 0:
        flash("Credits must be positive.", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # allow integers or .5 values: 1, 1.5, 2, 2.5, ...
    if not (credits_val * 2).is_integer():
        flash("Credits must be an integer OR end with .5", "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    credits = credits_val   # this is what we store/use below


    # 5) Difficulty (optional)
    difficulty = None
    if difficulty_raw:
        try:
            diff_val = int(difficulty_raw)
        except ValueError:
            flash("Difficulty must be a number between 1 and 5.", "error")
            return redirect(url_for("main.view_plan", plan_id=plan.id))

        if diff_val < 1 or diff_val > 5:
            flash("Difficulty must be between 1 and 5.", "error")
            return redirect(url_for("main.view_plan", plan_id=plan.id))

        difficulty = diff_val

    
    # 6) Create and save the course
    course = Course(
        degree_plan_id=plan.id,
        code=code,
        name=name,
        credits=credits,
        difficulty=difficulty,
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
        code = (request.form.get("code") or "").strip()
        name = (request.form.get("name") or "").strip()
        credits_raw = (request.form.get("credits") or "").strip()
        difficulty_raw = (request.form.get("difficulty") or "").strip()

        if not code or not name:
            flash("Course code and name are required.", "error")
            return redirect(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))

        # Credits validation
        if not credits_raw:
            flash("Credits are required.", "error")
            return render_template(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))
        
        try:
            credits_val = float(credits_raw)
        except ValueError:
            flash("Credits must be a number.", "error")
            return redirect(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))

        if credits_val <= 0:
            flash("Credit must be positive.", "error")
            return redirect(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))
        
        # 5) Difficulty (optional)
        difficulty_val = None
        if difficulty_raw:
            try:
                diff = int(difficulty_raw)
            except ValueError:
                flash("Difficulty must be a number between 1 and 5.", "error")
                return redirect(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))

            if diff < 1 or diff > 5:
                flash("Difficulty must be between 1 and 5.", "error")
                return redirect(url_for("main.edit_course", plan_id=plan.id, course_id=course.id))

            difficulty_val = diff


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

@main_bp.route("/plans/<int:plan_id>/courses/<int:course_id>/delete", methods=["POST"])
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

@main_bp.route("/plans/<int:plan_id>/courses/<int:course_id>")
@login_required
def course_detail(plan_id: int, course_id: int):
    # Plan must belong to current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # Course must belong to this plan
    course = Course.query.filter_by(
        id=course_id,
        degree_plan_id=plan.id,
    ).first()
    if course is None:
        abort(404)

    # Plan constraints → total_semesters (for offerings tab)
    constraints = PlanConstraint.query.filter_by(
        degree_plan_id=plan.id
    ).first()
    total_semesters = constraints.total_semesters if constraints and constraints.total_semesters else 6

    # Selected semesters for this course (offerings tab)
    selected_semesters = [off.semester_number for off in course.offerings]

    # Incoming prereqs: what this course REQUIRES
    incoming_prereqs = Prerequisite.query.filter_by(
        degree_plan_id=plan.id,
        course_id=course.id,
    ).all()

    # Outgoing prereqs: courses that depend on THIS course
    outgoing_prereqs = Prerequisite.query.filter_by(
        degree_plan_id=plan.id,
        prereq_course_id=course.id,
    ).all()

    # Courses you can still add as prereqs (same plan, not itself, not already a prereq)
    all_courses = (
        Course.query
        .filter_by(degree_plan_id=plan.id)
        .order_by(Course.code)
        .all()
    )
    already_prereq_ids = {edge.prereq_course_id for edge in incoming_prereqs}
    available_prereq_courses = [
        c for c in all_courses
        if c.id != course.id and c.id not in already_prereq_ids
    ]


    # Cycle-risk detection for UI: disable any candidate prereq that would create a cycle.
    # Adding an edge (candidate_prereq -> course) creates a cycle iff course can already reach candidate_prereq
    # through existing prereq edges (prereq -> dependent).
    
    edges = Prerequisite.query.filter_by(degree_plan_id=plan.id).all()
    adj = {}
    for e in edges:
        adj.setdefault(e.prereq_course_id, []).append(e.course_id)

    reachable = set()
    stack = [course.id]
    while stack:
        node = stack.pop()
        for nxt in adj.get(node, []):
            if nxt in reachable:
                continue
            reachable.add(nxt)
            stack.append(nxt)

    cycle_risk_ids = reachable


    return render_template(
        "course_detail.html",
        plan=plan,
        course=course,
        total_semesters=total_semesters,
        selected_semesters=selected_semesters,
        incoming_prereqs=incoming_prereqs,
        outgoing_prereqs=outgoing_prereqs,
        available_prereq_courses=available_prereq_courses,
        cycle_risk_ids=cycle_risk_ids,
    )

@main_bp.route("/plans/<int:plan_id>/courses/<int:course_id>/prereqs/add", methods=["POST"])
@login_required
def add_prereq(plan_id: int, course_id: int):
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    course = Course.query.filter_by(
        id=course_id,
        degree_plan_id=plan.id,
    ).first()
    if course is None:
        abort(404)

    prereq_raw = (request.form.get("prereq_course_id") or "").strip()
    if not prereq_raw:
        flash("Select a course to add as a prerequisite.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    try:
        prereq_id = int(prereq_raw)
    except ValueError:
        flash("Invalid course selected.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    if prereq_id == course.id:
        flash("A course cannot be a prerequisite of itself.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    prereq_course = Course.query.filter_by(
        id=prereq_id,
        degree_plan_id=plan.id,
    ).first()
    if prereq_course is None:
        flash("Selected course is not in this plan.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    # Avoid duplicates
    existing = Prerequisite.query.filter_by(
        degree_plan_id=plan.id,
        course_id=course.id,
        prereq_course_id=prereq_course.id,
    ).first()
    if existing:
        flash("That prerequisite already exists.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    edge = Prerequisite(
        degree_plan_id=plan.id,
        course_id=course.id,
        prereq_course_id=prereq_course.id,
    )
    db.session.add(edge)
    db.session.commit()

    flash("Prerequisite added.", "success")
    return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))


@main_bp.route("/plans/<int:plan_id>/courses/<int:course_id>/prereqs/<int:prereq_id>/delete", methods=["POST"])
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
    ).first()
    if edge is None:
        flash("Prerequisite not found.", "error")
        return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))

    db.session.delete(edge)
    db.session.commit()

    flash("Prerequisite removed.", "success")
    return redirect(url_for("main.course_detail", plan_id=plan.id, course_id=course.id))
