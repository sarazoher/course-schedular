from flask import render_template, redirect, url_for, request, abort, flash, current_app
from flask_login import current_user, login_required
from pathlib import Path
import json

from . import main_bp
from models.plan_course import PlanCourse
from models.degree_plan import DegreePlan
from models.plan_constraint import PlanConstraint
from utils.course_catalog import _load_xlsx_catalog


@main_bp.route("/plans/<int:plan_id>/catalog_upload", methods=["GET", "POST"])
@login_required
def upload_plan_catalog(plan_id: int):
    """
    Plan-local catalog seed upload (replacement model).

    - Does NOT modify global catalog tables.
    - Reads supported Excel format (same as existing catalog import helpers).
    - Persists a plan seed catalog file under instance/uploads/:
        plan_<id>_catalog_meta.json
      This file REPLACES the global catalog for this plan (no merging).
    - Upload does NOT add courses into the plan. Courses are added via bulk add / manual add.
    - Re-upload requires explicit confirmation and replaces the previous plan seed.
    """
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    upload_dir = Path(current_app.instance_path) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    meta_path = upload_dir / f"plan_{plan.id}_catalog_meta.json"
    raw_path = upload_dir / f"plan_{plan.id}_catalog_raw.xlsx"

    if request.method == "POST":
        # If an existing seed exists, require explicit confirmation to replace it.
        if meta_path.exists():
            confirm = (request.form.get("confirm_replace") or "").strip()
            if confirm not in ("1", "true", "on", "yes"):
                flash(
                    "This plan already has an uploaded catalog seed. "
                    "Confirm replacement to overwrite it.",
                    "error",
                )
                return redirect(url_for("main.upload_plan_catalog", plan_id=plan.id))

        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Please choose an Excel file to upload.", "error")
            return redirect(url_for("main.upload_plan_catalog", plan_id=plan.id))

        filename = file.filename.lower()
        if not (filename.endswith(".xlsx") or filename.endswith(".xls")):
            flash("Only .xlsx / .xls files are supported.", "error")
            return redirect(url_for("main.upload_plan_catalog", plan_id=plan.id))

        # Keep a copy of the raw upload for inspection/debugging (WRITE IT!)
        try:
            file.stream.seek(0)
            raw_path.write_bytes(file.read())
        except Exception as e:
            flash(f"Could not save uploaded file: {e}", "error")
            return redirect(url_for("main.upload_plan_catalog", plan_id=plan.id))

        # Parse with the same helper used for global catalog extraction
        try:
            items = _load_xlsx_catalog(raw_path)
        except Exception as e:
            flash(f"Could not read Excel: {e}", "error")
            return redirect(url_for("main.upload_plan_catalog", plan_id=plan.id))

        # Build a plan seed catalog (replacement). Shape:
        # {"version": 1, "courses": { "<code>": { ...fields... } } }
        seed_courses: dict[str, dict] = {}

        for c in items:
            code = str(getattr(c, "code", "") or "").strip()
            if not code:
                continue

            data: dict[str, object] = {}

            name = (getattr(c, "name", None) or "").strip()
            if name:
                data["name"] = name

            credits_val = getattr(c, "credits", None)
            if credits_val is not None and str(credits_val).strip() != "":
                data["credits"] = credits_val

            study_year = getattr(c, "study_year", None)
            if study_year is not None:
                data["academic_year"] = study_year

            hours = getattr(c, "weekly_hours", None)
            if hours is not None:
                data["weekly_hours"] = hours

            lecturer = getattr(c, "instructor_name", None)
            if lecturer:
                data["lecturer"] = lecturer

            prereq_text = getattr(c, "prereq_text", None)
            if prereq_text:
                data["prereq_text"] = prereq_text

            coreq_text = getattr(c, "coreq_text", None)
            if coreq_text:
                data["coreq_text"] = coreq_text

            lesson_type = getattr(c, "course_type", None)
            if lesson_type:
                data["lesson_type"] = lesson_type

            seed_courses[code] = data

        if not seed_courses:
            flash(
                "Upload processed, but no course rows were found in the Excel file.",
                "error",
            )
            return redirect(url_for("main.upload_plan_catalog", plan_id=plan.id))

        # Persist plan seed catalog (replacement)
        payload = {"version": 1, "courses": seed_courses}
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        flash(
            f"Plan catalog seed updated (plan-local): {len(seed_courses)} course(s) available in dropdown/bulk add.",
            "success",
        )
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # GET: never tries to read/parse raw_path
    return render_template(
        "plan_catalog_upload.html",
        plan=plan,
        existing_seed=meta_path.exists(),
    )


@main_bp.route("/plans/<int:plan_id>/manual-schedule", methods=["GET", "POST"])
@login_required
def manual_schedule(plan_id: int):
    """
    Plan-level manual placement of courses into semesters.

    - Stored as a small JSON file under instance/uploads/ (per plan).
    - Does NOT call the solver or mutate solver inputs.
    - Intended for a downstream Stage B timetabling step to consume.
    """
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    constraints = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()
    if constraints is None or not constraints.total_semesters:
        flash("Set total semesters in Plan settings before using manual placement.", "error")
        return redirect(url_for("main.plan_settings", plan_id=plan.id))

    total_semesters = int(constraints.total_semesters)

    # PlanCourse rows may be catalog-linked OR legacy-only.
    # We sort by visible code for a stable UI.    
    plan_courses = (
        PlanCourse.query
        .filter_by(plan_id=plan.id)
        .all()
    )
    plan_courses.sort(
        key=lambda pc: str(
            pc.catalog_course.code if pc.catalog_course else (pc.legacy_course.code if pc.legacy_course else "")
        )
    )

    upload_dir = Path(current_app.instance_path) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    manual_path = upload_dir / f"plan_{plan.id}_manual_schedule.json"

    # Load existing mapping if present
    existing_map: dict[str, int] = {}
    if manual_path.exists():
        try:
            payload = json.loads(manual_path.read_text(encoding="utf-8")) or {}
            existing_map = {str(k): int(v) for k, v in (payload.get("by_code") or {}).items()}
        except Exception:
            existing_map = {}

    if request.method == "POST":
        by_code: dict[str, int] = {}

        for pc in plan_courses:
            if pc.catalog_course is not None:
                code = str(pc.catalog_course.code).strip()
            elif pc.legacy_course is not None:
                code = str(pc.legacy_course.code).strip()
            else:
                continue
            field_name = f"sem_{pc.id}"
            raw = (request.form.get(field_name) or "").strip()
            if not raw:
                continue
            try:
                sem = int(raw)
            except ValueError:
                continue
            if sem < 1 or sem > total_semesters:
                continue
            by_code[code] = sem

        payload = {
            "plan_id": plan.id,
            "total_semesters": total_semesters,
            "by_code": by_code,
        }
        manual_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        flash(
            f"Saved manual placement for {len(by_code)} course(s). "
            "Stage B can now consume this mapping without re-running the solver.",
            "success",
        )
        return redirect(url_for("main.manual_schedule", plan_id=plan.id))

    return render_template(
        "manual_schedule.html",
        plan=plan,
        plan_courses=plan_courses,
        total_semesters=total_semesters,
        existing_map=existing_map,
    )
