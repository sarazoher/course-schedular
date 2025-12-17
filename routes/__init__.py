from flask import Blueprint

# single main blueprint for everything except auth(has its own)
main_bp = Blueprint("main", __name__)

#  import route modules (we'll create them later, hense the # noqa: F401)
from . import plans      # noqa: F401
from . import courses    # noqa: F401
from . import solver_routes     # noqa: F401

