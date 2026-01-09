"""
NVOC - UI Package

GTK4 user interface components.
"""

from .dashboard import DashboardPage
from .overclock import OverclockPage
from .fans import FansPage
from .profiles_view import ProfilesPage

__all__ = [
    "DashboardPage",
    "OverclockPage",
    "FansPage",
    "ProfilesPage",
]
