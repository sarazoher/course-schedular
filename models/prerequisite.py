from extensions import db


# For this plan, course X requires course Y before it
class Prerequisite(db.Model):
    __tablename__ = "prerequisite"

    __table_args__ = (
        # Prevent duplicate prereq edges within a plan
        db.UniqueConstraint(
            "degree_plan_id",
            "course_id",
            "prereq_course_id",
            name="uq_prereq_plan_course_prereq",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    degree_plan_id = db.Column(
        db.Integer,
        db.ForeignKey("degree_plan.id", ondelete="CASCADE"),
        nullable=False,
    )

    # the course that HAS the prerequisite (X)
    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id", ondelete="CASCADE"),
        nullable=False,
    )

    # the prerequisite course (Y)
    prereq_course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id", ondelete="CASCADE"),
        nullable=False,
    )

    degree_plan = db.relationship("DegreePlan", back_populates="prerequisites", lazy=True)

    course = db.relationship(
        "Course",
        foreign_keys=[course_id],
        back_populates="prereq_edges",
        lazy=True,
    )

    prereq_course = db.relationship(
        "Course",
        foreign_keys=[prereq_course_id],
        back_populates="prereq_for",
        lazy=True,
    )

    def __repr__(self) -> str:
        return f"<Prereq {self.prereq_course_id} -> {self.course_id}>"
