from app import app
from extensions import db
from models.catalog_course import CatalogCourse
from utils.course_catalog import load_catalog


def seed_catalog():
    catalog = load_catalog(app.config["CATALOG_DIR"])

    inserted = 0
    skipped = 0

    for c in catalog:
        # Adjust attribute names if your loader differs
        code = getattr(c, "code", None)
        name = getattr(c, "name", None)
        credits = getattr(c, "credits", None)
        prereq_text = getattr(c, "prereq_text", None)

        if not code or not name:
            continue

        exists = CatalogCourse.query.filter_by(code=code).first()
        if exists:
            skipped += 1
            continue

        db.session.add(
            CatalogCourse(
                code=code,
                name=name,
                credits=credits,
                prereq_text=prereq_text,
            )
        )
        inserted += 1

    db.session.commit()
    print(f"Catalog seed complete: {inserted} inserted, {skipped} skipped")


if __name__ == "__main__":
    with app.app_context():
        seed_catalog()
