"""
context_processor.py

This module is used to register context processor`
"""

import re

from django.apps import apps
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _

from base.models import Company, CompanyAccessControl, TrackLateComeEarlyOut
from company.utils import annotate_company_metrics, build_company_hierarchy
from base.urls import urlpatterns
from employee.models import (
    Employee,
    EmployeeGeneralSetting,
    EmployeeWorkInformation,
    ProfileEditFeature,
)
from horilla import horilla_apps
from horilla.decorators import hx_request_required, login_required, permission_required
from horilla.methods import get_horilla_model_class
from attendance.filters import (
    AttendanceActivityFilter,)
from datetime import datetime

class AllCompany:
    """
    Dummy class
    """

    class Urls:
        url = "https://ui-avatars.com/api/?name=All+Company&background=ffffff&color=5e17eb"

    company = "All Company"
    icon = Urls()
    text = "All companies"
    id = None


def get_last_section(path):
    # Remove any trailing slash and split the path
    segments = path.strip("/").split("/")

    # Get the last section (the ID)
    last_section = segments[-1] if segments else None
    return last_section


def get_companies(request):
    """
    This method will return the history additional field form
    
    Company visibility logic:
    - Global superusers/admins (no company assigned): See ALL companies
    - SuperUsers with manager permission: See ALL companies
    - SuperUsers without manager permission: See only their company and its children
    - Regular users: See only their company and its children
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        company_qs = Company.objects.none()
    else:
        # 1) Highest priority: explicit CompanyAccessControl rules
        access_rule = CompanyAccessControl.objects.filter(user=user).first()
        if access_rule:
            base_companies = list(access_rule.companies.all())
            visible_ids = set()
            for base_company in base_companies:
                visible_ids.add(base_company.id)
                visible_ids.update(
                    Company._get_descendant_company_ids(base_company.id)
                )
            company_qs = Company.objects.filter(id__in=visible_ids).select_related(
                "parent_company"
            )
        else:
            # 2) Manager permission override (same idea as company_index)
            if user.has_perm("base.view_company") and user.has_perm(
                "base.change_employeeshiftschedule"
            ):
                company_qs = Company.objects.all().select_related("parent_company")
            else:
                # 3) Superuser hierarchy / 4) normal users
                company_qs = Company.get_companies_for_user(user).select_related(
                    "parent_company"
                )

        # Apply the same company / subcompany permission rule used in
        # `company.views.company_index` so dropdown and cards match.
        can_view_subcompanies = (
            user.has_perm("base.view_company") and user.has_perm("base.view_subcompany")
        )
        if not can_view_subcompanies:
            company_qs = company_qs.filter(parent_company__isnull=True)
    company_list = list(company_qs)
    annotate_company_metrics(company_list)
    nav_company_hierarchy = build_company_hierarchy(company_list)
    companies = [
        [str(company.id), company.company, company.icon.url, False]
        for company in company_list
    ]
    companies = [
        [
            "all",
            "All Company",
            "https://ui-avatars.com/api/?name=All+Company&background=ffffff&color=5e17eb",
            False,
        ],
    ] + companies
    selected_company = request.session.get("selected_company")
    selected_company_str = str(selected_company) if selected_company else ""
    company_selected = False
    employee = getattr(request.user, "employee_get", None)
    work_info = getattr(employee, "employee_work_info", None) if employee else None
    user_company_instance = getattr(work_info, "company_id", None) if work_info else None
    user_company_id = str(user_company_instance.id) if user_company_instance else ""

    if selected_company and selected_company == "all":
        companies[0][3] = True
        company_selected = True
    else:
        for company in companies:
            if str(company[0]) == selected_company:
                company[3] = True
                company_selected = True
                break

    selected_ids = set()
    if selected_company_str:
        selected_ids.add(selected_company_str)
    elif user_company_id:
        selected_ids.add(user_company_id)

    for company in company_list:
        company.is_nav_selected = str(company.id) in selected_ids

    return {
        "all_companies": companies,
        "company_selected": company_selected,
        "nav_company_hierarchy": nav_company_hierarchy,
        "user_company_id": user_company_id,
    }


@login_required
@permission_required("base.view_company")
def update_selected_company(request):
    """
    This method is used to update the selected company on the session
    """
    company_id = request.GET.get("company_id")
    user = request.user.employee_get
    user_company = getattr(
        getattr(user, "employee_work_info", None), "company_id", None
    )
    request.session["selected_company"] = company_id
    company = (
        AllCompany()
        if company_id == "all"
        else (
            Company.objects.filter(id=company_id).first()
            if Company.objects.filter(id=company_id).first()
            else AllCompany()
        )
    )
    previous_path = request.GET.get("next", "/")
    # Define the regex pattern for the path
    pattern = r"^/employee/employee-view/\d+/$"
    # Check if the previous path matches the pattern
    if company_id != "all":
        if re.match(pattern, previous_path):
            employee_id = get_last_section(previous_path)
            employee = Employee.objects.filter(id=employee_id).first()
            emp_company = getattr(
                getattr(employee, "employee_work_info", None), "company_id", None
            )
            if emp_company != company:
                text = "Other Company"
                if company_id == user_company:
                    text = "My Company"
                company = {
                    "company": company.company,
                    "icon": company.icon.url,
                    "text": text,
                    "id": company.id,
                }
                messages.error(
                    request, _("Employee is not working in the selected company.")
                )
                request.session["selected_company_instance"] = company
                return HttpResponse(
                    f"""
                    <script>window.location.href = `{reverse("employee-view")}`</script>
                """
                )

    if company_id == "all":
        text = "All companies"
    elif company_id == user_company:
        text = "My Company"
    else:
        text = "Other Company"

    company = {
        "company": company.company,
        "icon": company.icon.url,
        "text": text,
        "id": company.id,
    }
    request.session["selected_company_instance"] = company

    # Support both HTMX and regular navigation:
    if request.headers.get("HX-Request"):
        return HttpResponse("<script>window.location.reload();</script>")
    return redirect(previous_path or "/")


urlpatterns.append(
    path(
        "update-selected-company",
        update_selected_company,
        name="update-selected-company",
    )
)


def white_labelling_company(request):
    white_labelling = getattr(horilla_apps, "WHITE_LABELLING", False)
    if white_labelling:
        hq = Company.objects.filter(hq=True).last()
        try:
            company = (
                request.user.employee_get.get_company()
                if request.user.employee_get.get_company()
                else hq
            )
        except:
            company = hq

        return {
            "white_label_company_name": company.company if company else "GreaterHRMS",
            "white_label_company": company,
        }
    else:
        return {
            "white_label_company_name": "GreaterHRMS",
            "white_label_company": None,
        }


def resignation_request_enabled(request):
    """
    Check weather resignation_request enabled of not in offboarding
    """
    enabled_resignation_request = False
    first = None
    if apps.is_installed("offboarding"):
        OffboardingGeneralSetting = get_horilla_model_class(
            app_label="offboarding", model="offboardinggeneralsetting"
        )
        first = OffboardingGeneralSetting.objects.first()
    if first:
        enabled_resignation_request = first.resignation_request
    return {"enabled_resignation_request": enabled_resignation_request}


def timerunner_enabled(request):
    """
    Check weather resignation_request enabled of not in offboarding
    """
    first = None
    enabled_timerunner = True
    if apps.is_installed("attendance"):
        AttendanceGeneralSetting = get_horilla_model_class(
            app_label="attendance", model="attendancegeneralsetting"
        )
        first = AttendanceGeneralSetting.objects.first()
        # print(first.__dict__)
    if first:
        enabled_timerunner = first.time_runner
    return {"enabled_timerunner": enabled_timerunner}


def intial_notice_period(request):
    """
    Check weather resignation_request enabled of not in offboarding
    """
    initial = 30
    first = None
    if apps.is_installed("payroll"):
        PayrollGeneralSetting = get_horilla_model_class(
            app_label="payroll", model="payrollgeneralsetting"
        )
        first = PayrollGeneralSetting.objects.first()
    if first:
        initial = first.notice_period
    return {"get_initial_notice_period": initial}


def check_candidate_self_tracking(request):
    """
    This method is used to get the candidate self tracking is enabled or not
    """

    candidate_self_tracking = False
    if apps.is_installed("recruitment"):
        RecruitmentGeneralSetting = get_horilla_model_class(
            app_label="recruitment", model="recruitmentgeneralsetting"
        )
        first = RecruitmentGeneralSetting.objects.first()
    else:
        first = None
    if first:
        candidate_self_tracking = first.candidate_self_tracking
    return {"check_candidate_self_tracking": candidate_self_tracking}


def check_candidate_self_tracking_rating(request):
    """
    This method is used to check enabled/disabled of rating option
    """
    rating_option = False
    if apps.is_installed("recruitment"):
        RecruitmentGeneralSetting = get_horilla_model_class(
            app_label="recruitment", model="recruitmentgeneralsetting"
        )
        first = RecruitmentGeneralSetting.objects.first()
    else:
        first = None
    if first:
        rating_option = first.show_overall_rating
    return {"check_candidate_self_tracking_rating": rating_option}


def get_initial_prefix(request):
    """
    This method is used to get the initial prefix
    """
    settings = EmployeeGeneralSetting.objects.first()
    instance_id = None
    prefix = "PEP"
    if settings:
        instance_id = settings.id
        prefix = settings.badge_id_prefix
    return {"get_initial_prefix": prefix, "prefix_instance_id": instance_id}


def biometric_app_exists(request):
    from django.conf import settings

    biometric_app_exists = "biometric" in settings.INSTALLED_APPS
    return {"biometric_app_exists": biometric_app_exists}


def enable_late_come_early_out_tracking(request):
    tracking = TrackLateComeEarlyOut.objects.first()
    enable = tracking.is_enable if tracking else True
    return {"tracking": enable, "late_come_early_out_tracking": enable}


def enable_profile_edit(request):
    from accessibility.accessibility import ACCESSBILITY_FEATURE

    profile_edit = ProfileEditFeature.objects.filter().first()
    enable = True if profile_edit and profile_edit.is_enabled else False
    if enable:
        if not any(item[0] == "profile_edit" for item in ACCESSBILITY_FEATURE):
            ACCESSBILITY_FEATURE.append(("profile_edit", _("Profile Edit Access")))

    return {"profile_edit_enabled": enable}


def calculate_elapsed_seconds(request):
    user = request.user
    filter_obj = AttendanceActivityFilter(request.GET)
    attendance_activities = filter_obj.qs
    if user.is_authenticated:
        latest_checkin = (attendance_activities.filter(employee_id=user.employee_get, clock_in__isnull=False).order_by('-attendance_date', '-clock_in').first())
        
        if latest_checkin:
            # Combine date + time into a datetime object
            latest_checkin_datetime = datetime.combine(
                latest_checkin.attendance_date,
                latest_checkin.clock_in
            )

            now = datetime.now()
            elapsed_seconds = int((now - latest_checkin_datetime).total_seconds())
            
        else:
            elapsed_seconds = 0
        return {"elapsed_seconds": elapsed_seconds}
    return {}