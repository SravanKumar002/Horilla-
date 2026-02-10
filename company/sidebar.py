from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as trans
from base.models import Company

# --- Main Menu Item Configuration ---

MENU = trans("Companies")
IMG_SRC = "images/ui/company.png"
ACCESSIBILITY = "company.sidebar.menu_accessibility"

# ✅ Use URL instead of REDIRECT so it becomes a clickable menu link
URL = reverse_lazy("company_index")

# No submenus — direct single link
SUBMENUS = []


# --- Accessibility Function (Callable) ---

def menu_accessibility(request, submenu=None, user_perms=None, *args, **kwargs):
    """
    Determines if the main 'Companies' menu should be visible.
    Rule:
    - Superusers always see it.
    - Otherwise, user must have `base.view_company` AND at least one
      company returned by `Company.get_companies_for_user`, so individual
      company permissions are respected.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False

    # Superuser: full access
    if user.is_superuser:
        return True

    # Require global company view permission
    if not user.has_perm("base.view_company"):
        return False

    # Respect per‑company visibility rules
    return Company.get_companies_for_user(user).exists()


# --- Compatibility: Dictionary fallback (safe for Horilla loaders) ---

menu_accessibility_map = {
    # Sidebar item will be shown only if user has `base.view_company`
    # and at least one accessible company via `Company.get_companies_for_user`.
    "Companies": ["base.view_company"],
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
