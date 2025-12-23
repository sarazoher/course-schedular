import os
# Used it as ...



# Absolute path to project root 
# (a stable anchor for a;ll file paths-Where is it on disk)
basedir = os.path.abspath(os.path.dirname(__file__))

# Runtime only directory (DB, uploads, secrets)
instance_dir = os.path.join(basedir, "instance") 

class Config:
    SECRET_KEY = "dev-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(instance_dir, "app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Canonical course catalog (CSV + xlsx files). Put your uploaded files in this folder.
    CATALOG_DIR = os.path.join(basedir, "data_catalog") 
    
    # External prerequisite classification rules (solve-time only).
    # Keeping heuristics out of code so different catalogs can swap rules without code edits.
    EXTERNAL_RULES_PATH = os.path.join(CATALOG_DIR, "external_rules.txt")

    # Alias mapping for prereq tokens -> canonical course (code or name)
    ALIASES_CSV_PATH = os.path.join(CATALOG_DIR, "aliases.csv")

