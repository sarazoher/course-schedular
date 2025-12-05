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

offerings_bp = Blueprint("offerings", __name__)


@offerings_bp.route("/plans/<int:plan_id>/courses/<int:course_id>/offerings", methods=["GET", "POST"])
@login_required
def edit_offerings(plan_id, course_id):
    plan = DegreePlan.query.filter_by(id=plan_id, user_id=current_user.id).first()
    if not plan:
        abort(404)

    course = Course.query.filter_by(id=course_id, degree_plan_id=plan.id).first()
    if not course:
        abort(404)

    # Determine total semesters for options
    pc = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()
    total_semesters = pc.total_semesters if pc else 6

    if request.method == "POST":
        selected = request.form.getlist("semesters")  # ["1", "3", "4"]
        selected = [int(s) for s in selected]

        # Clear existing offerings
        CourseOffering.query.filter_by(course_id=course.id).delete()

        # Re-add offerings
        for sem in selected:
            db.session.add(CourseOffering(course_id=course.id, semester_number=sem))

        db.session.commit()
        flash("Offerings updated.", "success")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # For GET — show which semesters are currently allowed
    existing = {o.semester_number for o in course.offerings}

    return render_template(
        "edit_offerings.html",
        plan=plan,
        course=course,
        total_semesters=total_semesters,
        selected_semesters=existing,
    )
