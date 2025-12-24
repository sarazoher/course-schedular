from app import app
from extensions import db
import models # db models to create (all)

with app.app_context():
    print("DB URI:", app.config["SQLALCHEMY_DATABASE_URI"])
    db.create_all()
    print("DB CREATED")
