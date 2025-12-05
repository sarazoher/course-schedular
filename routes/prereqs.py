from flask import (
    Blueprint,
    render_template,
    redirect, url_for,
    request,
    flash,
    abort,
    )
from flask_login import login_required, current_user

from extensions import db
from models.degree_plan import DegreePlan
from models.course import Course
from models.prerequisite import Prerequisite

prereqs_bp = Blueprint("prereqs", __name__)


@prereqs_bp.route("/plans/<int:plan_id>/courses/<int:course_id>/prereqs", methods=["GET", "POST"])
@login_required
def edit_prereqs(plan_id, course_id):
    plan = DegreePlan.query.filter_by(id=plan_id, user_id=current_user.id).first()
    if not plan:
        abort(404)

    course = Course.query.filter_by(id=course_id, degree_plan_id=plan.id).first()
    if not course:
        abort(404)

    # All other courses from this plan
    all_courses = Course.query.filter_by(degree_plan_id=plan.id).all()

    if request.method == "POST":
        chosen = request.form.getlist("prereqs")  # ["805", "806", "807"] (course_ids)
        chosen_ids = {int(cid) for cid in chosen}

        # Remove old prerequisites
        Prerequisite.query.filter_by(course_id=course.id).delete()

        # Add new
        for pid in chosen_ids:
            db.session.add(Prerequisite(course_id=course.id, prereq_course_id=pid))

        db.session.commit()
        flash("Prerequisites updated.", "success")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # Existing prerequisites
    existing = {p.prereq_course_id for p in course.prereqs}

    return render_template(
        "edit_prereqs.html",
        plan=plan,
        course=course,
        all_courses=all_courses,
        existing_prereqs=existing,
    )
