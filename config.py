import os

basedir = os.path.abspath(os.path.dirname(__file__))
instance_dir = os.path.join(basedir, "instance")

class Config:
    SECRET_KEY = "dev-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(instance_dir, "app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Canonical course catalog (CSV files). Put your uploaded files in this folder.
    CATALOG_DIR = os.path.join(basedir, "data_catalog") 
