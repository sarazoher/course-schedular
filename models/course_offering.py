from extensions import db

# Course X is offered in semester S in THIS plan

class CourseOffering(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False,
    )

    semester_number = db.Column(db.Integer, nullable=False)

    course = db.relationship(
        "Course",
        backref="offerings",
        lazy=True,
    )

    def __repr__(self):
        return f"<Offering course={self.course_id} sem={self.semester_number}>"
    