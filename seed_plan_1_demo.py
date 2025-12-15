from app import app 
from extensions import db
from models.course import Course
from models.course_offering import CourseOffering
from models.prerequisite import Prerequisite
from models.degree_plan import DegreePlan
from models.plan_constraint import PlanConstraint

PLAN_ID = 1 # we're using plan testing with /test-solve/1

def main():
    with app.app_context():
        plan = DegreePlan.query.get(PLAN_ID)
        if plan is None:
            print(f"NO DegreePlan id={plan.id}. Create one via UI first")
            return
        
        print(f"Using DegreePlan id={plan.id}, name={plan.name!r}")

        Prerequisite.query.filter_by(degree_plan_id=plan.id).delete()
        CourseOffering.query.filter(
            CourseOffering.course_id.in_(
                db.session.query(Course.id).filter_by(degree_plan_id=plan.id)
            )
        ).delete(synchronize_session=False)
        Course.query.filter_by(degree_plan_id=plan.id).delete()
        PlanConstraint.query.filter_by(degree_plan_id=plan.id).delete()
        db.session.commit()

# ----------------------------------------------------------------------------------------------------------------
#   CREATE COURSE - details: ID in db, add CODE, NAME, credits, difficulty (optional in general)
# ----------------------------------------------------------------------------------------------------------------
        
        
        c101 = Course(
            degree_plan_id=plan.id,
            code="CS101",
            name="IntroCS",
            credits=3,
            difficulty=1,
        )
        c102 = Course(
            degree_plan_id=plan.id,
            code="CS102",
            name="DataStr",
            credits=3,
            difficulty=2,
        )
        c103 = Course(
            degree_plan_id=plan.id,
            code="CS103",
            name="Algo",
            credits=3,
            difficulty=3,
        )
        c201 = Course(
            degree_plan_id=plan.id,
            code="CS201",
            name="AdvCS",
            credits=3,
            difficulty=3,
        )

        db.session.add_all([c101, c102, c103, c201])
        db.session.flush()  # get IDs for offerings/prereqs



# ----------------------------------------------------------------------------------------------------------------
#   OFFERINGS - which semester a course can be taken (based on total_semesters stated below in PlanConstraints)
# ----------------------------------------------------------------------------------------------------------------

        offerings = [
            # CS101 in semesters 1,2
            CourseOffering(course_id=c101.id, semester_number=1),
            CourseOffering(course_id=c101.id, semester_number=2),

            # CS102 in semesters 1,2,3
            CourseOffering(course_id=c102.id, semester_number=1),
            CourseOffering(course_id=c102.id, semester_number=2),
            CourseOffering(course_id=c102.id, semester_number=3),

            # CS103 in semesters 2,3
            CourseOffering(course_id=c103.id, semester_number=2),
            CourseOffering(course_id=c103.id, semester_number=3),

            # CS201 in semesters 2,3
            CourseOffering(course_id=c201.id, semester_number=2),
            CourseOffering(course_id=c201.id, semester_number=3),
        ]
        db.session.add_all(offerings)



# ----------------------------------------------------------------------------------------------------------------
#   PREREQS - course B after A, visually A ---➔ B
# ----------------------------------------------------------------------------------------------------------------


        prereqs = [
            # CS102 after CS101
            Prerequisite(
                degree_plan_id=plan.id,
                course_id=c102.id,
                prereq_course_id=c101.id,
            ),
            # CS103 after CS102
            Prerequisite(
                degree_plan_id=plan.id,
                course_id=c103.id,
                prereq_course_id=c102.id,
            ),
            # CS201 after CS101
            Prerequisite(
                degree_plan_id=plan.id,
                course_id=c201.id,
                prereq_course_id=c101.id,
            ),
        ]
        db.session.add_all(prereqs)

        #  global constraints for this plan 
        constraints = PlanConstraint(
            degree_plan_id=plan.id,
            min_credits_per_semester=None,
            max_credits_per_semester=6,  
            max_courses_per_semester=None,
            max_difficulty_per_semester=None,
            total_semesters=3,  # we’ll plan over 3 semesters, for simplicity
        )
        db.session.add(constraints)

        db.session.commit()
        print(" Seeded demo data for plan", plan.id)


if __name__ == "__main__":
    main()