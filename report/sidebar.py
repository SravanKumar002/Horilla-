from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as trans

# --- Main Menu Item Configuration ---

MENU = trans("Reports")
IMG_SRC = "images/ui/report.svg"
ACCESSIBILITY = "report.sidebar.menu_accessibility"

# ✅ Use URL instead of REDIRECT so it becomes a clickable menu link
URL = reverse_lazy("under_construction")

# No submenus — direct single link
SUBMENUS = []


# --- Accessibility Function (Callable) ---

def menu_accessibility(request, submenu=None, user_perms=None, *args, **kwargs):
    """
    Determines if the main 'Reports' menu should be visible.
    Minimal check: allow superusers or users with view_employee permission.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.has_perm("employee.view_employee")


# --- Compatibility: Dictionary fallback (safe for Horilla loaders) ---

menu_accessibility_map = {
    "Reports": ["employee.view_employee"],
}


# --- Placeholder accessibility functions (avoid missing attribute errors) ---

def recruitment_accessibility(request, submenu, user_perms, *args, **kwargs):
    return False

def employee_accessibility(request, submenu, user_perms, *args, **kwargs):
    return False

def attendance_accessibility(request, submenu, user_perms, *args, **kwargs):
    return False

def leave_accessibility(request, submenu, user_perms, *args, **kwargs):
    return False

def payroll_accessibility(request, submenu, user_perms, *args, **kwargs):
    return False

def asset_accessibility(request, submenu, user_perms, *args, **kwargs):
    return False

def pms_accessibility(request, submenu, user_perms, *args, **kwargs):
    return False
