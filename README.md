# course-schedular

A degree course scheduler that builds valid academic schedules using real course catalog data, prerequisite logic, and user-defined constraints.  
The system is designed around correctness and stability first, before committing to database migrations or advanced modeling.

The application allows users to create degree plans, add courses from a shared catalog, define constraints per plan, and generate a schedule using a MILP solver.

---

## Setup

Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Initialize the database:

```bash
python init_db.py
```

Seed the course catalog (required):

```bash
python seed_catalog_db.py
```

Run the application:

```bash
python app.py
```

In the browser:
- Register and log in  
- Create a degree plan  
- Add courses from the catalog  
- Adjust plan settings if needed  
- Click **Solve** to generate a schedule  

---

## How the scheduler works

Clicking **Solve** runs a MILP-based solver that attempts to place every course in exactly one allowed semester while respecting plan constraints.

A schedule is generated **only if the solver finds an optimal solution**.  
If the plan is infeasible, no schedule is produced; instead, the user receives feedback describing what must be fixed (for example: missing offerings or impossible credit limits).

When a solution exists, the solver result is saved as a single `PlanSolution` snapshot per plan.  
Opening the schedule page later displays the saved result and **does not re-run the solver**.

---

## Plan settings and solver behavior

Each plan has its own settings that directly affect solver behavior:

- **Prerequisite enforcement**  
  Catalog prerequisites are enforced when they can be resolved to known courses.  
  Unresolved or external prerequisite tokens do not block solving and are recorded as warnings.

- **Credit limits**  
  When enabled, the solver enforces the configured maximum credits per semester.  
  When disabled, credit limits are ignored.

- **Prefer earlier completion**  
  When enabled, the solver minimizes the *latest semester used* (finishing as early as possible),  
  then packs courses earlier within that horizon.  
  When disabled, the solver simply packs courses as early as possible overall.

---

## Catalog data and real-world constraints

The scheduler is designed to work with real catalog data, which introduces complexity beyond simple course-to-course prerequisites:

- Prerequisites are written as free text with AND / OR logic  
- Corequisites exist  
- Some requirements (such as English or math placement) are not part of the schedule itself  

To handle this, prerequisite text is parsed into an internal logical representation at solve time.  
This allows the solver to enforce what it can, warn about what it cannot, and remain stable when faced with real-world data.

---

## Maintenance and repair scripts

Plans created before the current default-offerings logic may contain incorrect semester offerings.

A repair script can be used to regenerate offerings for a plan:

```bash
python scripts/regen_offerings.py <plan_id>
```

This script rewrites semester offerings based on:
- catalog metadata (academic year)  
- plan structure (total semesters and semesters per year)  

---

## Known limitations

- Corequisites are display-only and are not enforced by the solver.  
- Unresolved or external prerequisites are recorded as warnings and do not block solving.  
- Older plans may require manual repair of offerings using the provided script.  
- Only the most recent solver result per plan is stored.  

---

## Database migration status

Database migration is intentionally deferred.

The current focus is solver correctness and compatibility with real catalog data.  
A fresh database setup is fully supported. Existing databases may require manual repair scripts, and automatic migration from earlier schemas is not guaranteed at this stage.

This approach allows the system to remain stable while providing a clear path for future schema migration after solver behavior is finalized.



 
course-schedular/
│
├── auth/
│   ├── routes.py
│   └── __init__.py
│
├── data_catalog/
│   ├── archive/
│       └── דרישות קדם (+מרצה, סמסטר ושנה, נז) - מדעי המחשב.xlsx
│   ├── aliases.csv
│   ├── catalog_meta.json
│   ├── external_rules.txt
│   ├── optional_courses.json
│   └── דרישות קדם (+מרצה, סמסטר ושנה, נז) - מדעי המחשב.xlsx (New edited excel, cleaner prerequisites)
│
├── instance/
│   └── app.db
│
├── models/
│   ├── __init__.py
│   ├── catalog_course.py
│   ├── course_offering.py
│   ├── course.py
│   ├── degree_plan.py
│   ├── plan_constraint.py
│   ├── plan_course.py
│   ├── plan_solution.py
│   ├── prerequisite.py
│   └── user.py
│
├── routes/
│   ├── __init__.py
│   ├── courses.py
│   ├── plans.py
│   └── solver_routes.py
│
├── scripts/
│   ├── debug_catalog.py
│   ├── debug_prereq_parser.py
│   ├── extract_catalog_meta.py 
│   └── regen_offerings.py
│    
├── services/
│   ├── __init__.py
│   ├── catalog_meta.py
│   ├── req_ir.py
│   ├── solver.py
│   └── validation.py
│
├── static/csss
│   └── main.css
│
├── templates/
│   ├── base.html
│   ├── course_detail.html
│   ├── create_plan.html
│   ├── dashboard.html
│   ├── edit_course.html
│   ├── edit_offerings.html
│   ├── home.html
│   ├── login.html
│   ├── plan_detail.html
│   ├── plan_schedule.html
│   ├── plan_settings.html
│   └── register.html
│
├── utils/
│   ├── __init__.py
│   ├── alias_rules.py
│   ├── course_catalog.py
│   ├── default_offerings.py
│   ├── external_rules.py
│   ├── optional_courses.py
│   ├── req_parser.py
│   └── semesters.py
│
├── venv/
│
├── .gitignore
├── app.py
├── config.py
├── extensions.py
├── init_db.py
├── README.md
├── requirements.txt
├── requirements-dev.txt
└── seed_vatalog_db.py
