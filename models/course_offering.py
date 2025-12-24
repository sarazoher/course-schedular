from extensions import db


# Course X is offered in semester S in THIS plan (through the course->plan link)
class CourseOffering(db.Model):
    __tablename__ = "course_offering"

    __table_args__ = (
        # Prevent duplicate offering rows per course+semester
        db.UniqueConstraint("course_id", "semester_number", name="uq_offering_course_sem"),
    )

    id = db.Column(db.Integer, primary_key=True)

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id", ondelete="CASCADE"),
        nullable=False,
    )

    semester_number = db.Column(db.Integer, nullable=False)

    course = db.relationship("Course", back_populates="offerings", lazy=True)

    def __repr__(self) -> str:
        return f"<Offering course={self.course_id} sem={self.semester_number}>"
