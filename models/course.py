from extensions import db


class Course(db.Model):
    __tablename__ = "course"

    __table_args__ = (
        # Prevent the same course code being added twice in the same plan
        db.UniqueConstraint("degree_plan_id", "code", name="uq_course_plan_code"),
    )

    id = db.Column(db.Integer, primary_key=True)

    degree_plan_id = db.Column(
        db.Integer,
        db.ForeignKey("degree_plan.id", ondelete="CASCADE"),
        nullable=False,
    )

    code = db.Column(db.String(9), nullable=False)

    # note: was String(9) changed to 255 because it was too small.
    name = db.Column(db.String(255), nullable=False)

    credits = db.Column(db.Integer, nullable=False)
    difficulty = db.Column(db.Integer, nullable=True)

    plan = db.relationship("DegreePlan", back_populates="courses", lazy=True)

    offerings = db.relationship(
        "CourseOffering",
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy=True,
    )

    # Prereq edges where THIS course is the dependent course (X requires Y)
    prereq_edges = db.relationship(
        "Prerequisite",
        foreign_keys="Prerequisite.course_id",
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy=True,
    )

    # Optional: edges where THIS course is used as a prereq for others
    prereq_for = db.relationship(
        "Prerequisite",
        foreign_keys="Prerequisite.prereq_course_id",
        back_populates="prereq_course",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy=True,
    )

    def __repr__(self) -> str:
        return f"<Course {self.code}>"
