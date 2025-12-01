from app import app
from extensions import db

# db models to create
from models.user import User
from models.degree_plan import DegreePlan
from models.course import Course
from models.prerequisite import Prerequisite
from models.course_offering import CourseOffering
from models.plan_constraint import PlanConstraint


with app.app_context():
    print("DB URI:", app.config["SQLALCHEMY_DATABASE_URI"])
    db.create_all()
    print("DB CREATED")
