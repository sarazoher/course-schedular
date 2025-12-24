from extensions import db

class PlanCourse(db.Model):
    __tablename__ = "plan_course"

    id = db.Column(db.Integer, primary_key=True)

    # Ownership
    plan_id = db.Column(
        db.Integer,
        db.ForeignKey("degree_plan.id", ondelete="CASCADE"),
        nullable=False,
    )

    catalog_course_id = db.Column(
        db.Integer,
        db.ForeignKey("catalog_courses.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Plan-specific state
    status = db.Column(db.String(32), default="planned", nullable=False)

    # Relationships
    plan = db.relationship("DegreePlan", backref=db.backref(
        "plan_courses", cascade="all, delete-orphan"
    ))

    catalog_course = db.relationship("CatalogCourse")

    def __repr__(self) -> str:
        return f"<PlanCourse plan={self.plan_id} catalog={self.catalog_course_id}>"
