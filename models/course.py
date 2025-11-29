from extensions import db


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    degree_plan_id = db.Column(
        db.Integer,
        db.ForeignKey("degree_plan.id"),
        nullable=False,
    )

    code = db.Column(db.String(9), nullable=False)
    name = db.Column(db.String(9), nullable=False)
    credits = db.Column(db.Integer, nullable=False)
    difficulty = db.Column(db.Integer, nullable=True)

    plan = db.relationship("DegreePlan", backref="courses", lazy=True)

    def __repr__(self):
        return f"<Course {self.code}>"