from extensions import db

# Model does in short: for this plan, course X requires course Y before it
# 
class Prerequisite(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    degree_plan_id = db.Column(
        db.Integer,
        db.ForeignKey("degree_plan.id"),
        nullable=False,
    )

    # the course that HAS the prerequisite (X)
    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False,
    )

    # the course that IS the prerequisite (Y)
    prereq_course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False,
    )

    # relationships:
    degree_plan = db.relationship("DegreePlan", backref="prerequisites", lazy=True)

    course = db.relationship(
        "Course",
        foreign_keys=[course_id],
        backref="prereq_edges",
        lazy=True,
    )

    prereq_course = db.relationship(
        "Course",
        foreign_keys=[prereq_course_id],
        lazy=True,
    )

    def __repr__(self):
        return f"<Prereq {self.prereq_course_id} -> {self.course_id}>"