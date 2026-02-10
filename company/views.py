from django.shortcuts import render

# Create your views here.
from django.urls import path
from base.models import Company, CompanyAccessControl
from horilla.decorators import login_required, manager_can_enter
from company.utils import annotate_company_metrics, build_company_hierarchy


@login_required
@manager_can_enter("base.view_company")
def company_index(request):
    """
    Fixed Company visibility logic:
    - Superusers: See ALL companies.
    - Company Admins/Users: See ONLY their assigned company and its branches.
    - Explicit Access Control rules are also honored.
    """
    user = request.user
    visible_ids = set()
    employee = getattr(user, "employee_get", None)

    # 1. Assigned Company & Branches logic (Saru/Preeti fix)
    assigned_company = employee.get_company() if employee else getattr(user, "company", None)
    if assigned_company:
        visible_ids.add(assigned_company.id)
        visible_ids.update(Company._get_descendant_company_ids(assigned_company.id))

    # 2. Explicit CompanyAccessControl rules
    access_rule = CompanyAccessControl.objects.filter(user=user).first()
    if access_rule:
        base_companies = list(access_rule.companies.all())
        for base_company in base_companies:
            visible_ids.add(base_company.id)
            visible_ids.update(Company._get_descendant_company_ids(base_company.id))

    # 3. Final Queryset Logic
    has_view_perm = user.has_perm("base.view_company")
    has_change_schedule_perm = user.has_perm("base.change_employeeshiftschedule")

    # Manager bypass only allowed for true Superusers
    if user.is_superuser or (has_view_perm and has_change_schedule_perm and not employee):
        company_qs = Company.objects.all().select_related("parent_company")
    elif visible_ids:
        # Restricted view for Company Admins
        company_qs = Company.objects.filter(id__in=visible_ids).select_related("parent_company")
    else:
        # Default fallback
        company_qs = Company.get_companies_for_user(user).select_related("parent_company")

    # 4. Sub-company permission logic
    can_view_subcompanies = (
        request.user.has_perm("base.view_company")
        and request.user.has_perm("base.view_subcompany")
    )
    if not can_view_subcompanies and not user.is_superuser:
        company_qs = company_qs.filter(parent_company__isnull=True)

    # Force evaluation and metadata buildup
    company_list = list(company_qs)
    annotate_company_metrics(company_list)
    company_hierarchy = build_company_hierarchy(company_list)

    return render(
        request,
        "company/companies_card.html",
        {
            "companies": company_list,
            "company_hierarchy": company_hierarchy,
            "model": Company(),
            "can_view_subcompanies": can_view_subcompanies,
        },
    )