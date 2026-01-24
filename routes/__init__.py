from flask import Blueprint

main_bp = Blueprint("main", __name__)

# Import route modules so decorators register with the blueprint
from . import plans        # noqa: F401
from . import courses      # noqa: F401
from . import solver_routes  # noqa: F401
from . import plan_tools_routes  # noqa: F401
