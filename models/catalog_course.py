from extensions import db

class CatalogCourse(db.Model):
    __tablename__ = "catalog_courses"

    id = db.Column(db.Integer, primary_key=True)

    # Canonical identifier (for example "8500001"), keeping as string to preserve leading xeros id any
    code = db.Column(db.String(32), unique=True, index=True, nullable=False)

    # Display name from catalog (Heb/Eng)
    name = db.Column(db.String(255), nullable=False)

    # Optional metadata
    credits = db.Column(db.Float, nullable=True)
    prereq_text = db.Column(db.Text, nullable=True)

    def __repr__(self) -> str:
        return f"<CatalogCourse {self.code} {self.name}>"