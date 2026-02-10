"""
views.py

This module is used to define the method for the path in the urls
"""

import json
from datetime import datetime
from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import groupby
from urllib.parse import parse_qs

import pandas as pd
import pdfkit
from django.contrib import messages
from django.db.models import ProtectedError, Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from base.methods import (
    closest_numbers,
    eval_validate,
    export_data,
    generate_colors,
    generate_pdf,
    get_key_instances,
    sortby,
)
from base.models import Company
from employee.models import Employee, EmployeeWorkInformation
from horilla.decorators import (
    hx_request_required,
    login_required,
    owner_can_enter,
    permission_required,
)
from horilla.group_by import group_by_queryset
from horilla.horilla_settings import HORILLA_DATE_FORMATS
from notifications.signals import notify
from payroll.context_processors import get_active_employees
from payroll.filters import ContractFilter, ContractReGroup, PayslipFilter
from payroll.forms.component_forms import (
    ContractExportFieldForm,
    PayrollSettingsForm,
    PayslipAutoGenerateForm,
    PayslipInlineUpdateForm,
)
from payroll.methods.methods import paginator_qry, save_payslip
from payroll.models.models import (
    Allowance,
    Contract,
    Deduction,
    FilingStatus,
    PayrollGeneralSetting,
    Payslip,
    PayslipAutoGenerate,
    Reimbursement,
    ReimbursementFile,
    ReimbursementrequestComment,
)
from payroll.models.tax_models import PayrollSettings

# Create your views here.

status_choices = {
    "draft": _("Draft"),
    "review_ongoing": _("Review Ongoing"),
    "confirmed": _("Confirmed"),
    "paid": _("Paid"),
}


def get_language_code(request):
    scale_x_text = _("Name of Employees")
    scale_y_text = _("Amount")
    response = {"scale_x_text": scale_x_text, "scale_y_text": scale_y_text}
    return JsonResponse(response)


@login_required
@permission_required("payroll.add_contract")
def contract_create(request):
    """
    Contract create view
    """
    from payroll.forms.forms import ContractForm

    form = ContractForm()
    if request.method == "POST":
        form = ContractForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, _("Contract Created"))
            return redirect(contract_view)
    return render(request, "payroll/common/form.html", {"form": form})


@login_required
@permission_required("payroll.change_contract")
def contract_update(request, contract_id, **kwargs):
    """
    Update an existing contract.

    Args:
        request: The HTTP request object.
        contract_id: The ID of the contract to update.

    Returns:
        If the request method is POST and the form is valid, redirects to the contract view.
        Otherwise, renders the contract update form.

    """
    from payroll.forms.forms import ContractForm

    contract = Contract.objects.filter(id=contract_id).first()
    if not contract:
        messages.info(request, _("The contract could not be found."))
        return redirect(contract_view)
    contract_form = ContractForm(instance=contract)
    if request.method == "POST":
        contract_form = ContractForm(request.POST, request.FILES, instance=contract)
        if contract_form.is_valid():
            contract_form.save()
            messages.success(request, _("Contract updated"))
            return redirect(contract_view)
    return render(
        request,
        "payroll/common/form.html",
        {
            "form": contract_form,
        },
    )


@login_required
@hx_request_required
@permission_required("payroll.change_contract")
def contract_status_update(request, contract_id):
    from payroll.forms.forms import ContractForm

    previous_data = request.GET.urlencode()
    if request.method == "POST":
        contract = Contract.objects.get(id=contract_id)
        if request.POST.get("view"):
            status = request.POST.get("status")
            if status in dict(contract.CONTRACT_STATUS_CHOICES).keys():
                save = True
                if status in ["active", "draft"]:
                    active_contract = Contract.objects.filter(
                        contract_status="active", employee_id=contract.employee_id
                    ).exists()
                    draft_contract = Contract.objects.filter(
                        contract_status="draft", employee_id=contract.employee_id
                    ).exists()
                    if (status == "active" and active_contract) or (
                        status == "draft" and draft_contract
                    ):
                        save = False
                        messages.info(
                            request,
                            _("An {} contract already exists for {}").format(
                                status, contract.employee_id
                            ),
                        )
                if save:
                    contract.contract_status = status
                    contract.save()
                    messages.success(
                        request, _("The contract status has been updated successfully.")
                    )
            else:
                messages.warning(
                    request, _("You selected the wrong option for contract status.")
                )

            return redirect(f"/payroll/contract-filter?{previous_data}")

        contract_form = ContractForm(request.POST, request.FILES, instance=contract)
        if contract_form.is_valid():
            contract_form.save()
            messages.success(request, _("Contract status updated"))
        else:
            for errors in contract_form.errors.values():
                for error in errors:
                    messages.error(request, error)
        return HttpResponse("<script>$('#reloadMessagesButton').click()</script>")


@login_required
@permission_required("payroll.change_contract")
def bulk_contract_status_update(request):
    status = request.POST.get("status")
    ids = eval_validate(request.POST.get("ids"))
    all_contracts = Contract.objects.all()
    contracts = all_contracts.filter(id__in=ids)

    for contract in contracts:
        save = True
        if status in ["active", "draft"]:
            active_contract = all_contracts.filter(
                contract_status="active", employee_id=contract.employee_id
            ).exists()
            draft_contract = all_contracts.filter(
                contract_status="draft", employee_id=contract.employee_id
            ).exists()
            if (status == "active" and active_contract) or (
                status == "draft" and draft_contract
            ):
                save = False
                messages.info(
                    request,
                    _("An {} contract already exists for {}").format(
                        status, contract.employee_id
                    ),
                )
        if save:
            contract.contract_status = status
            contract.save()
            messages.success(
                request, _("The contract status has been updated successfully.")
            )
    return HttpResponse("success")


@login_required
@permission_required("payroll.change_contract")
def update_contract_filing_status(request, contract_id):
    if request.method == "POST":
        contract = get_object_or_404(Contract, id=contract_id)
        filing_status_id = request.POST.get("filing_status")
        try:
            filing_status = (
                FilingStatus.objects.get(id=int(filing_status_id))
                if filing_status_id
                else None
            )
            contract.filing_status = filing_status
            messages.success(
                request, _("The employee filing status has been updated successfully.")
            )
        except (ValueError, OverflowError, FilingStatus.DoesNotExist):
            messages.warning(
                request, _("You selected the wrong option for filing status.")
            )
        contract.save()
        return redirect(contract_filter)


@login_required
@hx_request_required
@permission_required("payroll.delete_contract")
def contract_delete(request, contract_id):
    """
    Delete a contract.

    Args:
        contract_id: The ID of the contract to delete.

    Returns:
        Redirects to the contract view after successfully deleting the contract.

    """
    try:
        Contract.objects.get(id=contract_id).delete()
        messages.success(request, _("Contract deleted"))
        request_path = request.path.split("/")
        if "delete-contract-modal" in request_path:
            if instances_ids := request.GET.get("instances_ids"):
                get_data = request.GET.copy()
                get_data.pop("instances_ids", None)
                previous_data = get_data.urlencode()
                instances_list = json.loads(instances_ids)
                previous_instance, next_instance = closest_numbers(
                    instances_list, contract_id
                )
                if contract_id in instances_list:
                    instances_list.remove(contract_id)
                urls = f"/payroll/single-contract-view/{next_instance}/"
                params = f"?{previous_data}&instances_ids={instances_list}"
                return redirect(urls + params)
            return HttpResponse("<script>window.location.reload();</script>")
        else:
            return redirect(f"/payroll/contract-filter?{request.GET.urlencode()}")
    except Contract.DoesNotExist:
        messages.error(request, _("Contract not found."))
    except ProtectedError:
        messages.error(request, _("You cannot delete this contract."))
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))


@login_required
@permission_required("payroll.view_contract")
def contract_view(request):
    """
    Contract view method
    """

    contracts = Contract.objects.all()
    if contracts.exists():
        template = "payroll/contract/contract_view.html"
    else:
        template = "payroll/contract/contract_empty.html"

    contracts = paginator_qry(contracts, request.GET.get("page"))
    contract_ids_json = json.dumps([instance.id for instance in contracts.object_list])
    filter_form = ContractFilter(request.GET)
    context = {
        "contracts": contracts,
        "f": filter_form,
        "contract_ids": contract_ids_json,
        "gp_fields": ContractReGroup.fields,
    }

    return render(request, template, context)


@login_required
# @hx_request_required         #this function is also used in payroll dashboard which uses ajax
@owner_can_enter("payroll.view_contract", Contract)
def view_single_contract(request, contract_id):
    """
    Renders a single contract view page.
    """
    get_data = request.GET.copy()
    get_data.pop("instances_ids", None)
    previous_data = get_data.urlencode()
    dashboard = request.GET.get("dashboard", "")

    HTTP_REFERERS = request.META.get("HTTP_REFERER", "").split("/")
    delete_hx_target = (
        "#personal_target"
        if "employee-view" in HTTP_REFERERS or "employee-profile" in HTTP_REFERERS
        else "#objectDetailsModalTarget"
    )

    contract = Contract.find(contract_id)

    context = {
        "contract": contract,
        "dashboard": dashboard,
        "delete_hx_target": delete_hx_target,
        "pd": previous_data,
    }

    contract_ids_json = request.GET.get("instances_ids")
    if contract_ids_json:
        contract_ids = json.loads(contract_ids_json)
        previous_id, next_id = closest_numbers(contract_ids, contract_id)
        context.update(
            {
                "previous": previous_id,
                "next": next_id,
                "contract_ids": contract_ids_json,
            }
        )
    return render(request, "payroll/contract/contract_single_view.html", context)


@login_required
@hx_request_required
@permission_required("payroll.view_contract")
def contract_filter(request):
    """
    Filter contracts based on the provided query parameters.

    Args:
        request: The HTTP request object containing the query parameters.

    Returns:
        Renders the contract list template with the filtered contracts.

    """
    query_string = request.GET.urlencode()
    contracts_filter = ContractFilter(request.GET)
    template = "payroll/contract/contract_list.html"
    contracts = contracts_filter.qs
    field = request.GET.get("field")

    if field != "" and field is not None:
        contracts = group_by_queryset(contracts, field, request.GET.get("page"), "page")
        list_values = [entry["list"] for entry in contracts]
        id_list = []
        for value in list_values:
            for instance in value.object_list:
                id_list.append(instance.id)

        contract_ids_json = json.dumps(list(id_list))
        template = "payroll/contract/group_by.html"

    else:
        contracts = sortby(request, contracts, "orderby")
        contracts = paginator_qry(contracts, request.GET.get("page"))
        contract_ids_json = json.dumps(
            [instance.id for instance in contracts.object_list]
        )

    data_dict = parse_qs(query_string)
    get_key_instances(Contract, data_dict)
    keys_to_remove = [key for key, value in data_dict.items() if value == ["unknown"]]
    for key in keys_to_remove:
        data_dict.pop(key)
    if "contract_status" in data_dict:
        status_list = data_dict["contract_status"]
        if len(status_list) > 1:
            data_dict["contract_status"] = [status_list[-1]]
    return render(
        request,
        template,
        {
            "contracts": contracts,
            "pd": query_string,
            "filter_dict": data_dict,
            "contract_ids": contract_ids_json,
            "field": field,
        },
    )


@login_required
@permission_required("payroll.view_payrollsettings")
def settings(request):
    """
    This method is used to render settings template
    """
    instance = PayrollSettings.objects.first()
    currency_form = PayrollSettingsForm(instance=instance)
    selected_company_id = request.session.get("selected_company")

    if selected_company_id == "all" or not selected_company_id:
        companies = Company.objects.all()
    else:
        companies = Company.objects.filter(id=selected_company_id)

    if request.method == "POST":

        currency_form = PayrollSettingsForm(request.POST, instance=instance)
        if currency_form.is_valid():

            currency_form.save()
            messages.success(request, _("Payroll settings updated."))
            return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))
    return render(
        request,
        "payroll/settings/payroll_settings.html",
        {
            "currency_form": currency_form,
            "companies": companies,
            "selected_company_id": selected_company_id,
        },
    )


@login_required
@permission_required("payroll.change_payslip")
def update_payslip_status(request, payslip_id):
    """
    This method is used to update the payslip confirmation status
    """
    status = request.POST.get("status")
    view = request.POST.get("view")
    payslip = Payslip.objects.filter(id=payslip_id).first()
    if payslip:
        payslip.status = status
        payslip.save()
        messages.success(request, ("Payslip status updated"))
    else:
        messages.error(request, ("Payslip not found"))
    if view:
        from .component_views import filter_payslip

        # If this is an HTMX request coming from the table view,
        # return the refreshed table HTML directly instead of a full redirect.
        if request.headers.get("HX-Request"):
            qd = QueryDict(mutable=True)
            qd.update({"view": view})
            request.GET = qd
            return filter_payslip(request)

        return redirect(filter_payslip)
    # Get pay_head_data - it might be a dict or JSON string
    pay_head_data = payslip.pay_head_data
    if isinstance(pay_head_data, str):
        try:
            import json
            pay_head_data = json.loads(pay_head_data)
        except (json.JSONDecodeError, TypeError):
            pay_head_data = {}
    data = pay_head_data or {}
    data["employee"] = payslip.employee_id
    data["payslip"] = payslip
    data["json_data"] = data.copy()
    data["json_data"]["employee"] = payslip.employee_id.id
    data["json_data"]["payslip"] = payslip.id
    data["instance"] = payslip
    
    # Check if this is an imported payslip FIRST - needed for paid_days calculation
    is_imported = data.get('is_imported', False) or payslip.pay_head_data.get('is_imported', False) if isinstance(payslip.pay_head_data, dict) else False
    
    # Ensure paid_days and unpaid_days are available in template context
    # data IS pay_head_data, so extract directly from it
    # Debug: Check what's in pay_head_data
    print(f"[VIEW_PAYSLIP_SUMMARY] pay_head_data keys: {list(data.keys())}")
    print(f"[VIEW_PAYSLIP_SUMMARY] pay_head_data.get('paid_days'): {data.get('paid_days')}")
    print(f"[VIEW_PAYSLIP_SUMMARY] pay_head_data.get('unpaid_days'): {data.get('unpaid_days')}")
    print(f"[VIEW_PAYSLIP_SUMMARY] pay_head_data.get('lop_days'): {data.get('lop_days')}")
    print(f"[VIEW_PAYSLIP_SUMMARY] is_imported: {is_imported}")
    
    # Extract unpaid_days first
    # HORILLA-STYLE: unpaid_days = 0 unless explicitly provided (NOT from attendance)
    unpaid_days_value = data.get("unpaid_days")
    if unpaid_days_value is None or unpaid_days_value == "":
        unpaid_days_value = data.get("lop_days")
    if unpaid_days_value is None or unpaid_days_value == "":
        # Default to 0 (no attendance-based calculation)
        unpaid_days_value = 0
    
    try:
        data["unpaid_days"] = round(float(unpaid_days_value), 2)
    except (ValueError, TypeError) as e:
        print(f"[VIEW_PAYSLIP_SUMMARY] Error converting unpaid_days: {e}, value: {unpaid_days_value}")
        data["unpaid_days"] = 0
    
    # Extract paid_days and validate/correct if needed
    paid_days_value = data.get("paid_days")
    
    # Calculate total days in period: (Payslip End Date - Payslip Start Date) + 1
    start_date_obj = payslip.start_date
    end_date_obj = payslip.end_date
    days_in_period = 0
    if start_date_obj and end_date_obj:
        days_in_period = (end_date_obj - start_date_obj).days + 1
    
    # CRITICAL: For imported payslips, use Excel paid_days if provided, otherwise calculate from date range
    if is_imported:
        # Try to convert paid_days_value to float first to check if it's valid
        paid_days_float = None
        if paid_days_value is not None and paid_days_value != "":
            try:
                paid_days_float = float(paid_days_value)
            except (ValueError, TypeError) as e:
                print(f"[VIEW_PAYSLIP_SUMMARY] Error converting paid_days to float: {e}, value: {paid_days_value}")
                paid_days_float = None
        
        if paid_days_float is not None and paid_days_float > 0:
            # Excel provided paid_days - use it exactly
            paid_days_value = round(paid_days_float, 2)
            print(f"[VIEW_PAYSLIP_SUMMARY] Imported payslip - using Excel paid_days: {paid_days_value}")
        else:
            # Excel did NOT provide paid_days (or it's 0) - calculate as (End Date - Start Date) + 1
            paid_days_value = round(float(days_in_period), 2) if days_in_period > 0 else 0
            print(f"[VIEW_PAYSLIP_SUMMARY] Imported payslip - paid_days not in Excel or is 0, calculated from date range: {paid_days_value} (days_in_period: {days_in_period})")
    else:
        # For non-imported payslips, use date range calculation (NO attendance logic)
        # HORILLA-STYLE: Paid Days = (End Date - Start Date) + 1, LOP = 0 (unless explicitly provided)
        if paid_days_value is None or paid_days_value == "" or paid_days_value == 0:
            # Calculate from date range: Total Days = (End Date - Start Date) + 1
            paid_days_value = round(float(days_in_period), 2) if days_in_period > 0 else 0
            print(f"[VIEW_PAYSLIP_SUMMARY] Non-imported payslip - calculated paid_days from date range: {paid_days_value} (days_in_period: {days_in_period})")
        else:
            try:
                paid_days_value = float(paid_days_value)
                # Ensure paid_days doesn't exceed total days
                if days_in_period > 0 and paid_days_value > days_in_period:
                    paid_days_value = round(float(days_in_period), 2)
                    print(f"[VIEW_PAYSLIP_SUMMARY] WARNING: paid_days ({paid_days_value}) > total_days ({days_in_period}). Set to {paid_days_value}")
            except (ValueError, TypeError) as e:
                print(f"[VIEW_PAYSLIP_SUMMARY] Error converting paid_days: {e}, value: {paid_days_value}")
                paid_days_value = round(float(days_in_period), 2) if days_in_period > 0 else 0
    
    try:
        data["paid_days"] = round(float(paid_days_value), 2)
    except (ValueError, TypeError) as e:
        print(f"[VIEW_PAYSLIP_SUMMARY] Error rounding paid_days: {e}, value: {paid_days_value}")
        data["paid_days"] = 0
    
    # Recalculate basic_pay based on recalculated paid_days if it's 0 or incorrect
    basic_pay_value = data.get("basic_pay", payslip.basic_pay or 0)
    contract_wage = payslip.contract_wage or data.get("contract_wage", 0)
    
    # If basic_pay is 0 but we have contract_wage and paid_days, recalculate
    if (basic_pay_value == 0 or basic_pay_value is None) and contract_wage > 0 and data["paid_days"] > 0 and days_in_period > 0:
        per_day_wage = contract_wage / days_in_period
        recalculated_basic_pay = per_day_wage * data["paid_days"]
        basic_pay_value = round(recalculated_basic_pay, 2)
        print(f"[VIEW_PAYSLIP_SUMMARY] Recalculated basic_pay: ({contract_wage} / {days_in_period}) * {data['paid_days']} = {basic_pay_value}")
        data["basic_pay"] = basic_pay_value
    else:
        data["basic_pay"] = basic_pay_value if basic_pay_value else 0
    
    # is_imported already checked above for paid_days calculation
    
    # Calculate loss_of_pay if not present - SKIP auto-calculation (use only explicit values)
    # HORILLA-STYLE: LOP = 0 unless explicitly provided via import/deduction (NOT from attendance)
    loss_of_pay_value = data.get("loss_of_pay")
    if loss_of_pay_value is None:
        loss_of_pay_value = data.get("lop", 0)
    
    # CRITICAL: Do NOT auto-calculate LOP from unpaid_days or attendance
    # Only use explicit values from pay_head_data (import/deduction)
    # For non-imported payslips, if LOP is not explicitly set, use 0
    if not is_imported and (loss_of_pay_value is None or loss_of_pay_value == 0):
        # Do NOT calculate from unpaid_days - set to 0 (old Horilla behavior)
        loss_of_pay_value = 0
    
    data["loss_of_pay"] = loss_of_pay_value if loss_of_pay_value else 0
    
    # For imported payslips, skip database queries and use empty lists
    if is_imported:
        print(f"[VIEW_PAYSLIP_SUMMARY] Payslip is imported - skipping database allowances/deductions")
        # CRITICAL: Completely clear ALL previous allowances and deductions from pay_head_data
        # This ensures only fresh Excel data is shown, no previous database allowances/deductions
        allowances_list = []
        data["allowances"] = []
        
        # CRITICAL: Completely clear ALL previous allowances and deductions from pay_head_data
        # This ensures only fresh Excel data is shown, no previous database allowances/deductions
        # Clear from payslip.pay_head_data (persistent storage)
        if isinstance(payslip.pay_head_data, dict):
            payslip.pay_head_data['allowances'] = []
            payslip.pay_head_data['pretax_deductions'] = []
            payslip.pay_head_data['posttax_deductions'] = []
            payslip.pay_head_data['post_tax_deductions'] = []
            payslip.pay_head_data['basic_pay_deductions'] = []
            payslip.pay_head_data['gross_pay_deductions'] = []
            payslip.pay_head_data['tax_deductions'] = []
            payslip.pay_head_data['net_deductions'] = []
            # Save the cleared state to database to prevent old data from showing again
            payslip.save(update_fields=['pay_head_data'])
            print(f"[VIEW_PAYSLIP_SUMMARY] Cleared and saved pay_head_data allowances/deductions to database")
        
        # Also clear from data dict (which is pay_head_data) for template rendering
        data['allowances'] = []
        data['pretax_deductions'] = []
        data['posttax_deductions'] = []
        data['post_tax_deductions'] = []
        data['basic_pay_deductions'] = []
        data['gross_pay_deductions'] = []
        data['tax_deductions'] = []
        data['net_deductions'] = []
        
        print(f"[VIEW_PAYSLIP_SUMMARY] Cleared all previous allowances and deductions from imported payslip - only Excel data will be shown")
    else:
        # Fetch allowances (bonuses) from database for this employee and payslip period
        employee = payslip.employee_id
        # start_date_obj and end_date_obj already defined above (lines 529-533)
        
        # Query allowances that are specific to this employee and within the payslip period
        allowances_queryset = Allowance.objects.filter(
            specific_employees=employee,
            only_show_under_employee=True
        )
        
        # Filter by date if one_time_date is set and falls within payslip period
        if start_date_obj and end_date_obj:
            allowances_queryset = allowances_queryset.filter(
                Q(one_time_date__isnull=True) | 
                Q(one_time_date__gte=start_date_obj, one_time_date__lte=end_date_obj)
            )
        
        # Convert to list format expected by template
        allowances_list = []
        for allowance in allowances_queryset:
            # Calculate amount - use fixed amount or calculate based on rate
            amount = 0
            if allowance.is_fixed:
                amount = float(allowance.amount or 0)
            else:
                # For non-fixed, calculate based on rate and basic pay
                basic_pay = data.get("basic_pay", payslip.basic_pay or 0)
                rate = float(allowance.rate or 0)
                amount = (basic_pay * rate) / 100
            
            if amount > 0:
                allowances_list.append({
                    "title": allowance.title,
                    "amount": round(amount, 2),
                    "id": allowance.id
                })
        
        data["allowances"] = allowances_list
    
    # Set is_imported flag in data for template
    data["is_imported"] = is_imported
    
    # CRITICAL: For imported payslips, still fetch bonuses that were added AFTER import
    if is_imported and start_date_obj and end_date_obj:
        bonus_allowances = Allowance.objects.filter(
            specific_employees=employee,
            only_show_under_employee=True
        ).filter(
            Q(one_time_date__isnull=True) | 
            Q(one_time_date__gte=start_date_obj, one_time_date__lte=end_date_obj)
        )
        
        # Only add bonuses (not other allowances) to the list
        for allowance in bonus_allowances:
            # Check if it's a bonus (title contains "bonus" or similar)
            if "bonus" in allowance.title.lower():
                amount = 0
                if allowance.is_fixed:
                    amount = float(allowance.amount or 0)
                else:
                    basic_pay = data.get("basic_pay", payslip.basic_pay or 0)
                    rate = float(allowance.rate or 0)
                    amount = (basic_pay * rate) / 100
                
                if amount > 0:
                    allowances_list.append({
                        "title": allowance.title,
                        "amount": round(amount, 2),
                        "id": allowance.id
                    })
    
    # Extract housing, transport, and other allowances from pay_head_data
    data["housing_allowance"] = data.get("housing_allowance", 0)
    data["transport_allowance"] = data.get("transport_allowance", 0)
    data["other_allowance"] = data.get("other_allowance", 0)
    
    # CRITICAL: Extract Excel-specific components (overtime, salary_advance, bonus) for imported payslips
    # These are needed for the Excel formula: (Gross Pay + Overtime + Salary Advance + Bonus) - (LOP + Loan Recovery + Deduction)
    data["overtime"] = data.get("overtime", 0)
    data["salary_advance"] = data.get("salary_advance", 0)
    data["bonus"] = data.get("bonus", 0)
    
    # CRITICAL: Extract Excel-specific deductions (salary_advance_loan_recovery, deduction) for imported payslips
    # These are needed for display and the Excel formula
    data["salary_advance_loan_recovery"] = data.get("salary_advance_loan_recovery", 0)
    data["deduction"] = data.get("deduction", 0)
    
    # Start with basic pay
    basic_pay = float(data.get("basic_pay", payslip.basic_pay or 0))
    
    # For imported payslips, skip database deductions (Excel deductions only)
    if is_imported:
        # CRITICAL: For imported payslips, fetch manually added deductions from database
        # These are deductions added via add_deduction AFTER import
        # But do NOT include them in net pay calculation (Excel formula only)
        employee = payslip.employee_id
        deductions_queryset = Deduction.objects.filter(
            specific_employees=employee,
            only_show_under_employee=True
        )
        
        # Filter by date if one_time_date is set and falls within payslip period
        if start_date_obj and end_date_obj:
            deductions_queryset = deductions_queryset.filter(
                Q(one_time_date__isnull=True) | 
                Q(one_time_date__gte=start_date_obj, one_time_date__lte=end_date_obj)
            )
        
        # Initialize deduction lists (will contain manually added deductions only)
        basic_pay_deductions_list = []
        gross_pay_deductions_list = []
        pretax_deductions_list = []
        post_tax_deductions_list = []
        tax_deductions_list = []
        net_deductions_list = []
        basic_pay_deduction_total = 0
        gross_pay_deduction_total = 0
        
        # Fetch manually added deductions from database (for display only, not calculation)
        for deduction in deductions_queryset:
            amount = 0
            if deduction.is_fixed:
                amount = float(deduction.amount or 0)
            else:
                basic_pay_for_calc = float(data.get("basic_pay", payslip.basic_pay or 0))
                rate = float(deduction.rate or 0)
                amount = (basic_pay_for_calc * rate) / 100
            
            if amount > 0:
                deduction_dict = {
                    "title": deduction.title,
                    "amount": round(amount, 2),
                    "id": deduction.id,
                    "update_compensation": deduction.update_compensation
                }
                
                # Categorize deduction based on its type
                if deduction.update_compensation == "basic_pay":
                    basic_pay_deductions_list.append(deduction_dict)
                elif deduction.update_compensation == "gross_pay":
                    gross_pay_deductions_list.append(deduction_dict)
                elif deduction.update_compensation == "net_pay":
                    net_deductions_list.append(deduction_dict)
                elif deduction.is_pretax:
                    pretax_deductions_list.append(deduction_dict)
                elif deduction.is_tax:
                    tax_deductions_list.append(deduction_dict)
                else:
                    post_tax_deductions_list.append(deduction_dict)
        
        # Use values from pay_head_data (Excel data)
        basic_pay = float(data.get("basic_pay", payslip.basic_pay or 0))
        
        # CRITICAL: Recalculate gross_pay to include bonuses added after import
        housing = float(data["housing_allowance"])
        transport = float(data["transport_allowance"])
        other = float(data["other_allowance"])
        bonus_total = sum(a.get("amount", 0) for a in allowances_list if "bonus" in a.get("title", "").lower())
        
        # CRITICAL: Also check direct "bonus" field in pay_head_data if not in allowances list
        excel_bonus = float(data.get("bonus", 0) or 0)
        if excel_bonus > 0 and bonus_total == 0:
            # If there's a direct bonus field and no bonuses in allowances list, use it
            bonus_total = excel_bonus
        elif excel_bonus > 0 and bonus_total > 0:
            # If both exist, prefer allowances list (as it might include database bonuses)
            # But ensure we don't double count - this case shouldn't happen, but just in case
            pass
        
        # CRITICAL: Extract overtime and salary_advance from pay_head_data
        # These are separate fields, not in allowances list
        overtime = float(data.get("overtime", 0) or 0)
        salary_advance = float(data.get("salary_advance", 0) or 0)
        
        # CRITICAL: Recalculate gross pay - EXCLUDING Overtime, Salary Advance, Bonus
        # Gross Pay = Basic Pay + Housing + Transport + Other Allowance
        gross_pay = round(basic_pay + housing + transport + other, 2)
        
        # CRITICAL: Net Pay calculation for imported payslips
        # Net Pay = Gross Pay + Overtime + Salary Advance + Bonus - (LOP + Loan Recovery + Deduction)
        lop = float(data.get("loss_of_pay", data.get("lop", 0)))
        loan_recovery = float(data.get("salary_advance_loan_recovery", 0))
        deduction = float(data.get("deduction", 0))
        
        # Net Pay = Gross Pay + Additional Allowances - Deductions
        net_pay = round(
            gross_pay + overtime + salary_advance + bonus_total - (lop + loan_recovery + deduction),
            2
        )
    else:
        # Fetch deductions from database for this employee and payslip period
        employee = payslip.employee_id
        deductions_queryset = Deduction.objects.filter(
            specific_employees=employee,
            only_show_under_employee=True
        )
        
        # Filter by date if one_time_date is set and falls within payslip period
        if start_date_obj and end_date_obj:
            deductions_queryset = deductions_queryset.filter(
                Q(one_time_date__isnull=True) | 
                Q(one_time_date__gte=start_date_obj, one_time_date__lte=end_date_obj)
            )
        
        # STEP 1: Collect basic_pay deductions for display (DO NOT apply again - already applied in payroll_calculation)
        # CRITICAL: basic_pay from payslip model already has deductions with update_compensation="basic_pay" applied
        # We only collect them for display purposes, not to deduct again
        basic_pay_deductions_list = []
        for deduction in deductions_queryset:
            if deduction.update_compensation == "basic_pay":
                amount = 0
                if deduction.is_fixed:
                    amount = float(deduction.amount or 0)
                else:
                    # Use original basic_pay (before deductions) for rate calculation
                    # Get from payslip contract_wage or calculate from current basic_pay + deductions
                    original_basic_pay = payslip.contract_wage or basic_pay
                    rate = float(deduction.rate or 0)
                    amount = (original_basic_pay * rate) / 100
                
                if amount > 0:
                    basic_pay_deductions_list.append({
                        "title": deduction.title,
                        "amount": round(amount, 2),
                        "id": deduction.id,
                        "update_compensation": deduction.update_compensation
                    })
        
        # CRITICAL: Do NOT apply basic_pay deductions again - they're already in payslip.basic_pay
        # The basic_pay from payslip model already has these deductions applied via update_compensation_deduction
    
    data["basic_pay"] = basic_pay  # Use basic_pay as-is from payslip
    
    # STEP 2: Calculate gross pay with updated basic_pay
    if not is_imported:
        total_allowances_from_db = sum(allowance.get("amount", 0) for allowance in allowances_list)
        gross_pay = round(
            basic_pay + 
            float(data["housing_allowance"]) + 
            float(data["transport_allowance"]) + 
            float(data["other_allowance"]) + 
            total_allowances_from_db, 
            2
        )
        
        # STEP 3: Apply gross_pay deductions
        gross_pay_deductions_list = []
        gross_pay_deduction_total = 0
        for deduction in deductions_queryset:
            if deduction.update_compensation == "gross_pay":
                amount = 0
                if deduction.is_fixed:
                    amount = float(deduction.amount or 0)
                else:
                    rate = float(deduction.rate or 0)
                    amount = (gross_pay * rate) / 100
                
                if amount > 0:
                    gross_pay_deduction_total += amount
                    gross_pay_deductions_list.append({
                        "title": deduction.title,
                        "amount": round(amount, 2),
                        "id": deduction.id,
                        "update_compensation": deduction.update_compensation
                    })
        
        # Apply gross_pay deductions
        gross_pay = round(gross_pay, 2)
    
    data["gross_pay"] = gross_pay
    
    # STEP 4: Calculate other deductions (pretax, post_tax, tax) - these don't update compensation
    if not is_imported:
        pretax_deductions_list = []
        post_tax_deductions_list = []
        tax_deductions_list = []
        
        for deduction in deductions_queryset:
            # Skip deductions that update compensation (already handled)
            if deduction.update_compensation:
                continue
                
            # Calculate amount
            amount = 0
            if deduction.is_fixed:
                amount = float(deduction.amount or 0)
            else:
                if deduction.based_on == "basic_pay":
                    base_amount = basic_pay
                elif deduction.based_on == "gross_pay":
                    base_amount = gross_pay
                else:
                    base_amount = basic_pay
                
                rate = float(deduction.rate or 0)
                amount = (base_amount * rate) / 100
            
            if amount > 0:
                deduction_dict = {
                    "title": deduction.title,
                    "amount": round(amount, 2),
                    "id": deduction.id,
                    "update_compensation": deduction.update_compensation
                }
                
                if deduction.is_pretax:
                    pretax_deductions_list.append(deduction_dict)
                elif deduction.is_tax:
                    tax_deductions_list.append(deduction_dict)
                else:
                    post_tax_deductions_list.append(deduction_dict)
    
    # Calculate net pay before net_pay deductions
    if not is_imported:
        total_other_deductions = (
            sum(d.get("amount", 0) for d in pretax_deductions_list) +
            sum(d.get("amount", 0) for d in post_tax_deductions_list) +
            sum(d.get("amount", 0) for d in tax_deductions_list)
        )
        # CRITICAL: Only include LOP in deductions if it's NOT deducted from basic_pay
        lop_for_deduction = float(data.get("loss_of_pay", 0))
        net_pay = round(gross_pay - total_other_deductions - lop_for_deduction, 2)
        
        # STEP 5: Apply net_pay deductions
        net_deductions_list = []
        net_pay_deduction_total = 0
        for deduction in deductions_queryset:
            if deduction.update_compensation == "net_pay":
                amount = 0
                if deduction.is_fixed:
                    amount = float(deduction.amount or 0)
                else:
                    rate = float(deduction.rate or 0)
                    amount = (net_pay * rate) / 100
                
                if amount > 0:
                    net_pay_deduction_total += amount
                    net_deductions_list.append({
                        "title": deduction.title,
                        "amount": round(amount, 2),
                        "id": deduction.id,
                        "update_compensation": deduction.update_compensation
                    })
        
        # Apply net_pay deductions
        net_pay = round(net_pay - net_pay_deduction_total, 2)
    
    data["net_pay"] = net_pay
    
    # Merge with deductions from pay_head_data if any (only for non-imported payslips)
    if is_imported:
        # For imported payslips, use ONLY empty lists - no deductions from pay_head_data
        # This ensures fresh import data only, no previous deductions
        data["basic_pay_deductions"] = []
        data["gross_pay_deductions"] = []
        data["pretax_deductions"] = []
        data["post_tax_deductions"] = []
        data["tax_deductions"] = []
        data["net_deductions"] = []
        print(f"[VIEW_PAYSLIP_SUMMARY] Set all deduction lists to empty for imported payslip")
    else:
        # For non-imported payslips, merge database deductions with pay_head_data
        data["basic_pay_deductions"] = basic_pay_deductions_list + data.get("basic_pay_deductions", [])
        data["gross_pay_deductions"] = gross_pay_deductions_list + data.get("gross_pay_deductions", [])
        data["pretax_deductions"] = pretax_deductions_list + data.get("pretax_deductions", [])
        data["post_tax_deductions"] = post_tax_deductions_list + data.get("post_tax_deductions", [])
        data["tax_deductions"] = tax_deductions_list + data.get("tax_deductions", [])
        data["net_deductions"] = net_deductions_list + data.get("net_deductions", [])
    
    # Calculate total deductions for display
    if is_imported:
        # For imported payslips, total_deductions comes from Excel formula only
        # (LOP + Loan Recovery + Deduction)
        # Manually added deductions are shown but NOT included in total
        lop = float(data.get("loss_of_pay", data.get("lop", 0)))
        loan_recovery = float(data.get("salary_advance_loan_recovery", 0))
        deduction = float(data.get("deduction", 0))
        total_deductions_amount = round(lop + loan_recovery + deduction, 2)
        data["total_deductions"] = total_deductions_amount
    else:
        # For non-imported payslips, include all deductions from lists (EXCLUDE basic_pay_deductions - already in basic_pay)
        # CRITICAL: basic_pay_deductions are already applied to basic_pay in payroll_calculation
        # Including them here would cause double deduction
        total_deductions_from_lists = (
            sum(d.get("amount", 0) for d in data["pretax_deductions"]) +
            sum(d.get("amount", 0) for d in data["post_tax_deductions"]) +
            sum(d.get("amount", 0) for d in data["tax_deductions"]) +
            sum(d.get("amount", 0) for d in data["net_deductions"]) +
            sum(d.get("amount", 0) for d in data["gross_pay_deductions"])
            # NOTE: basic_pay_deductions are NOT included - they're already in basic_pay calculation
        )
        
        # Add loss of pay to total deductions
        total_deductions_amount = round(total_deductions_from_lists + float(data.get("loss_of_pay", 0)), 2)
        data["total_deductions"] = total_deductions_amount
    
    print(f"[VIEW_PAYSLIP_SUMMARY] Final values - paid_days: {data['paid_days']}, unpaid_days: {data['unpaid_days']}, loss_of_pay: {data['loss_of_pay']}")
    print(f"[VIEW_PAYSLIP_SUMMARY] Allowances found: {len(allowances_list)}")
    
    return render(request, "payroll/payslip/individual_payslip_summery.html", data)


@login_required
@permission_required("payroll.change_payslip")
def payslip_inline_edit(request, payslip_id):
    """
    HTMX endpoint to render and save inline edits for a payslip row.
    Only the fields that are input-enabled in the table are editable.
    """

    payslip = get_object_or_404(Payslip, pk=payslip_id)
    pay_data = payslip.pay_head_data or {}
    if isinstance(pay_data, str):
        try:
            pay_data = json.loads(pay_data)
        except Exception:
            pay_data = {}
    
    # CRITICAL: Normalize pay_head_data structure for both imported and non-imported payslips
    # This ensures consistent behavior regardless of import status
    if not isinstance(pay_data, dict):
        pay_data = {}
    
    # Ensure allowances and deductions lists are properly initialized
    if 'allowances' not in pay_data or pay_data.get('allowances') is None:
        pay_data['allowances'] = []
    if 'pretax_deductions' not in pay_data or pay_data.get('pretax_deductions') is None:
        pay_data['pretax_deductions'] = []
    if 'posttax_deductions' not in pay_data or pay_data.get('posttax_deductions') is None:
        pay_data['posttax_deductions'] = []
    
    # Ensure allowances and pretax_deductions are lists (not other types)
    if not isinstance(pay_data.get('allowances'), list):
        pay_data['allowances'] = []
    if not isinstance(pay_data.get('pretax_deductions'), list):
        pay_data['pretax_deductions'] = []
    if not isinstance(pay_data.get('posttax_deductions'), list):
        pay_data['posttax_deductions'] = []

    def _get_allowance_amount(title: str) -> float:
        """
        Get allowance amount by title.
        Works for both imported and non-imported payslips.
        """
        title_lower = title.lower()
        allowances_list = pay_data.get("allowances", []) or []
        if not isinstance(allowances_list, list):
            allowances_list = []
        
        for item in allowances_list:
            name = str(
                item.get("title")
                or item.get("name")
                or item.get("pay_head_title")
                or ""
            ).lower()
            # CRITICAL: Handle variations of title (e.g., "advanced salary" vs "salary advance")
            if title_lower in name or name in title_lower:
                return float(item.get("amount") or item.get("value") or 0)  # type: ignore
        return 0.0

    def _get_pretax_amount(title: str) -> float:
        """
        Get pretax deduction amount by title.
        Works for both imported and non-imported payslips.
        """
        title_lower = title.lower()
        pretax_list = pay_data.get("pretax_deductions", []) or []
        if not isinstance(pretax_list, list):
            pretax_list = []
        
        for item in pretax_list:
            name = str(
                item.get("title")
                or item.get("name")
                or item.get("pay_head_title")
                or ""
            ).lower()
            # CRITICAL: Handle variations of title (e.g., "salary advance loan recovery" vs "advanced salary")
            if title_lower in name or name in title_lower:
                return float(item.get("amount") or item.get("value") or 0)  # type: ignore
        return 0.0

    # CRITICAL: Initialize form values consistently for both imported and non-imported payslips
    # This ensures the same functionality works regardless of import status
    initial = {
        "paid_days": round(float(pay_data.get("paid_days", 0)), 2),
        "basic_pay": round(float(pay_data.get("basic_pay", payslip.basic_pay or 0)), 2),
        "housing_allowance": round(float(pay_data.get("housing_allowance", payslip.housing_allowance or 0)), 2),
        "transport_allowance": round(float(pay_data.get("transport_allowance", payslip.transport_allowance or 0)), 2),
        "other_allowance": round(float(pay_data.get("other_allowance", payslip.other_allowance or 0)), 2),
        "loss_of_pay": round(float(pay_data.get("loss_of_pay", pay_data.get("lop", 0))), 2),
        # CRITICAL: For both imported and non-imported, check pay_head_data first, then allowances list
        "overtime": round(float(pay_data.get("overtime", _get_allowance_amount("overtime"))), 2),
        "pretax_advanced_salary": round(float(pay_data.get("salary_advance_loan_recovery", _get_pretax_amount("salary advance loan recovery"))), 2),
        "deduction": round(float(pay_data.get("deduction", payslip.deduction or 0)), 2),
        "allowance_advanced_salary": round(float(pay_data.get("salary_advance", _get_allowance_amount("advanced salary"))), 2),
        "bonus": round(float(pay_data.get("bonus", _get_allowance_amount("bonus"))), 2),
        "total_deductions": round(float(pay_data.get("total_deductions", payslip.deduction or 0)), 2),
    }

    form = PayslipInlineUpdateForm(request.POST or None, instance=payslip, initial=initial)

    def _upsert_item(items: list, title: str, amount: float):
        title_lower = title.lower()
        for item in items:
            name = str(
                item.get("title")
                or item.get("name")
                or item.get("pay_head_title")
                or ""
            ).lower()
            if name == title_lower:
                item["amount"] = round(float(amount), 2)
                item["value"] = round(float(amount), 2)
                item["total"] = round(float(amount), 2)
                return
        items.append({"title": title, "amount": round(float(amount), 2), "value": round(float(amount), 2), "total": round(float(amount), 2)})

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        
        # CRITICAL: Ensure allowances and pretax_deductions are lists for both imported and non-imported
        # Create copies to avoid modifying the original lists
        allowances = list(pay_data.get("allowances", []) or [])
        pretax = list(pay_data.get("pretax_deductions", []) or [])
        
        # Ensure they are lists (handle edge cases)
        if not isinstance(allowances, list):
            allowances = []
        if not isinstance(pretax, list):
            pretax = []

        # Upsert items into allowances and pretax_deductions (works for both imported and non-imported)
        _upsert_item(allowances, "Overtime", data["overtime"])
        _upsert_item(allowances, "Advanced Salary", data["allowance_advanced_salary"])
        _upsert_item(allowances, "Bonus", data["bonus"])
        # CRITICAL: Use "Salary Advance Loan Recovery" for deduction, NOT "Advanced Salary"
        _upsert_item(pretax, "Salary Advance Loan Recovery", data["pretax_advanced_salary"])

        # Update pay_data with normalized lists
        pay_data["allowances"] = allowances
        pay_data["pretax_deductions"] = pretax
        
        # Get original paid_days BEFORE updating pay_data
        original_pay_data = payslip.pay_head_data or {}
        if isinstance(original_pay_data, str):
            try:
                original_pay_data = json.loads(original_pay_data)
            except Exception:
                original_pay_data = {}
        original_paid_days = original_pay_data.get("paid_days")
        if original_paid_days is not None:
            try:
                original_paid_days = float(original_paid_days)
            except (ValueError, TypeError):
                original_paid_days = None
        
        # Get the new paid_days value from form
        paid_days = round(float(data["paid_days"]), 2)
        pay_data["paid_days"] = paid_days
        # CRITICAL: Save loss_of_pay to both "loss_of_pay" and "lop" fields for consistency
        loss_of_pay_saved = round(float(data["loss_of_pay"]), 2)
        pay_data["loss_of_pay"] = loss_of_pay_saved
        pay_data["lop"] = loss_of_pay_saved  # Also save to "lop" field for backward compatibility
        pay_data["total_deductions"] = round(float(data["total_deductions"]), 2)

        # CRITICAL: Recalculate Basic Pay based on Paid Days
        # For imported payslips: Basic Pay = (Monthly Basic Pay / Calendar Month Days) × Paid Days
        # For non-imported payslips: Basic Pay = (Contract Wage / Days in Period) × Paid Days
        basic_pay = data["basic_pay"]
        is_imported = pay_data.get("is_imported", False)
        days_in_period = 0
        if payslip.start_date and payslip.end_date:
            days_in_period = (payslip.end_date - payslip.start_date).days + 1
        
        # CRITICAL: Recalculate basic_pay when paid_days is provided and valid
        # Check if paid_days changed or if we need to recalculate for consistency
        should_recalculate = False
        if original_paid_days is not None:
            # Check if paid_days changed (with tolerance for floating point comparison)
            if abs(round(original_paid_days, 2) - paid_days) > 0.001:
                should_recalculate = True
        else:
            # No original paid_days, recalculate if we have necessary data
            should_recalculate = True
        
        # Also recalculate if basic_pay is 0 or invalid but we have valid paid_days
        if not should_recalculate and (basic_pay == 0 or basic_pay is None):
            should_recalculate = True
        
        # Recalculate basic_pay if needed and we have necessary data
        if should_recalculate and days_in_period > 0 and paid_days >= 0:
            if is_imported:
                # For imported payslips, use monthly_basic_pay from pay_head_data
                # Formula: Basic Pay = (Monthly Basic Pay / Calendar Month Days) × Paid Days
                monthly_basic_pay = pay_data.get("monthly_basic_pay", 0)
                if monthly_basic_pay == 0:
                    # Fallback to contract_wage if monthly_basic_pay not available
                    monthly_basic_pay = payslip.contract_wage or pay_data.get("contract_wage", 0)
                
                if monthly_basic_pay > 0:
                    # Use calendar month days (like in import process)
                    from calendar import monthrange
                    if payslip.start_date:
                        calendar_month_days = monthrange(payslip.start_date.year, payslip.start_date.month)[1]
                    else:
                        calendar_month_days = days_in_period
                    
                    if calendar_month_days > 0:
                        per_day_basic_pay = monthly_basic_pay / calendar_month_days
                        recalculated_basic_pay = round(per_day_basic_pay * paid_days, 2)
                        basic_pay = recalculated_basic_pay
                        data["basic_pay"] = basic_pay
            else:
                # For non-imported payslips, use contract_wage
                # Formula: Basic Pay = (Contract Wage / Days in Period) × Paid Days
                contract_wage = payslip.contract_wage or pay_data.get("contract_wage", 0)
                if contract_wage > 0:
                    per_day_wage = contract_wage / days_in_period
                    recalculated_basic_pay = round(per_day_wage * paid_days, 2)
                    basic_pay = recalculated_basic_pay
                    data["basic_pay"] = basic_pay

        # Save form fields to model (values are already rounded in form.clean())
        payslip = form.save(commit=False)

        # Recalculate gross and net with available numbers (round to 2 decimals)
        # CRITICAL: Gross Pay = Basic Pay + Housing Allowance + Transport Allowance + Other Allowance
        # (EXCLUDING Overtime, Salary Advance, Bonus - these are added to Net Pay only)
        fixed_allowances_total = round(
            data["housing_allowance"]
            + data["transport_allowance"]
            + data["other_allowance"],
            2
        )
        # Gross Pay includes Basic Pay + Fixed Allowances only
        gross_pay = round(basic_pay + fixed_allowances_total, 2)
        # CRITICAL: Calculate total_deductions from form inputs (Loss of Pay + Salary Advance Loan Recovery + Other Deductions)
        loss_of_pay_val = float(data.get("loss_of_pay", 0) or 0)
        salary_advance_loan_recovery_val = float(data.get("pretax_advanced_salary", 0) or 0)
        deduction_val = float(data.get("deduction", 0) or 0)
        total_deductions_calculated = round(loss_of_pay_val + salary_advance_loan_recovery_val + deduction_val, 2)
        # Net Pay = Gross Pay + Overtime + Salary Advance + Bonus - Total Deductions
        additional_allowances = round(
            data["overtime"]
            + data["allowance_advanced_salary"]
            + data["bonus"],
            2
        )
        net_pay = round(gross_pay + additional_allowances - total_deductions_calculated, 2)

        payslip.gross_pay = gross_pay
        payslip.net_pay = net_pay
        payslip.basic_pay = basic_pay

        # CRITICAL: Keep a copy of derived values in pay_head_data for downstream use.
        # This ensures consistency for both imported and non-imported payslips
        pay_data["gross_pay"] = gross_pay
        pay_data["net_pay"] = net_pay
        pay_data["housing_allowance"] = data["housing_allowance"]
        pay_data["transport_allowance"] = data["transport_allowance"]
        pay_data["other_allowance"] = data["other_allowance"]
        pay_data["bonus"] = data["bonus"]
        pay_data["overtime"] = data["overtime"]
        pay_data["deduction"] = data["deduction"]
        # CRITICAL: Save salary_advance and salary_advance_loan_recovery directly in pay_head_data for template access
        # This works for both imported and non-imported payslips
        pay_data["salary_advance"] = data["allowance_advanced_salary"]
        pay_data["salary_advance_loan_recovery"] = data["pretax_advanced_salary"]
        # CRITICAL: Ensure loss_of_pay is saved in pay_data (already saved above, but ensure it's present)
        # This ensures it's available for template rendering
        if "loss_of_pay" not in pay_data or pay_data.get("loss_of_pay") is None:
            pay_data["loss_of_pay"] = loss_of_pay_saved
        if "lop" not in pay_data or pay_data.get("lop") is None:
            pay_data["lop"] = loss_of_pay_saved
        # CRITICAL: Use calculated total_deductions (already calculated above)
        pay_data["total_deductions"] = total_deductions_calculated

        # Update basic_pay in pay_head_data (use recalculated value)
        pay_data["basic_pay"] = basic_pay
        
        # CRITICAL: Ensure is_imported flag is preserved
        # This ensures the payslip type is maintained after editing (for both imported and non-imported)
        # The flag was already checked earlier (line 1164), so preserve it
        if "is_imported" not in pay_data:
            pay_data["is_imported"] = is_imported
        
        payslip.pay_head_data = pay_data
        payslip.save()
        
        # Check if this is an HTMX request targeting the full table (like status update)
        view = request.POST.get("view")
        if view == "table" and request.headers.get("HX-Request"):
            from .component_views import filter_payslip
            messages.success(request, ("Payslip updated successfully"))
            # Return the full table HTML via filter_payslip
            qd = QueryDict(mutable=True)
            qd.update({"view": view})
            request.GET = qd
            return filter_payslip(request)
        
        # Reload payslip from DB to get fresh data
        payslip.refresh_from_db()
        
        # Process payslip through same logic as filter_payslip to ensure calculated fields
        pay_head_data = payslip.pay_head_data or {}
        if isinstance(pay_head_data, str):
            try:
                pay_head_data = json.loads(pay_head_data)
            except Exception:
                pay_head_data = {}
        
        # Calculate paid_days and unpaid_days similar to filter_payslip
        unpaid_days_value = pay_head_data.get("unpaid_days")
        if unpaid_days_value is None:
            unpaid_days_value = pay_head_data.get("lop_days")
        if unpaid_days_value is None:
            unpaid_days_value = 0
        
        try:
            unpaid_days = round(float(unpaid_days_value), 2)
        except (ValueError, TypeError):
            unpaid_days = 0
        
        # Calculate days in period
        days_in_period = 0
        if payslip.start_date and payslip.end_date:
            days_in_period = (payslip.end_date - payslip.start_date).days + 1
        
        # Extract and validate paid_days
        paid_days_value = pay_head_data.get("paid_days")
        if paid_days_value is None or paid_days_value == "":
            if days_in_period > 0 and unpaid_days > 0:
                paid_days_value = days_in_period - unpaid_days
            else:
                paid_days_value = days_in_period if days_in_period > 0 else 0
        else:
            try:
                paid_days_value = float(paid_days_value)
            except (ValueError, TypeError):
                paid_days_value = days_in_period if days_in_period > 0 else 0
        
        paid_days = round(paid_days_value, 2)
        
        # Check if this is an imported payslip
        is_imported = pay_head_data.get('is_imported', False)
        
        # CRITICAL: Extract loss_of_pay from pay_head_data - use saved value if it exists
        # Do NOT overwrite the value that was just saved during edit
        # The value was already saved at line 1210-1213, so preserve it here
        loss_of_pay_amount = pay_head_data.get("loss_of_pay")
        if loss_of_pay_amount is None:
            loss_of_pay_amount = pay_head_data.get("lop", 0)
        
        # CRITICAL: Ensure loss_of_pay is numeric and properly set
        try:
            loss_of_pay_amount = float(loss_of_pay_amount) if loss_of_pay_amount is not None else 0.0
        except (ValueError, TypeError):
            loss_of_pay_amount = 0.0
        
        # CRITICAL: Preserve loss_of_pay value - it was already saved during edit (line 1210-1213)
        # The value should already be in pay_head_data from the save operation above
        # Do NOT overwrite it - only use it if it exists, otherwise keep the saved value
        
        # Update pay_head_data with calculated values
        pay_head_data["paid_days"] = paid_days
        pay_head_data["unpaid_days"] = unpaid_days
        pay_head_data["lop_days"] = unpaid_days
        # CRITICAL: Preserve loss_of_pay value - it was already saved during edit
        # Always update both fields to ensure consistency (the value was saved above)
        pay_head_data["loss_of_pay"] = loss_of_pay_amount
        pay_head_data["lop"] = loss_of_pay_amount
        
        # Ensure total_deductions and deduction are present
        if "total_deductions" not in pay_head_data or pay_head_data.get("total_deductions") is None:
            pay_head_data["total_deductions"] = payslip.deduction or 0
        if "deduction" not in pay_head_data or pay_head_data.get("deduction") is None:
            pay_head_data["deduction"] = payslip.deduction or 0
        
        # Update payslip object attributes for template
        payslip.pay_head_data = pay_head_data
        payslip.calculated_paid_days = paid_days
        payslip.calculated_unpaid_days = unpaid_days
        payslip.calculated_loss_of_pay = loss_of_pay_amount
        
        # Render just the single row
        row_html = render_to_string(
            "payroll/payslip/payslip_table_row.html",
            {
                "payslip": payslip,
                "perms": {
                    "payroll": {
                        "change_payslip": request.user.has_perm("payroll.change_payslip"),
                        "add_payslip": request.user.has_perm("payroll.add_payslip"),
                        "delete_payslip": request.user.has_perm("payroll.delete_payslip"),
                    }
                }
            },
            request=request
        )
        
        # Set success message and render HTML
        messages.success(request, ("Payslip updated successfully"))
        messages_html = '<div class="oh-alert-container"><div class="oh-alert oh-alert--animated success">Payslip updated successfully</div></div>'
        
        # Return the row HTML with success message trigger
        response = HttpResponse(row_html)
        import json
        response["HX-Trigger"] = json.dumps({
            "showPayslipMessage": {
                "html": messages_html
            }
        })
        return response

    # If POST but form invalid, return row with error message
    if request.method == "POST":
        # Process payslip for template rendering even on validation error
        pay_head_data = payslip.pay_head_data or {}
        if isinstance(pay_head_data, str):
            try:
                pay_head_data = json.loads(pay_head_data)
            except Exception:
                pay_head_data = {}
        
        # Calculate fields for display
        unpaid_days_value = pay_head_data.get("unpaid_days") or pay_head_data.get("lop_days") or 0
        try:
            unpaid_days = round(float(unpaid_days_value), 2)
        except (ValueError, TypeError):
            unpaid_days = 0
        
        days_in_period = 0
        if payslip.start_date and payslip.end_date:
            days_in_period = (payslip.end_date - payslip.start_date).days + 1
        
        paid_days_value = pay_head_data.get("paid_days") or 0
        try:
            paid_days = round(float(paid_days_value), 2)
        except (ValueError, TypeError):
            paid_days = days_in_period if days_in_period > 0 else 0
        
        loss_of_pay_amount = pay_head_data.get("loss_of_pay") or pay_head_data.get("lop") or 0
        
        payslip.pay_head_data = pay_head_data
        payslip.calculated_paid_days = paid_days
        payslip.calculated_unpaid_days = unpaid_days
        payslip.calculated_loss_of_pay = loss_of_pay_amount
        
        # Return row HTML with error message
        row_html = render_to_string(
            "payroll/payslip/payslip_table_row.html",
            {
                "payslip": payslip,
                "perms": {
                    "payroll": {
                        "change_payslip": request.user.has_perm("payroll.change_payslip"),
                        "add_payslip": request.user.has_perm("payroll.add_payslip"),
                        "delete_payslip": request.user.has_perm("payroll.delete_payslip"),
                    }
                }
            },
            request=request
        )
        
        error_msg = _("Please correct the errors below.")
        if form.errors:
            error_msg = "; ".join([f"{field}: {', '.join(errors)}" for field, errors in form.errors.items()])
        
        response = HttpResponse(row_html)
        response["HX-Trigger"] = json.dumps({
            "showMessage": {
                "message": str(error_msg),
                "type": "error"
            }
        })
        return response
    
    # Display-only values for the modal (GET request - should not happen in inline edit)
    allowance_total_display = round(
        (payslip.housing_allowance or 0)
        + (payslip.transport_allowance or 0)
        + (payslip.other_allowance or 0)
        + _get_allowance_amount("overtime")
        + _get_allowance_amount("advanced salary")
        + _get_allowance_amount("bonus"),
        2
    )

    context = {
        "form": form,
        "payslip": payslip,
        "allowances_total": allowance_total_display,
        "success": False,
    }
    template = "payroll/payslip/payslip_inline_form.html"
    return render(request, template, context)

def update_payslip_status_no_id(request):
    """
    This method is used to update the payslip confirmation status
    """
    message = {"type": "success", "message": "Payslip status updated."}
    if request.method == "POST":
        ids_json = request.POST["ids"]
        ids = json.loads(ids_json)
        status = request.POST["status"]
        slips = Payslip.objects.filter(id__in=ids)
        slips.update(status=status)
        message = {
            "type": "success",
            "message": f"{slips.count()} Payslips status updated.",
        }
    return JsonResponse(message)


@login_required
@permission_required("payroll.change_payslip")
def bulk_update_payslip_status(request):
    """
    This method is used to update payslip status when generating payslip through
    generate payslip method
    """
    json_data = request.GET["json_data"]
    pay_data = json.loads(json_data)
    status = request.GET["status"]

    for json_entry in pay_data:
        data = json.loads(json_entry)
        emp_id = data["employee"]
        employee = Employee.objects.get(id=emp_id)

        payslip_kwargs = {
            "employee_id": employee,
            "start_date": data["start_date"],
            "end_date": data["end_date"],
        }
        filtered_instance = Payslip.objects.filter(**payslip_kwargs).first()
        instance = filtered_instance if filtered_instance is not None else Payslip()

        instance.employee_id = employee
        instance.start_date = data["start_date"]
        instance.end_date = data["end_date"]
        instance.status = status
        instance.basic_pay = data["basic_pay"]
        instance.contract_wage = data["contract_wage"]
        instance.gross_pay = data["gross_pay"]
        instance.deduction = data["total_deductions"]
        instance.net_pay = data["net_pay"]
        instance.pay_head_data = data
        instance.save()

    return JsonResponse({"type": "success", "message": "Payslips status updated"})


@login_required
def view_payslip_pdf(request, payslip_id):
    """
    PDF view for payslip - uses the same data preparation logic as view_created_payslip
    to ensure PDF output matches the summary view exactly.
    """
    from .component_views import filter_payslip

    if Payslip.objects.filter(id=payslip_id).exists():
        payslip = Payslip.objects.get(id=payslip_id)
        company = Company.objects.filter(hq=True).first()
        if (
            request.user.has_perm("payroll.view_payslip")
            or payslip.employee_id.employee_user_id == request.user
        ):
            user = request.user
            employee_user = user.employee_get

            # Get date format for PDF formatting
            info = EmployeeWorkInformation.objects.filter(employee_id=employee_user)
            if info.exists():
                for emp_info in info:
                    employee_company = emp_info.company_id
                company_name = Company.objects.filter(company=employee_company)
                emp_company = company_name.first()
                date_format = (
                    emp_company.date_format
                    if emp_company and emp_company.date_format
                    else "MMM. D, YYYY"
                )
            else:
                date_format = "MMM. D, YYYY"

            # CRITICAL: Use the exact same data preparation logic as view_created_payslip
            # Get pay_head_data - it might be a dict or JSON string
            pay_head_data = payslip.pay_head_data
            if isinstance(pay_head_data, str):
                try:
                    import json
                    pay_head_data = json.loads(pay_head_data)
                except (json.JSONDecodeError, TypeError):
                    pay_head_data = {}
            data = pay_head_data or {}
            
            # CRITICAL: Normalize allowances and deductions lists for template safety
            # This matches the normalization logic in view_created_payslip for consistency
            if not isinstance(data, dict):
                data = {}
            if 'allowances' not in data or data.get('allowances') is None:
                data['allowances'] = []
            if 'pretax_deductions' not in data or data.get('pretax_deductions') is None:
                data['pretax_deductions'] = []
            if 'posttax_deductions' not in data or data.get('posttax_deductions') is None:
                data['posttax_deductions'] = []
            
            # CRITICAL: Filter out "Salary Advance Loan Recovery" from pretax_deductions to prevent duplicate display
            # It's shown as a separate field, so don't show it in the pretax_deductions list
            def filter_salary_advance_loan_recovery_from_deductions(deduction_list):
                """Remove any deductions with 'Salary Advance Loan Recovery' in title - it's displayed as a separate field"""
                if not isinstance(deduction_list, list):
                    return []
                return [d for d in deduction_list if "salary advance loan recovery" not in d.get("title", "").lower()]
            
            # Apply filter to pretax_deductions
            if isinstance(data.get('pretax_deductions'), list):
                data['pretax_deductions'] = filter_salary_advance_loan_recovery_from_deductions(data['pretax_deductions'])
            
            data["employee"] = payslip.employee_id
            data["payslip"] = payslip
            data["json_data"] = data.copy()
            data["json_data"]["employee"] = getattr(payslip.employee_id, "id", None)
            data["json_data"]["payslip"] = payslip.id
            data["instance"] = payslip
            work_info = getattr(payslip.employee_id, "employee_work_info", None)

            if work_info:
                data["job_position"] = getattr(work_info, "job_position_id", None)
            else:
                data["job_position"] = None
            data["joining_date"] = getattr(work_info, "date_joining", "")
            
            # HORILLA-STYLE: Calculate salary based on start_date and end_date only
            # Get start and end dates from payslip model (primary source)
            start_date_obj = payslip.start_date
            end_date_obj = payslip.end_date
            
            # Fallback to pay_head_data if model dates are missing
            if not start_date_obj or not end_date_obj:
                start_date_str = data.get("start_date")
                end_date_str = data.get("end_date")
                if start_date_str:
                    try:
                        if isinstance(start_date_str, str):
                            start_date_obj = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                        else:
                            start_date_obj = start_date_str
                    except (ValueError, TypeError):
                        pass
                if end_date_str:
                    try:
                        if isinstance(end_date_str, str):
                            end_date_obj = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                        else:
                            end_date_obj = end_date_str
                    except (ValueError, TypeError):
                        pass
            
            # Calculate calendar days in period (start_date to end_date, inclusive)
            days_in_period = 0
            if start_date_obj and end_date_obj:
                days_in_period = (end_date_obj - start_date_obj).days + 1
            
            # Expose dates for template
            data["start_date"] = start_date_obj
            data["end_date"] = end_date_obj
            data["days_in_period"] = days_in_period
            
            # PDF-specific: Add formatted dates
            if start_date_obj and end_date_obj:
                month_start_name = start_date_obj.strftime("%B %d, %Y")
                month_end_name = end_date_obj.strftime("%B %d, %Y")

            # Formatted date for each format
                formatted_start_date = start_date_obj.strftime("%B %d, %Y")  # default
                formatted_end_date = end_date_obj.strftime("%B %d, %Y")  # default
            for format_name, format_string in HORILLA_DATE_FORMATS.items():
                if format_name == date_format:
                        formatted_start_date = start_date_obj.strftime(format_string)
                        formatted_end_date = end_date_obj.strftime(format_string)
                        break

            data["month_start_name"] = month_start_name
            data["month_end_name"] = month_end_name
            data["formatted_start_date"] = formatted_start_date
            data["formatted_end_date"] = formatted_end_date
            
            # Add payslip date (use end_date of payslip period, or current date if end_date not available)
            # Typically, payslip date is the end date of the payroll period
            if end_date_obj:
                data["payslip_date"] = end_date_obj
            else:
                data["payslip_date"] = date.today()
            
            # Check if this is an imported payslip FIRST - needed for paid_days calculation
            is_imported = data.get('is_imported', False) or payslip.pay_head_data.get('is_imported', False) if isinstance(payslip.pay_head_data, dict) else False
            
            # Extract unpaid_days first
            # HORILLA-STYLE: unpaid_days = 0 unless explicitly provided (NOT from attendance)
            unpaid_days_value = data.get("unpaid_days")
            if unpaid_days_value is None or unpaid_days_value == "":
                unpaid_days_value = data.get("lop_days")
            if unpaid_days_value is None or unpaid_days_value == "":
                # Default to 0 (no attendance-based calculation)
                unpaid_days_value = 0
            
            try:
                data["unpaid_days"] = round(float(unpaid_days_value), 2)
            except (ValueError, TypeError) as e:
                print(f"[VIEW_PAYSLIP_PDF] Error converting unpaid_days: {e}, value: {unpaid_days_value}")
                data["unpaid_days"] = 0
            
            # Extract paid_days and validate/correct if needed
            paid_days_value = data.get("paid_days")
            
            # CRITICAL: For imported payslips, use Excel paid_days if provided, otherwise calculate from date range
            if is_imported:
                # Try to convert paid_days_value to float first to check if it's valid
                paid_days_float = None
                if paid_days_value is not None and paid_days_value != "":
                    try:
                        paid_days_float = float(paid_days_value)
                    except (ValueError, TypeError) as e:
                        print(f"[VIEW_PAYSLIP_PDF] Error converting paid_days to float: {e}, value: {paid_days_value}")
                        paid_days_float = None
                
                if paid_days_float is not None and paid_days_float > 0:
                    # Excel provided paid_days - use it exactly
                    paid_days_value = round(paid_days_float, 2)
                    print(f"[VIEW_PAYSLIP_PDF] Imported payslip - using Excel paid_days: {paid_days_value}")
                else:
                    # Excel did NOT provide paid_days (or it's 0) - calculate as (End Date - Start Date) + 1
                    paid_days_value = round(float(days_in_period), 2) if days_in_period > 0 else 0
                    print(f"[VIEW_PAYSLIP_PDF] Imported payslip - paid_days not in Excel or is 0, calculated from date range: {paid_days_value} (days_in_period: {days_in_period})")
            else:
                # For non-imported payslips, if paid_days is missing or 0, calculate from total_days - unpaid_days
                if not paid_days_value or paid_days_value == 0:
                    if days_in_period > 0 and data["unpaid_days"] > 0:
                        paid_days_value = days_in_period - data["unpaid_days"]
                        print(f"[VIEW_PAYSLIP_PDF] Calculated paid_days from total_days ({days_in_period}) - unpaid_days ({data['unpaid_days']}) = {paid_days_value}")
                    else:
                        paid_days_value = days_in_period if days_in_period > 0 else 0
                else:
                    try:
                        paid_days_value = float(paid_days_value)
                        # Validate: paid_days + unpaid_days should not exceed total days
                        if days_in_period > 0 and data["unpaid_days"] > 0:
                            total_calculated = paid_days_value + data["unpaid_days"]
                            if total_calculated > days_in_period:
                                # Recalculate paid_days to ensure consistency
                                paid_days_value = days_in_period - data["unpaid_days"]
                                print(f"[VIEW_PAYSLIP_PDF] WARNING: paid_days + unpaid_days ({total_calculated}) > total_days ({days_in_period}). Recalculated paid_days to {paid_days_value}")
                    except (ValueError, TypeError) as e:
                        print(f"[VIEW_PAYSLIP_PDF] Error converting paid_days: {e}, value: {paid_days_value}")
                        if days_in_period > 0 and data["unpaid_days"] > 0:
                            paid_days_value = days_in_period - data["unpaid_days"]
                        else:
                            paid_days_value = 0
            
            try:
                data["paid_days"] = round(float(paid_days_value), 2)
            except (ValueError, TypeError) as e:
                print(f"[VIEW_PAYSLIP_PDF] Error rounding paid_days: {e}, value: {paid_days_value}")
                data["paid_days"] = 0
            
            data["basic_pay"] = data.get("basic_pay", payslip.basic_pay or 0)
            
            # is_imported already checked above for paid_days calculation
            data["is_imported"] = is_imported  # Set flag for template
            
            # Get contract to check LOP handling
            employee = payslip.employee_id
            contract = Contract.objects.filter(
                employee_id=employee, contract_status="active"
            ).first()
            
            # CRITICAL: Calculate loss_of_pay using the same logic as view_created_payslip (lines 2763-2820)
            # Do NOT fetch from pay_head_data - calculate it from contract_wage, days_in_period, and unpaid_days
            # This ensures consistency with payslip creation logic
            loss_of_pay_val = 0.0
            
            # Only calculate for non-imported payslips (imported payslips have LOP from Excel)
            if not is_imported:
                # First check if there's an explicit value in pay_head_data (from edit/create)
                if isinstance(pay_head_data, dict):
                    loss_of_pay_val = pay_head_data.get("loss_of_pay")
                    if loss_of_pay_val is None:
                        loss_of_pay_val = pay_head_data.get("lop")
                
                # If not in pay_head_data or is 0, calculate from contract_wage and unpaid_days
                if loss_of_pay_val is None or loss_of_pay_val == 0:
                    # Get contract_wage from payslip model or pay_head_data
                    contract_wage = payslip.contract_wage or data.get("contract_wage", 0)
                    if contract_wage == 0:
                        contract_wage = pay_head_data.get("contract_wage", 0) if isinstance(pay_head_data, dict) else 0
                    
                    # Get unpaid_days (already calculated above)
                    unpaid_days = data.get("unpaid_days", 0)
                    
                    # Calculate loss_of_pay: (contract_wage / days_in_period) * unpaid_days
                    # Same formula as filter_payslip (component_views.py:1340-1341)
                    # if contract_wage > 0 and days_in_period > 0 and unpaid_days > 0:
                    #     per_day_wage = contract_wage / days_in_period
                    #     loss_of_pay_val = round(per_day_wage * unpaid_days, 2)
                    #     print(f"[VIEW_PAYSLIP_PDF] Calculated loss_of_pay: ({contract_wage} / {days_in_period}) * {unpaid_days} = {loss_of_pay_val}")
                    # else:
                    #     loss_of_pay_val = 0.0
                else:
                    # Use the value from pay_head_data (from edit)
                    try:
                        loss_of_pay_val = round(float(loss_of_pay_val) if loss_of_pay_val is not None else 0.0, 2)
                    except (ValueError, TypeError):
                        loss_of_pay_val = 0.0
            else:
                # For imported payslips, get from pay_head_data (Excel value)
                if isinstance(pay_head_data, dict):
                    loss_of_pay_val = pay_head_data.get("loss_of_pay")
                    if loss_of_pay_val is None:
                        loss_of_pay_val = pay_head_data.get("lop", 0)
                if loss_of_pay_val is None:
                    loss_of_pay_val = 0.0
                try:
                    loss_of_pay_val = round(float(loss_of_pay_val) if loss_of_pay_val is not None else 0.0, 2)
                except (ValueError, TypeError):
                    loss_of_pay_val = 0.0
            
            # CRITICAL: Ensure loss_of_pay is always rounded to 2 decimal places
            loss_of_pay_val = round(float(loss_of_pay_val), 2) if loss_of_pay_val else 0.0
            
            # CRITICAL: Set loss_of_pay in data dict and save to pay_head_data
            data["loss_of_pay"] = loss_of_pay_val
            # Also save to pay_head_data to ensure it persists
            if isinstance(pay_head_data, dict):
                pay_head_data["loss_of_pay"] = loss_of_pay_val
                pay_head_data["lop"] = loss_of_pay_val
            
            print(f"[VIEW_PAYSLIP_PDF] Set loss_of_pay at line 1870: {loss_of_pay_val}, is_imported: {is_imported}, unpaid_days: {data.get('unpaid_days', 0)}, days_in_period: {days_in_period}")
            
            # CRITICAL: For imported payslips, always show LOP as deduction (part of Excel formula)
            # For non-imported payslips, check contract setting
            if is_imported:
                # Imported payslips: LOP is always shown as deduction (part of Excel formula)
                # Use the extracted value
                data["loss_of_pay"] = loss_of_pay_val
                data["loss_of_pay_deducted_from_basic"] = 0
            else:
                # For non-imported payslips, handle LOP based on contract setting
                # CRITICAL: Always save the calculated loss_of_pay_value to data["loss_of_pay"]
                # The contract setting only determines if it's shown as separate deduction or already in basic_pay
                # The value from line 1870 (calculated from contract_wage, days_in_period, unpaid_days) must be preserved
                data["loss_of_pay"] = loss_of_pay_val  # Always save the calculated value from line 1870
                
                # Check if LOP should be shown as deduction or already deducted from basic_pay
                if contract and hasattr(contract, 'deduct_leave_from_basic_pay'):
                    if contract.deduct_leave_from_basic_pay:
                        # LOP is already deducted from basic_pay, don't show as separate deduction
                        # But preserve the value in data["loss_of_pay"] for reference and calculations
                        data["loss_of_pay_deducted_from_basic"] = loss_of_pay_val
                        print(f"[VIEW_PAYSLIP_PDF] Non-imported payslip - LOP deducted from basic_pay, loss_of_pay_val: {loss_of_pay_val}, data['loss_of_pay']: {data['loss_of_pay']}")
                    else:
                        # LOP should be shown as separate deduction
                        # CRITICAL: Use the calculated value (already set above)
                        data["loss_of_pay_deducted_from_basic"] = 0.0
                        print(f"[VIEW_PAYSLIP_PDF] Non-imported payslip - LOP shown as deduction, loss_of_pay_val: {loss_of_pay_val}, data['loss_of_pay']: {data['loss_of_pay']}")
                else:
                    # No contract or setting not available - show as deduction (default behavior)
                    # CRITICAL: Use the calculated value (already set above)
                    data["loss_of_pay_deducted_from_basic"] = 0.0
                    print(f"[VIEW_PAYSLIP_PDF] Non-imported payslip - No contract, LOP shown as deduction, loss_of_pay_val: {loss_of_pay_val}, data['loss_of_pay']: {data['loss_of_pay']}")
            
            # CRITICAL: Save the final loss_of_pay value to pay_head_data to ensure it persists
            # This ensures the calculated/saved value from line 1870 is available for future views and edits
            if isinstance(pay_head_data, dict):
                pay_head_data["loss_of_pay"] = data.get("loss_of_pay", 0)
                pay_head_data["lop"] = data.get("loss_of_pay", 0)
                print(f"[VIEW_PAYSLIP_PDF] Saved loss_of_pay to pay_head_data: {data.get('loss_of_pay', 0)}")
            
            # Fetch allowances (bonuses) from database for this employee and payslip period
            # UNIFIED: Initialize db_allowances_list for both imported and non-imported payslips
            employee = payslip.employee_id
            # Use dates already calculated above (from data["start_date"] and data["end_date"])
            db_allowances_list = []  # Initialize for both cases
            
           
            # Query allowances that are specific to this employee and within the payslip period
            allowances_queryset = Allowance.objects.filter(
                specific_employees=employee,
                only_show_under_employee=True
            )
            
            # Filter by date if one_time_date is set and falls within payslip period
            if data.get("start_date") and data.get("end_date"):
                allowances_queryset = allowances_queryset.filter(
                    Q(one_time_date__isnull=True) | 
                    Q(one_time_date__gte=data["start_date"], one_time_date__lte=data["end_date"])
                )
            
            # Convert to list format expected by template
            allowances_list = []
            for allowance in allowances_queryset:
                # Calculate amount - use fixed amount or calculate based on rate
                amount = 0
                if allowance.is_fixed:
                    amount = float(allowance.amount or 0)
                else:
                    # For non-fixed, calculate based on rate and basic pay
                    basic_pay = data.get("basic_pay", payslip.basic_pay or 0)
                    rate = float(allowance.rate or 0)
                    amount = (basic_pay * rate) / 100
                
                if amount > 0:
                    allowances_list.append({
                        "title": allowance.title,
                        "amount": round(amount, 2),
                        "id": allowance.id
                            })
            
            data["allowances"] = allowances_list
            
            # CRITICAL: Update flags after allowances are set (for non-imported payslips)
            # Check if bonus, overtime, and salary_advance are already in allowances list
            bonus_in_allowances = any("bonus" in str(a.get("title", "")).lower() for a in allowances_list)
            overtime_in_allowances = any("overtime" in str(a.get("title", "")).lower() for a in allowances_list)
            salary_advance_in_allowances = any(
                "salary advance" in str(a.get("title", "")).lower() or 
                "advanced salary" in str(a.get("title", "")).lower() 
                for a in allowances_list
            )
            
            # Extract housing, transport, and other allowances from pay_head_data
            # CRITICAL: Always show contract components, even if 0 - fetch from contract if not in pay_head_data
            housing_allowance = data.get("housing_allowance", 0)
            transport_allowance = data.get("transport_allowance", 0)
            other_allowance = data.get("other_allowance", 0)
            
            # If values are missing or 0, try to get from contract to ensure all components are shown
            if (housing_allowance == 0 and transport_allowance == 0 and other_allowance == 0) or not is_imported:
                contract = Contract.objects.filter(
                    employee_id=employee, contract_status="active"
                ).first()
                if contract:
                    # Use contract values if pay_head_data doesn't have them or they're 0
                    if housing_allowance == 0:
                        housing_allowance = float(contract.housing_allowance or 0)
                    if transport_allowance == 0:
                        transport_allowance = float(contract.transport_allowance or 0)
                    if other_allowance == 0:
                        other_allowance = float(contract.other_allowance or 0)
            
            data["housing_allowance"] = housing_allowance
            data["transport_allowance"] = transport_allowance
            data["other_allowance"] = other_allowance
            
            # Debug: Log allowance values
            print(f"[VIEW_PAYSLIP_PDF] Contract Allowances - Housing: {housing_allowance}, Transport: {transport_allowance}, Other: {other_allowance}")
            
            # Start with basic pay
            basic_pay = float(data.get("basic_pay", payslip.basic_pay or 0))
            
            # Fetch deductions from database for this employee and payslip period
            deductions_queryset = Deduction.objects.filter(
                specific_employees=employee,
                only_show_under_employee=True
            )
            
            # Filter by date if one_time_date is set and falls within payslip period
            if data.get("start_date") and data.get("end_date"):
                deductions_queryset = deductions_queryset.filter(
                    Q(one_time_date__isnull=True) | 
                    Q(one_time_date__gte=data["start_date"], one_time_date__lte=data["end_date"])
                )
            
            # STEP 1: Collect basic_pay deductions for display (DO NOT apply again - already applied in payroll_calculation)
            # CRITICAL: basic_pay from payslip model already has deductions with update_compensation="basic_pay" applied
            # We only collect them for display purposes, not to deduct again
            basic_pay_deductions_list = []
            for deduction in deductions_queryset:
                if deduction.update_compensation == "basic_pay":
                    amount = 0
                    if deduction.is_fixed:
                        amount = float(deduction.amount or 0)
                    else:
                        # Use original basic_pay (before deductions) for rate calculation
                        # Get from payslip contract_wage or calculate from current basic_pay + deductions
                        original_basic_pay = payslip.contract_wage or basic_pay
                        rate = float(deduction.rate or 0)
                        amount = (original_basic_pay * rate) / 100
                    
                    if amount > 0:
                        basic_pay_deductions_list.append({
                            "title": deduction.title,
                            "amount": round(amount, 2),
                            "id": deduction.id,
                            "update_compensation": deduction.update_compensation
                        })
            
            # CRITICAL: Do NOT apply basic_pay deductions again - they're already in payslip.basic_pay
            # The basic_pay from payslip model already has these deductions applied via update_compensation_deduction
            data["basic_pay"] = basic_pay  # Use basic_pay as-is from payslip
            
            # STEP 2: Calculate gross pay
            # CRITICAL: Gross Pay = Basic Pay + Housing Allowance + Transport Allowance + Other Allowance + Overtime + Salary Advance + Bonus
            housing_allowance_val = float(data.get("housing_allowance", 0))
            transport_allowance_val = float(data.get("transport_allowance", 0))
            other_allowance_val = float(data.get("other_allowance", 0))
            
            # Extract Overtime, Salary Advance, Bonus, and Other Allowances from allowances_list
            overtime_val = 0
            salary_advance_val = 0
            bonus_val = 0
            other_allowances_total = 0  # CRITICAL: Total of all other allowances (not overtime, salary_advance, or bonus)
            
            for allowance in allowances_list:
                title_lower = allowance.get("title", "").lower()
                amount = allowance.get("amount", 0)
                if "overtime" in title_lower:
                    overtime_val += amount
                elif "salary advance" in title_lower or "advanced salary" in title_lower:
                    salary_advance_val += amount
                elif "bonus" in title_lower:
                    bonus_val += amount
                else:
                    # CRITICAL: Include all other allowances in gross pay (like 'ty' allowance)
                    other_allowances_total += amount
            
            # Also check direct fields in pay_head_data
            if not overtime_val:
                overtime_val = float(data.get("overtime", 0))
            if not salary_advance_val:
                salary_advance_val = float(data.get("salary_advance", 0))
            if not bonus_val:
                bonus_val = float(data.get("bonus", 0))
            
            # Update flags for template to know if these should be shown separately
            data["show_bonus_separately"] = bonus_val != 0 and not bonus_in_allowances
            data["show_overtime_separately"] = overtime_val != 0 and not overtime_in_allowances
            data["show_salary_advance_separately"] = salary_advance_val != 0 and not salary_advance_in_allowances
            
            # Set overtime, salary_advance, bonus in data dict for template
            data["overtime"] = round(overtime_val, 2)
            data["salary_advance"] = round(salary_advance_val, 2)
            data["bonus"] = round(bonus_val, 2)
            
            # CRITICAL: Calculate gross pay: Basic Pay + Housing + Transport + Other + All Dynamic Allowances
            # All Dynamic Allowances = Overtime + Salary Advance + Bonus + Other Allowances (like 'ty')
            gross_pay = round(
                basic_pay +
                housing_allowance_val + 
                transport_allowance_val + 
                other_allowance_val + 
                overtime_val + 
                salary_advance_val + 
                bonus_val + 
                other_allowances_total,  # CRITICAL: Include all other allowances
                2
            )
            
            print(f"[VIEW_PAYSLIP_PDF] Gross Pay Calculation: {basic_pay} + {housing_allowance_val} + {transport_allowance_val} + {other_allowance_val} + {overtime_val} + {salary_advance_val} + {bonus_val} + {other_allowances_total} (other allowances) = {gross_pay}")
            
            # STEP 3: Apply gross_pay deductions
            gross_pay_deductions_list = []
            gross_pay_deduction_total = 0
            for deduction in deductions_queryset:
                if deduction.update_compensation == "gross_pay":
                    amount = 0
                    if deduction.is_fixed:
                        amount = float(deduction.amount or 0)
                    else:
                        rate = float(deduction.rate or 0)
                        amount = (gross_pay * rate) / 100
                    
                    if amount > 0:
                        gross_pay_deduction_total += amount
                        gross_pay_deductions_list.append({
                            "title": deduction.title,
                            "amount": round(amount, 2),
                            "id": deduction.id,
                            "update_compensation": deduction.update_compensation
                        })
            
            # Apply gross_pay deductions
            gross_pay = round(gross_pay - gross_pay_deduction_total, 2)
            data["gross_pay"] = gross_pay
            
            # STEP 4: Calculate other deductions (pretax, post_tax, tax) - these don't update compensation
            pretax_deductions_list = []
            post_tax_deductions_list = []
            tax_deductions_list = []
            
            for deduction in deductions_queryset:
                # Skip deductions that update compensation (already handled)
                if deduction.update_compensation:
                    continue
                    
                # Calculate amount
                amount = 0
                if deduction.is_fixed:
                    amount = float(deduction.amount or 0)
                else:
                    if deduction.based_on == "basic_pay":
                        base_amount = basic_pay
                    elif deduction.based_on == "gross_pay":
                        base_amount = gross_pay
                    else:
                        base_amount = basic_pay
                    
                    rate = float(deduction.rate or 0)
                    amount = (base_amount * rate) / 100
                
                if amount > 0:
                    deduction_dict = {
                        "title": deduction.title,
                        "amount": round(amount, 2),
                        "id": deduction.id,
                        "update_compensation": deduction.update_compensation
                    }
                    
                    if deduction.is_pretax:
                        pretax_deductions_list.append(deduction_dict)
                    elif deduction.is_tax:
                        tax_deductions_list.append(deduction_dict)
                    else:
                        post_tax_deductions_list.append(deduction_dict)
            
            # Calculate net pay before net_pay deductions
            total_other_deductions = (
                sum(d.get("amount", 0) for d in pretax_deductions_list) +
                sum(d.get("amount", 0) for d in post_tax_deductions_list) +
                sum(d.get("amount", 0) for d in tax_deductions_list)
            )
            # CRITICAL: Only include LOP in deductions if it's NOT deducted from basic_pay
            # If contract.deduct_leave_from_basic_pay is True, LOP is already in basic_pay calculation
            lop_for_deduction = float(data.get("loss_of_pay", 0))
            net_pay = round(gross_pay - total_other_deductions - lop_for_deduction, 2)
            
            # STEP 5: Apply net_pay deductions
            net_deductions_list = []
            net_pay_deduction_total = 0
            for deduction in deductions_queryset:
                if deduction.update_compensation == "net_pay":
                    amount = 0
                    if deduction.is_fixed:
                        amount = float(deduction.amount or 0)
                    else:
                        rate = float(deduction.rate or 0)
                        amount = (net_pay * rate) / 100
                    
                    if amount > 0:
                        net_pay_deduction_total += amount
                        net_deductions_list.append({
                            "title": deduction.title,
                            "amount": round(amount, 2),
                            "id": deduction.id,
                            "update_compensation": deduction.update_compensation
                        })
            
            # Apply net_pay deductions
            net_pay = round(net_pay - net_pay_deduction_total, 2)
            data["net_pay"] = net_pay
            
            # Merge with deductions from pay_head_data if any (deduplicate by deduction ID and title)
            # CRITICAL: Deduplicate deductions to prevent showing the same deduction multiple times
            def deduplicate_deductions(new_list, existing_list):
                """Deduplicate deductions by ID and title, preferring new_list items"""
                existing_ids = {d.get("id") for d in existing_list if d.get("id")}
                existing_titles = {d.get("title", "").lower().strip() for d in existing_list if d.get("title")}
                # Add new deductions that don't exist in existing list (check both ID and title)
                for deduction in new_list:
                    deduction_id = deduction.get("id")
                    deduction_title = deduction.get("title", "").lower().strip()
                    
                    # Skip if already exists (by ID or by title)
                    if deduction_id and deduction_id in existing_ids:
                        continue
                    if deduction_title and deduction_title in existing_titles:
                        continue
                    
                    # Add if not duplicate
                    existing_list.append(deduction)
                    if deduction_id:
                        existing_ids.add(deduction_id)
                    if deduction_title:
                        existing_titles.add(deduction_title)
                return existing_list
            
            # CRITICAL: For basic_pay_deductions and gross_pay_deductions, start with empty list
            # These are compensation deductions that are already applied - we only need to show them once from database query
            # Don't merge with pay_head_data to avoid duplicates
            data["basic_pay_deductions"] = basic_pay_deductions_list
            data["gross_pay_deductions"] = gross_pay_deductions_list
            
            # CRITICAL: Filter out "Advanced Salary" from deduction lists - it should only be in allowances
            def filter_advanced_salary_from_deductions_pdf(deduction_list):
                """Remove any deductions with 'Advanced Salary' in title - it belongs in allowances, not deductions"""
                return [d for d in deduction_list if "advanced salary" not in d.get("title", "").lower()]
            
            # CRITICAL: Filter out "Salary Advance Loan Recovery" from pretax_deductions - it's displayed as a separate field
            def filter_salary_advance_loan_recovery_from_deductions_pdf(deduction_list):
                """Remove any deductions with 'Salary Advance Loan Recovery' in title - it's displayed as a separate field"""
                return [d for d in deduction_list if "salary advance loan recovery" not in d.get("title", "").lower()]
            
            # For other deductions, merge with pay_head_data (deduplicate) and filter
            pretax_merged = deduplicate_deductions(
                pretax_deductions_list, 
                data.get("pretax_deductions", [])
            )
            pretax_filtered = filter_advanced_salary_from_deductions_pdf(pretax_merged)
            data["pretax_deductions"] = filter_salary_advance_loan_recovery_from_deductions_pdf(pretax_filtered)
            
            post_tax_merged = deduplicate_deductions(
                post_tax_deductions_list, 
                data.get("post_tax_deductions", [])
            )
            data["post_tax_deductions"] = filter_advanced_salary_from_deductions_pdf(post_tax_merged)
            
            tax_merged = deduplicate_deductions(
                tax_deductions_list, 
                data.get("tax_deductions", [])
            )
            data["tax_deductions"] = filter_advanced_salary_from_deductions_pdf(tax_merged)
            
            net_merged = deduplicate_deductions(
                net_deductions_list, 
                data.get("net_deductions", [])
            )
            data["net_deductions"] = filter_advanced_salary_from_deductions_pdf(net_merged)
            
            # For imported payslips, use values directly from pay_head_data (already calculated in import)
            if is_imported:
                # Use Excel values directly - don't recalculate
                pay_head = payslip.pay_head_data or {}
                
                # CRITICAL: Merge bonuses that were added AFTER import with imported allowances
                # Start with imported allowances from pay_head_data (these include bonuses added via add_bonus)
                imported_allowances = pay_head.get("allowances", [])
                if not isinstance(imported_allowances, list):
                    imported_allowances = []
                
                # CRITICAL: Merge with database bonuses (from earlier code block - db_allowances_list)
                # This ensures bonuses added via add_bonus (stored in pay_head_data) AND bonuses from database are both included
                existing_bonus_titles = {a.get("title", "").lower() for a in imported_allowances if "bonus" in a.get("title", "").lower()}
                
                # Add bonuses from database that aren't already in imported_allowances
                for bonus in db_allowances_list:
                    bonus_title = bonus.get("title", "").lower()
                    if bonus_title not in existing_bonus_titles:
                        imported_allowances.append(bonus)
                        existing_bonus_titles.add(bonus_title)
                
                # CRITICAL: Also fetch bonuses from database directly to ensure we have the latest (added after import)
                # This is a safety check in case pay_head_data wasn't updated
                if data.get("start_date") and data.get("end_date"):
                    bonus_allowances_db = Allowance.objects.filter(
                        specific_employees=employee,
                        only_show_under_employee=True
                    ).filter(
                        Q(one_time_date__isnull=True) | 
                        Q(one_time_date__gte=data["start_date"], one_time_date__lte=data["end_date"])
                    )
                    
                    # Add bonuses from database that aren't already in imported_allowances
                    for allowance in bonus_allowances_db:
                        if "bonus" in allowance.title.lower():
                            bonus_title = allowance.title
                            if bonus_title.lower() not in existing_bonus_titles:
                                amount = 0
                                if allowance.is_fixed:
                                    amount = float(allowance.amount or 0)
                                else:
                                    basic_pay = float(data.get("basic_pay", payslip.basic_pay or 0))
                                    rate = float(allowance.rate or 0)
                                    amount = (basic_pay * rate) / 100
                                
                                if amount > 0:
                                    imported_allowances.append({
                                        "title": bonus_title,
                                        "amount": round(amount, 2),
                                        "id": allowance.id
                                    })
                                    existing_bonus_titles.add(bonus_title.lower())
                
                # CRITICAL: Also merge with db_allowances_list from earlier code block (if any)
                # This ensures bonuses fetched earlier are also included
                for bonus in db_allowances_list:
                    # Check if this bonus is not already in imported_allowances
                    bonus_title = bonus.get("title", "").lower()
                    if bonus_title not in existing_bonus_titles:
                        imported_allowances.append(bonus)
                        existing_bonus_titles.add(bonus_title)
                
                data["allowances"] = imported_allowances
                data["all_allowances"] = imported_allowances.copy()  # CRITICAL: Also update all_allowances to prevent DB values
                
                print(f"[VIEW_PAYSLIP_PDF] Imported allowances count: {len(imported_allowances)}, DB allowances count: {len(db_allowances_list)}")
                for allowance in imported_allowances:
                    print(f"[VIEW_PAYSLIP_PDF] Allowance: {allowance.get('title')} = {allowance.get('amount')}")
                
                # CRITICAL: Always show contract components, even if 0 - fetch from contract if not in pay_head_data
                housing_allowance = pay_head.get("housing_allowance", 0)
                transport_allowance = pay_head.get("transport_allowance", 0)
                other_allowance = pay_head.get("other_allowance", 0)
                
                # If values are missing or 0, try to get from contract to ensure all components are shown
                if (housing_allowance == 0 and transport_allowance == 0 and other_allowance == 0):
                    contract = Contract.objects.filter(
                        employee_id=employee, contract_status="active"
                    ).first()
                    if contract:
                        # Use contract values if pay_head_data doesn't have them or they're 0
                        if housing_allowance == 0:
                            housing_allowance = float(contract.housing_allowance or 0)
                        if transport_allowance == 0:
                            transport_allowance = float(contract.transport_allowance or 0)
                        if other_allowance == 0:
                            other_allowance = float(contract.other_allowance or 0)
                
                data["housing_allowance"] = housing_allowance
                data["transport_allowance"] = transport_allowance
                data["other_allowance"] = other_allowance
                data["basic_pay"] = pay_head.get("basic_pay", payslip.basic_pay or 0)
                
                # CRITICAL: Recalculate gross_pay to include bonuses added after import
                basic_pay = float(data["basic_pay"])
                housing = float(data["housing_allowance"])
                transport = float(data["transport_allowance"])
                other = float(data["other_allowance"])
                # Use imported_allowances (which includes bonuses from pay_head_data and database)
                bonus_total = sum(a.get("amount", 0) for a in imported_allowances if "bonus" in a.get("title", "").lower())
                
                # CRITICAL: Also check direct "bonus" field in pay_head_data if not in allowances list
                excel_bonus = float(pay_head.get("bonus", 0) or 0)
                if excel_bonus > 0 and bonus_total == 0:
                    # If there's a direct bonus field and no bonuses in allowances list, use it
                    bonus_total = excel_bonus
                elif excel_bonus > 0 and bonus_total > 0:
                    # If both exist, prefer allowances list (as it might include database bonuses)
                    # But ensure we don't double count - this case shouldn't happen, but just in case
                    pass
                
                # CRITICAL: Extract overtime and salary_advance from pay_head_data
                # These are separate fields, not in allowances list
                overtime = float(pay_head.get("overtime", 0) or 0)
                salary_advance = float(pay_head.get("salary_advance", 0) or 0)
                
                # CRITICAL: Recalculate gross pay to include ALL earning components
                # Gross Pay = Basic Pay + Housing + Transport + Other + Overtime + Salary Advance + Bonus
                gross_pay = round(basic_pay + housing + transport + other + overtime + salary_advance + bonus_total, 2)
                data["gross_pay"] = gross_pay
                
                # CRITICAL: Get deductions from database that were added AFTER import
                deductions_queryset = Deduction.objects.filter(
                    specific_employees=employee,
                    only_show_under_employee=True
                )
                if data.get("start_date") and data.get("end_date"):
                    deductions_queryset = deductions_queryset.filter(
                        Q(one_time_date__isnull=True) | 
                        Q(one_time_date__gte=data["start_date"], one_time_date__lte=data["end_date"])
                    )
                
                # Build database deductions list (excluding update_compensation deductions - those are already applied)
                db_deductions_list = []
                for deduction in deductions_queryset:
                    if not deduction.update_compensation:  # Only show non-compensation deductions
                        amount = 0
                        if deduction.is_fixed:
                            amount = float(deduction.amount or 0)
                        else:
                            base_amount = float(basic_pay) if deduction.based_on == "basic_pay" else float(gross_pay)
                            rate = float(deduction.rate or 0)
                            amount = (base_amount * rate) / 100
                        
                        if amount > 0:
                            db_deductions_list.append({
                                "title": deduction.title,
                                "amount": round(amount, 2),
                                "id": deduction.id,
                                "update_compensation": None
                            })
                
                # Recalculate net pay using Excel formula: (Gross Pay + Overtime + Salary Advance + Bonus) - (LOP + Loan Recovery + Deduction + DB Deductions)
                # Excel Formula: =(H3+M3+N3+O3)-(J3+K3+L3)
                # Where: H=Gross Pay, M=Overtime, N=salary_advance, O=bonus
                #        J=Loss of Pay, K=salary_advance_loan_recovery, L=Deduction
                lop = float(pay_head.get("loss_of_pay", pay_head.get("lop", 0)))
                loan_recovery = float(pay_head.get("salary_advance_loan_recovery", 0))
                deduction = float(pay_head.get("deduction", 0))
                overtime = float(pay_head.get("overtime", 0))
                salary_advance = float(pay_head.get("salary_advance", 0))
                excel_bonus = float(pay_head.get("bonus", 0))
                
                # CRITICAL: Calculate total bonus from imported_allowances (includes bonuses from add_bonus)
                # This ensures bonuses added via add_bonus are included in net pay calculation
                db_bonus_total = sum(a.get("amount", 0) for a in imported_allowances if "bonus" in a.get("title", "").lower())
                # Use database bonuses if available (from add_bonus), otherwise use Excel bonus
                total_bonus = db_bonus_total if db_bonus_total > 0 else excel_bonus
                
                # Calculate total database deductions (added after import)
                db_deduction_total = sum(d.get("amount", 0) for d in db_deductions_list)
                
                # CRITICAL: Net Pay calculation for imported payslips
                # Since Gross Pay now includes Overtime, Salary Advance, and Bonus, we don't add them again
                # Net Pay = Gross Pay - (LOP + Loan Recovery + Deduction + DB Deductions)
                net_pay = round(
                    gross_pay - (lop + loan_recovery + deduction + db_deduction_total),
                    2
                )
                data["net_pay"] = net_pay
                
                # Update total deductions to include database deductions
                total_deductions = round(lop + loan_recovery + deduction + db_deduction_total, 2)
                data["total_deductions"] = total_deductions
                
                # CRITICAL: Extract Excel-specific components for template display
                # CRITICAL: Set bonus to total_bonus (includes bonuses from add_bonus via imported_allowances)
                # The template will show bonuses from data["allowances"] list, but we also set bonus for backward compatibility
                data["overtime"] = overtime
                data["salary_advance"] = salary_advance
                data["bonus"] = total_bonus
                data["salary_advance_loan_recovery"] = loan_recovery
                data["deduction"] = deduction
                # CRITICAL: Ensure loss_of_pay is set for template display (for imported payslips)
                # Convert to float and round to 2 decimal places to ensure it's numeric and properly formatted
                try:
                    data["loss_of_pay"] = round(float(lop) if lop else 0.0, 2)
                except (ValueError, TypeError):
                    data["loss_of_pay"] = 0.0
                
                # CRITICAL: Merge database deductions with Excel deductions (deduplicate by ID)
                def deduplicate_deductions(new_list, existing_list):
                    """Deduplicate deductions by ID, preferring existing_list items"""
                    existing_ids = {d.get("id") for d in existing_list if d.get("id")}
                    # Add new deductions that don't exist in existing list
                    for deduction in new_list:
                        if deduction.get("id") not in existing_ids:
                            existing_list.append(deduction)
                            existing_ids.add(deduction.get("id"))
                    return existing_list
                
                # Start with Excel deductions from pay_head_data
                data["basic_pay_deductions"] = pay_head.get("basic_pay_deductions", [])
                data["gross_pay_deductions"] = pay_head.get("gross_pay_deductions", [])
                data["pretax_deductions"] = pay_head.get("pretax_deductions", [])
                data["post_tax_deductions"] = pay_head.get("post_tax_deductions", [])
                data["posttax_deductions"] = pay_head.get("posttax_deductions", [])
                data["tax_deductions"] = pay_head.get("tax_deductions", [])
                data["net_deductions"] = pay_head.get("net_deductions", [])
                
                # CRITICAL: Filter out "Advanced Salary" from deduction lists - it should only be in allowances
                def filter_advanced_salary_from_deductions(deduction_list):
                    """Remove any deductions with 'Advanced Salary' in title - it belongs in allowances, not deductions"""
                    return [d for d in deduction_list if "advanced salary" not in d.get("title", "").lower()]
                
                # CRITICAL: Filter out "Salary Advance Loan Recovery" from pretax_deductions - it's displayed as a separate field
                def filter_salary_advance_loan_recovery_from_deductions(deduction_list):
                    """Remove any deductions with 'Salary Advance Loan Recovery' in title - it's displayed as a separate field"""
                    return [d for d in deduction_list if "salary advance loan recovery" not in d.get("title", "").lower()]
                
                # Merge database deductions (added after import) - deduplicate and filter
                pretax_merged = deduplicate_deductions(
                    db_deductions_list,
                    data["pretax_deductions"]
                )
                pretax_filtered = filter_advanced_salary_from_deductions(pretax_merged)
                data["pretax_deductions"] = filter_salary_advance_loan_recovery_from_deductions(pretax_filtered)
                
                # Filter all deduction lists to remove "Advanced Salary"
                data["basic_pay_deductions"] = filter_advanced_salary_from_deductions(data["basic_pay_deductions"])
                data["gross_pay_deductions"] = filter_advanced_salary_from_deductions(data["gross_pay_deductions"])
                data["post_tax_deductions"] = filter_advanced_salary_from_deductions(data["post_tax_deductions"])
                data["tax_deductions"] = filter_advanced_salary_from_deductions(data["tax_deductions"])
                data["net_deductions"] = filter_advanced_salary_from_deductions(data["net_deductions"])
                
                # Use the deduction value from pay_head_data, not total_deductions
                data["deduction"] = pay_head.get("deduction", 0)
                
                # CRITICAL: Build all_deductions from all deduction lists (including merged DB deductions)
                all_deductions_list = []
                all_deductions_list.extend(data["basic_pay_deductions"])
                all_deductions_list.extend(data["gross_pay_deductions"])
                all_deductions_list.extend(data["pretax_deductions"])
                all_deductions_list.extend(data["post_tax_deductions"])
                all_deductions_list.extend(data["tax_deductions"])
                all_deductions_list.extend(data["net_deductions"])
                data["all_deductions"] = all_deductions_list
                
                # Update zipped_data with empty lists to prevent template from showing DB values
                equalize_lists_length(data["all_allowances"], data["all_deductions"])
                data["zipped_data"] = zip(data["all_allowances"], data["all_deductions"])
            else:
                # Calculate total deductions for display (EXCLUDE basic_pay_deductions - already deducted from basic_pay)
                # CRITICAL: basic_pay_deductions are already applied to basic_pay in payroll_calculation
                # Including them here would cause double deduction
                total_deductions_from_lists = (
                    sum(d.get("amount", 0) for d in data["pretax_deductions"]) +
                    sum(d.get("amount", 0) for d in data["post_tax_deductions"]) +
                    sum(d.get("amount", 0) for d in data["tax_deductions"]) +
                    sum(d.get("amount", 0) for d in data["net_deductions"]) +
                    sum(d.get("amount", 0) for d in data["gross_pay_deductions"])
                    # NOTE: basic_pay_deductions are NOT included - they're already in basic_pay calculation
                )
                
                # CRITICAL: Extract salary_advance_loan_recovery and deduction from pay_head_data for non-imported payslips
                # These values are set when creating payslip via "Create Payslip" and need to be displayed
                # Extract salary_advance_loan_recovery
                salary_advance_loan_recovery_val = data.get("salary_advance_loan_recovery", 0)
                try:
                    salary_advance_loan_recovery_val = float(salary_advance_loan_recovery_val) if salary_advance_loan_recovery_val else 0.0
                except (ValueError, TypeError):
                    salary_advance_loan_recovery_val = 0.0
                data["salary_advance_loan_recovery"] = salary_advance_loan_recovery_val
                
                # CRITICAL: Extract deduction from pay_head_data for non-imported payslips
                # This is a separate field (like in imported payslips), not the other_deductions_total
                deduction_val = data.get("deduction", 0)
                # If not in data, try to get from payslip model
                if not deduction_val or deduction_val == 0:
                    deduction_val = payslip.deduction or 0
                try:
                    deduction_val = float(deduction_val) if deduction_val else 0.0
                except (ValueError, TypeError):
                    deduction_val = 0.0
                data["deduction"] = deduction_val
                
                # CRITICAL: Get Loss of Pay - use the same extraction logic as above (lines 1826-1910)
                # Extract from pay_head_data directly to ensure we get the actual saved value
                # The value was already calculated and set at line 1870, so use that
                loss_of_pay_val = data.get("loss_of_pay", 0)
                # If not in data, recalculate using the same logic as above
                if loss_of_pay_val == 0 and not is_imported:
                    # Recalculate from contract_wage, days_in_period, and unpaid_days
                    contract_wage = payslip.contract_wage or data.get("contract_wage", 0)
                    if contract_wage == 0:
                        contract_wage = pay_head_data.get("contract_wage", 0) if isinstance(pay_head_data, dict) else 0
                    unpaid_days = data.get("unpaid_days", 0)
                    if contract_wage > 0 and days_in_period > 0 and unpaid_days > 0:
                        per_day_wage = contract_wage / days_in_period
                        loss_of_pay_val = round(per_day_wage * unpaid_days, 2)
                        data["loss_of_pay"] = loss_of_pay_val
                        print(f"[VIEW_PAYSLIP_PDF] Recalculated loss_of_pay for total_deductions: {loss_of_pay_val}")
                try:
                    loss_of_pay_val = round(float(loss_of_pay_val) if loss_of_pay_val else 0.0, 2)
                except (ValueError, TypeError):
                    loss_of_pay_val = 0.0
                # Ensure it's set in data (in case it wasn't set properly above) - always rounded to 2 decimal places
                data["loss_of_pay"] = round(float(loss_of_pay_val), 2) if loss_of_pay_val else 0.0
                
                # Total Deduction = Loss of Pay + Salary Advance Loan Recovery + Deduction + Other Deductions
                total_deductions_amount = round(loss_of_pay_val + salary_advance_loan_recovery_val + deduction_val + total_deductions_from_lists, 2)
                data["total_deductions"] = total_deductions_amount
                
                # CRITICAL: Recalculate Net Pay = Gross Pay - Total Deduction
                # This ensures Net Pay includes all deductions: loss_of_pay, salary_advance_loan_recovery, deduction, and other deductions
                net_pay = round(float(data.get("gross_pay", 0)) - total_deductions_amount, 2)
                data["net_pay"] = net_pay
                
                # Build all_allowances and all_deductions for template
                data["all_allowances"] = allowances_list.copy()
                all_deductions_list = []
                all_deductions_list.extend(data.get("basic_pay_deductions", []))
                all_deductions_list.extend(data.get("gross_pay_deductions", []))
                all_deductions_list.extend(data.get("pretax_deductions", []))
                all_deductions_list.extend(data.get("post_tax_deductions", []))
                all_deductions_list.extend(data.get("tax_deductions", []))
                all_deductions_list.extend(data.get("net_deductions", []))
                data["all_deductions"] = all_deductions_list
                equalize_lists_length(data["all_allowances"], data["all_deductions"])
                data["zipped_data"] = zip(data["all_allowances"], data["all_deductions"])
            
            # PDF-specific: Add additional context
            data["currency"] = PayrollSettings.objects.first().currency_symbol
            data["host"] = request.get_host()
            data["protocol"] = "https" if request.is_secure() else "http"
            data["company"] = company
            
            # Ensure federal_tax is available (from pay_head_data or default to 0)
            if "federal_tax" not in data:
                data["federal_tax"] = data.get("federal_tax", 0)

            print(f"[VIEW_PAYSLIP_PDF] Final values - paid_days: {data['paid_days']}, unpaid_days: {data['unpaid_days']}, loss_of_pay: {data['loss_of_pay']}, total_deductions: {data['total_deductions']}")
            print(f"[VIEW_PAYSLIP_PDF] Deduction lists - basic_pay: {len(data.get('basic_pay_deductions', []))}, gross_pay: {len(data.get('gross_pay_deductions', []))}, pretax: {len(data.get('pretax_deductions', []))}, post_tax: {len(data.get('post_tax_deductions', []))}, tax: {len(data.get('tax_deductions', []))}, net: {len(data.get('net_deductions', []))}")

            return render(request, "payroll/payslip/payslip_pdf.html", context=data)
        return redirect(filter_payslip)
    return render(request, "405.html")


@login_required
def view_created_payslip(request, payslip_id, **kwargs):
    """
    This method is used to view the saved payslips
    """
    payslip = Payslip.objects.filter(id=payslip_id).first()
    if payslip and (
        request.user.has_perm("payroll.view_payslip")
        or getattr(payslip.employee_id, "employee_user_id", None) == request.user
    ):

        # Get pay_head_data - it might be a dict or JSON string
        pay_head_data = payslip.pay_head_data
        if isinstance(pay_head_data, str):
            try:
                import json
                pay_head_data = json.loads(pay_head_data)
            except (json.JSONDecodeError, TypeError):
                pay_head_data = {}
        data = pay_head_data or {}
        
        # CRITICAL: Normalize allowances and deductions lists for template safety
        # This matches the normalization logic in view_payslip for consistency
        if not isinstance(data, dict):
            data = {}
        if 'allowances' not in data or data.get('allowances') is None:
            data['allowances'] = []
        if 'pretax_deductions' not in data or data.get('pretax_deductions') is None:
            data['pretax_deductions'] = []
        if 'posttax_deductions' not in data or data.get('posttax_deductions') is None:
            data['posttax_deductions'] = []
        
        # CRITICAL: Filter out "Salary Advance Loan Recovery" from pretax_deductions to prevent duplicate display
        # It's shown as a separate field, so don't show it in the pretax_deductions list
        def filter_salary_advance_loan_recovery_from_deductions(deduction_list):
            """Remove any deductions with 'Salary Advance Loan Recovery' in title - it's displayed as a separate field"""
            if not isinstance(deduction_list, list):
                return []
            return [d for d in deduction_list if "salary advance loan recovery" not in d.get("title", "").lower()]
        
        # Apply filter to pretax_deductions
        if isinstance(data.get('pretax_deductions'), list):
            data['pretax_deductions'] = filter_salary_advance_loan_recovery_from_deductions(data['pretax_deductions'])
        
        data["employee"] = payslip.employee_id
        data["payslip"] = payslip
        data["json_data"] = data.copy()
        data["json_data"]["employee"] = getattr(payslip.employee_id, "id", None)
        data["json_data"]["payslip"] = payslip.id
        data["instance"] = payslip
        work_info = getattr(payslip.employee_id, "employee_work_info", None)

        if work_info:
            data["job_position"] = getattr(work_info, "job_position_id", None)
        else:
            data["job_position"] = None
        data["joining_date"] = getattr(work_info, "date_joining", "")
        
        # Get start and end dates from payslip model (primary source)
        start_date_obj = payslip.start_date
        end_date_obj = payslip.end_date
        
        # Fallback to pay_head_data if model dates are missing
        if not start_date_obj or not end_date_obj:
            start_date_str = data.get("start_date")
            end_date_str = data.get("end_date")
            if start_date_str:
                try:
                    if isinstance(start_date_str, str):
                        start_date_obj = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                    else:
                        start_date_obj = start_date_str
                except (ValueError, TypeError):
                    pass
            if end_date_str:
                try:
                    if isinstance(end_date_str, str):
                        end_date_obj = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                    else:
                        end_date_obj = end_date_str
                except (ValueError, TypeError):
                    pass
        
        # Calculate calendar days in period (start_date to end_date, inclusive)
        days_in_period = 0
        if start_date_obj and end_date_obj:
            days_in_period = (end_date_obj - start_date_obj).days + 1
        
        # Expose dates for template
        data["start_date"] = start_date_obj
        data["end_date"] = end_date_obj
        data["days_in_period"] = days_in_period
        
        # Check if this is an imported payslip FIRST - needed for paid_days calculation
        is_imported = data.get('is_imported', False) or payslip.pay_head_data.get('is_imported', False) if isinstance(payslip.pay_head_data, dict) else False
        
        # UNIFIED: Initialize db_allowances_list early for both imported and non-imported payslips
        # This ensures it's always available when merging bonuses from database
        db_allowances_list = []
        employee = payslip.employee_id
        
        # Get Department - for imported payslips, use from pay_head_data, otherwise from employee_work_info
        department_name = ""
        if is_imported and isinstance(pay_head_data, dict):
            department_name = pay_head_data.get("department", "")
        if not department_name and work_info and work_info.department_id:
            department_name = work_info.department_id.department or ""
        data["department"] = department_name
        
        # Extract unpaid_days first
        # HORILLA-STYLE: unpaid_days = 0 unless explicitly provided (NOT from attendance)
        unpaid_days_value = data.get("unpaid_days")
        if unpaid_days_value is None or unpaid_days_value == "":
            unpaid_days_value = data.get("lop_days")
        if unpaid_days_value is None or unpaid_days_value == "":
            # Default to 0 (no attendance-based calculation)
            unpaid_days_value = 0
        
        try:
            data["unpaid_days"] = round(float(unpaid_days_value), 2)
        except (ValueError, TypeError) as e:
            print(f"[VIEW_PAYSLIP] Error converting unpaid_days: {e}, value: {unpaid_days_value}")
            data["unpaid_days"] = 0
        
        # Extract paid_days and validate/correct if needed
        paid_days_value = data.get("paid_days")
        
        # CRITICAL: For imported payslips, use Excel paid_days if provided, otherwise calculate from date range
        if is_imported:
            # Try to convert paid_days_value to float first to check if it's valid
            paid_days_float = None
            if paid_days_value is not None and paid_days_value != "":
                try:
                    paid_days_float = float(paid_days_value)
                except (ValueError, TypeError) as e:
                    print(f"[VIEW_PAYSLIP] Error converting paid_days to float: {e}, value: {paid_days_value}")
                    paid_days_float = None
            
            if paid_days_float is not None and paid_days_float > 0:
                # Excel provided paid_days - use it exactly
                paid_days_value = round(paid_days_float, 2)
                print(f"[VIEW_PAYSLIP] Imported payslip - using Excel paid_days: {paid_days_value}")
            else:
                # Excel did NOT provide paid_days (or it's 0) - calculate as (End Date - Start Date) + 1
                paid_days_value = round(float(days_in_period), 2) if days_in_period > 0 else 0
                print(f"[VIEW_PAYSLIP] Imported payslip - paid_days not in Excel or is 0, calculated from date range: {paid_days_value} (days_in_period: {days_in_period})")
        else:
            # For non-imported payslips, if paid_days is missing or 0, calculate from total_days - unpaid_days
            if not paid_days_value or paid_days_value == 0:
                if days_in_period > 0 and data["unpaid_days"] > 0:
                    paid_days_value = days_in_period - data["unpaid_days"]
                    print(f"[VIEW_PAYSLIP] Calculated paid_days from total_days ({days_in_period}) - unpaid_days ({data['unpaid_days']}) = {paid_days_value}")
                else:
                    paid_days_value = days_in_period if days_in_period > 0 else 0
            else:
                try:
                    paid_days_value = float(paid_days_value)
                    # Validate: paid_days + unpaid_days should not exceed total days
                    if days_in_period > 0 and data["unpaid_days"] > 0:
                        total_calculated = paid_days_value + data["unpaid_days"]
                        if total_calculated > days_in_period:
                            # Recalculate paid_days to ensure consistency
                            paid_days_value = days_in_period - data["unpaid_days"]
                            print(f"[VIEW_PAYSLIP] WARNING: paid_days + unpaid_days ({total_calculated}) > total_days ({days_in_period}). Recalculated paid_days to {paid_days_value}")
                except (ValueError, TypeError) as e:
                    print(f"[VIEW_PAYSLIP] Error converting paid_days: {e}, value: {paid_days_value}")
                    if days_in_period > 0 and data["unpaid_days"] > 0:
                        paid_days_value = days_in_period - data["unpaid_days"]
                    else:
                        paid_days_value = 0
        
        try:
            data["paid_days"] = round(float(paid_days_value), 2)
        except (ValueError, TypeError) as e:
            print(f"[VIEW_PAYSLIP] Error rounding paid_days: {e}, value: {paid_days_value}")
            data["paid_days"] = 0
        
        # CRITICAL: Ensure basic_pay, gross_pay, net_pay, and deduction are synced from model if missing
        # This ensures consistency with what's displayed in the payslip table
        data["basic_pay"] = data.get("basic_pay", payslip.basic_pay or 0)
        if "gross_pay" not in data or data.get("gross_pay") is None:
            data["gross_pay"] = payslip.gross_pay or 0
        if "net_pay" not in data or data.get("net_pay") is None:
            data["net_pay"] = payslip.net_pay or 0
        if "deduction" not in data or data.get("deduction") is None:
            data["deduction"] = payslip.deduction or 0
        if "total_deductions" not in data or data.get("total_deductions") is None:
            data["total_deductions"] = payslip.deduction or 0
        
        # CRITICAL: Calculate loss_of_pay using the same logic as filter_payslip (component_views.py:1338-1341)
        # Do NOT fetch from pay_head_data - calculate it from contract_wage, days_in_period, and unpaid_days
        # This ensures consistency with payslip creation logic
        loss_of_pay_val = 0.0
        
        # Only calculate for non-imported payslips (imported payslips have LOP from Excel)
        if not is_imported:
            # First check if there's an explicit value in pay_head_data (from edit/create)
            if isinstance(pay_head_data, dict):
                loss_of_pay_val = pay_head_data.get("loss_of_pay")
                if loss_of_pay_val is None:
                    loss_of_pay_val = pay_head_data.get("lop")
            
            # If not in pay_head_data or is 0, calculate from contract_wage and unpaid_days
            if loss_of_pay_val is None or loss_of_pay_val == 0:
                # Get contract_wage from payslip model or pay_head_data
                contract_wage = payslip.contract_wage or data.get("contract_wage", 0)
                if contract_wage == 0:
                    contract_wage = pay_head_data.get("contract_wage", 0) if isinstance(pay_head_data, dict) else 0
                
                # Get unpaid_days (already calculated above at line 2693)
                unpaid_days = data.get("unpaid_days", 0)
                
                # Calculate loss_of_pay: (contract_wage / days_in_period) * unpaid_days
                # Same formula as filter_payslip (component_views.py:1340-1341)
                # if contract_wage > 0 and days_in_period > 0 and unpaid_days > 0:
                #     per_day_wage = contract_wage / days_in_period
                #     loss_of_pay_val = round(per_day_wage * unpaid_days, 2)
                #     print(f"[VIEW_PAYSLIP] Calculated loss_of_pay: ({contract_wage} / {days_in_period}) * {unpaid_days} = {loss_of_pay_val}")
                # else:
                #     loss_of_pay_val = 0.0
            else:
                # Use the value from pay_head_data (from edit)
                try:
                    loss_of_pay_val = round(float(loss_of_pay_val) if loss_of_pay_val is not None else 0.0, 2)
                except (ValueError, TypeError):
                    loss_of_pay_val = 0.0
        else:
            # For imported payslips, get from pay_head_data (Excel value)
            if isinstance(pay_head_data, dict):
                loss_of_pay_val = pay_head_data.get("loss_of_pay")
                if loss_of_pay_val is None:
                    loss_of_pay_val = pay_head_data.get("lop", 0)
            if loss_of_pay_val is None:
                loss_of_pay_val = 0.0
            try:
                loss_of_pay_val = round(float(loss_of_pay_val) if loss_of_pay_val is not None else 0.0, 2)
            except (ValueError, TypeError):
                loss_of_pay_val = 0.0
        
        # CRITICAL: Ensure loss_of_pay is always rounded to 2 decimal places
        loss_of_pay_val = round(float(loss_of_pay_val), 2) if loss_of_pay_val else 0.0
        
        # CRITICAL: Set loss_of_pay in data dict and save to pay_head_data
        data["loss_of_pay"] = loss_of_pay_val
        # Also save to pay_head_data to ensure it persists
        if isinstance(pay_head_data, dict):
            pay_head_data["loss_of_pay"] = loss_of_pay_val
            pay_head_data["lop"] = loss_of_pay_val
        
        print(f"[VIEW_PAYSLIP] Set loss_of_pay at line 2805: {loss_of_pay_val}, is_imported: {is_imported}, unpaid_days: {data.get('unpaid_days', 0)}, days_in_period: {days_in_period}")
        
        # CRITICAL: Extract salary_advance_loan_recovery and deduction from pay_head_data for non-imported payslips
        # These are needed for display in the template (same as imported payslips)
        if "salary_advance_loan_recovery" not in data or data.get("salary_advance_loan_recovery") is None:
            data["salary_advance_loan_recovery"] = data.get("salary_advance_loan_recovery", 0)
        # Ensure it's a numeric value
        try:
            data["salary_advance_loan_recovery"] = float(data.get("salary_advance_loan_recovery", 0) or 0)
        except (ValueError, TypeError):
            data["salary_advance_loan_recovery"] = 0
        
        # CRITICAL: Extract deduction from pay_head_data for non-imported payslips
        # This is needed for display in the template (same as imported payslips)
        if "deduction" not in data or data.get("deduction") is None:
            # Try to get from payslip model as fallback
            data["deduction"] = payslip.deduction or 0
        # Ensure it's a numeric value
        try:
            data["deduction"] = float(data.get("deduction", 0) or 0)
        except (ValueError, TypeError):
            data["deduction"] = 0
        
        # CRITICAL: Ensure housing_allowance, transport_allowance, and other_allowance are synced from model if missing
        # This ensures consistency with what's displayed in the payslip table
        if "housing_allowance" not in data or data.get("housing_allowance") is None:
            data["housing_allowance"] = payslip.housing_allowance or 0
        if "transport_allowance" not in data or data.get("transport_allowance") is None:
            data["transport_allowance"] = payslip.transport_allowance or 0
        if "other_allowance" not in data or data.get("other_allowance") is None:
            data["other_allowance"] = payslip.other_allowance or 0
        
        # CRITICAL: Ensure overtime, salary_advance, and bonus are present and numeric
        # This matches the normalization logic in filter_payslip for consistency
        overtime = float(data.get("overtime", 0) or 0)
        salary_advance = float(data.get("salary_advance", 0) or 0)
        bonus = float(data.get("bonus", 0) or 0)
        
        # Also check allowances list for bonus if not in pay_head_data directly
        if bonus == 0 and isinstance(data.get("allowances"), list):
            for allowance in data.get("allowances", []):
                if isinstance(allowance, dict) and "bonus" in str(allowance.get("title", "")).lower():
                    bonus += float(allowance.get("amount", 0) or 0)
        
        data["overtime"] = overtime
        data["salary_advance"] = salary_advance
        data["bonus"] = bonus
        
        # CRITICAL: Check if bonus, overtime, and salary_advance are already in allowances list
        # This prevents duplicate display in the template
        allowances_list = data.get("allowances", [])
        if not isinstance(allowances_list, list):
            allowances_list = []
        
        bonus_in_allowances = any("bonus" in str(a.get("title", "")).lower() for a in allowances_list)
        overtime_in_allowances = any("overtime" in str(a.get("title", "")).lower() for a in allowances_list)
        salary_advance_in_allowances = any(
            "salary advance" in str(a.get("title", "")).lower() or 
            "advanced salary" in str(a.get("title", "")).lower() 
            for a in allowances_list
        )
        
        # Set flags for template to know if these should be shown separately
        data["show_bonus_separately"] = bonus and bonus != 0 and not bonus_in_allowances
        data["show_overtime_separately"] = overtime and overtime != 0 and not overtime_in_allowances
        data["show_salary_advance_separately"] = salary_advance and salary_advance != 0 and not salary_advance_in_allowances
        
        # CRITICAL: Recalculate gross_pay to include ALL earning components for imported payslips
        # This ensures consistency with filter_payslip view
        if is_imported:
            # For imported payslips, recalculate gross_pay to include overtime, salary_advance, and bonus
            basic_pay = float(data.get("basic_pay", payslip.basic_pay or 0))
            housing = float(data.get("housing_allowance", 0) or 0)
            transport = float(data.get("transport_allowance", 0) or 0)
            other = float(data.get("other_allowance", 0) or 0)
            
            # Gross Pay = Basic Pay + Housing + Transport + Other + Overtime + Salary Advance + Bonus
            recalculated_gross_pay = round(basic_pay + housing + transport + other + overtime + salary_advance + bonus, 2)
            data["gross_pay"] = recalculated_gross_pay
            
            # Update payslip model's gross_pay if it differs (but don't save to avoid unnecessary writes)
            if abs((payslip.gross_pay or 0) - recalculated_gross_pay) > 0.01:
                payslip.gross_pay = recalculated_gross_pay
        
        # Add payslip date (use end_date of payslip period, or current date if end_date not available)
        # Typically, payslip date is the end date of the payroll period
        if end_date_obj:
            data["payslip_date"] = end_date_obj
        else:
            from datetime import date as date_today
            data["payslip_date"] = date_today.today()
        
        # is_imported already checked above for paid_days calculation
        data["is_imported"] = is_imported  # Set flag for template
        
        # Get contract to check LOP handling
        employee = payslip.employee_id
        contract = Contract.objects.filter(
            employee_id=employee, contract_status="active"
        ).first()
        
        # CRITICAL: Extract loss_of_pay from pay_head_data - use the value that was already extracted above (line 2763-2778)
        # Do NOT overwrite it unless we need to handle contract settings
        # The value was already set in data["loss_of_pay"] at line 2774, so use that as the base
        # But also check pay_head_data directly to ensure we have the latest value
        loss_of_pay_value = data.get("loss_of_pay")
        if loss_of_pay_value is None:
            loss_of_pay_value = data.get("lop")
        # Also check pay_head_data directly (in case data dict was modified)
        if (loss_of_pay_value is None or loss_of_pay_value == 0) and isinstance(pay_head_data, dict):
            loss_of_pay_value = pay_head_data.get("loss_of_pay")
            if loss_of_pay_value is None:
                loss_of_pay_value = pay_head_data.get("lop")
        
        # CRITICAL: Ensure loss_of_pay_value is numeric
        try:
            if loss_of_pay_value is not None:
                loss_of_pay_value = float(loss_of_pay_value)
            else:
                loss_of_pay_value = 0.0
        except (ValueError, TypeError):
            loss_of_pay_value = 0.0
        
        # Debug: Log the extracted value
        print(f"[VIEW_PAYSLIP] Extracted loss_of_pay_value: {loss_of_pay_value}, is_imported: {is_imported}")
        
        # CRITICAL: For imported payslips, always show LOP as deduction (part of Excel formula)
        # For non-imported payslips, check contract setting
        if is_imported:
            # Imported payslips: LOP is always shown as deduction (part of Excel formula)
            # Use the extracted value
            data["loss_of_pay"] = loss_of_pay_value
            data["loss_of_pay_deducted_from_basic"] = 0
        else:
            # For non-imported payslips, handle LOP based on contract setting
            # CRITICAL: Preserve the value that was saved in pay_head_data (from create/edit)
            # Only adjust display based on contract setting, but don't lose the value
            
            # Check if LOP should be shown as deduction or already deducted from basic_pay
            # CRITICAL: Always save the calculated loss_of_pay_value to data["loss_of_pay"]
            # The contract setting only determines if it's shown as separate deduction or already in basic_pay
            data["loss_of_pay"] = loss_of_pay_value  # Always save the calculated value
            
            if contract and hasattr(contract, 'deduct_leave_from_basic_pay'):
                if contract.deduct_leave_from_basic_pay:
                    # LOP is already deducted from basic_pay, don't show as separate deduction
                    # But preserve the value in data["loss_of_pay"] for reference and calculations
                    data["loss_of_pay_deducted_from_basic"] = loss_of_pay_value
                    print(f"[VIEW_PAYSLIP] Non-imported payslip - LOP deducted from basic_pay, loss_of_pay_value: {loss_of_pay_value}, data['loss_of_pay']: {data['loss_of_pay']}")
                else:
                    # LOP should be shown as separate deduction
                    # CRITICAL: Use the calculated value (already set above)
                    data["loss_of_pay_deducted_from_basic"] = 0.0
                    print(f"[VIEW_PAYSLIP] Non-imported payslip - LOP shown as deduction, loss_of_pay_value: {loss_of_pay_value}, data['loss_of_pay']: {data['loss_of_pay']}")
            else:
                # No contract or setting not available - show as deduction (default behavior)
                # CRITICAL: Use the calculated value (already set above)
                data["loss_of_pay_deducted_from_basic"] = 0.0
                print(f"[VIEW_PAYSLIP] Non-imported payslip - No contract, LOP shown as deduction, loss_of_pay_value: {loss_of_pay_value}, data['loss_of_pay']: {data['loss_of_pay']}")
        
        # CRITICAL: Save the final loss_of_pay value to pay_head_data to ensure it persists
        # This ensures the calculated/saved value from line 2820 is available for future views and edits
        if isinstance(pay_head_data, dict):
            pay_head_data["loss_of_pay"] = data.get("loss_of_pay", 0)
            pay_head_data["lop"] = data.get("loss_of_pay", 0)
            print(f"[VIEW_PAYSLIP] Saved loss_of_pay to pay_head_data: {data.get('loss_of_pay', 0)}")
        
        # Fetch allowances (bonuses) from database for this employee and payslip period
        # SKIP if this is an imported payslip - only use Excel values
        employee = payslip.employee_id
        # Use dates already calculated above (from data["start_date"] and data["end_date"])
        
        # For imported payslips, use empty lists - don't fetch from database
       
            # Query allowances that are specific to this employee and within the payslip period
        allowances_queryset = Allowance.objects.filter(
            specific_employees=employee,
            only_show_under_employee=True
        )
    
        # Filter by date if one_time_date is set and falls within payslip period
        if data.get("start_date") and data.get("end_date"):
            allowances_queryset = allowances_queryset.filter(
                Q(one_time_date__isnull=True) | 
                Q(one_time_date__gte=data["start_date"], one_time_date__lte=data["end_date"])
            )
        
        # Convert to list format expected by template
        allowances_list = []
        for allowance in allowances_queryset:
            # Calculate amount - use fixed amount or calculate based on rate
            amount = 0
            if allowance.is_fixed:
                amount = float(allowance.amount or 0)
            else:
                # For non-fixed, calculate based on rate and basic pay
                basic_pay = data.get("basic_pay", payslip.basic_pay or 0)
                rate = float(allowance.rate or 0)
                amount = (basic_pay * rate) / 100
            
            if amount > 0:
                allowances_list.append({
                    "title": allowance.title,
                    "amount": round(amount, 2),
                    "id": allowance.id
                })
        
        data["allowances"] = allowances_list
        
        # CRITICAL: Update flags after allowances are set (for non-imported payslips)
        # Check if bonus, overtime, and salary_advance are already in allowances list
        bonus_in_allowances = any("bonus" in str(a.get("title", "")).lower() for a in allowances_list)
        overtime_in_allowances = any("overtime" in str(a.get("title", "")).lower() for a in allowances_list)
        salary_advance_in_allowances = any(
            "salary advance" in str(a.get("title", "")).lower() or 
            "advanced salary" in str(a.get("title", "")).lower() 
            for a in allowances_list
        )
        
        # Update flags for template to know if these should be shown separately
        bonus_val = float(data.get("bonus", 0) or 0)
        overtime_val = float(data.get("overtime", 0) or 0)
        salary_advance_val = float(data.get("salary_advance", 0) or 0)
        
        data["show_bonus_separately"] = bonus_val != 0 and not bonus_in_allowances
        data["show_overtime_separately"] = overtime_val != 0 and not overtime_in_allowances
        data["show_salary_advance_separately"] = salary_advance_val != 0 and not salary_advance_in_allowances
        
        # Extract housing, transport, and other allowances from pay_head_data
        # CRITICAL: Always show contract components, even if 0 - fetch from contract if not in pay_head_data
        housing_allowance = data.get("housing_allowance", 0)
        transport_allowance = data.get("transport_allowance", 0)
        other_allowance = data.get("other_allowance", 0)
        
        # If values are missing or 0, try to get from contract to ensure all components are shown
        if (housing_allowance == 0 and transport_allowance == 0 and other_allowance == 0) or not is_imported:
            contract = Contract.objects.filter(
                employee_id=employee, contract_status="active"
            ).first()
            if contract:
                # Use contract values if pay_head_data doesn't have them or they're 0
                if housing_allowance == 0:
                    housing_allowance = float(contract.housing_allowance or 0)
                if transport_allowance == 0:
                    transport_allowance = float(contract.transport_allowance or 0)
                if other_allowance == 0:
                    other_allowance = float(contract.other_allowance or 0)
            
            data["housing_allowance"] = housing_allowance
            data["transport_allowance"] = transport_allowance
            data["other_allowance"] = other_allowance
            
            # Debug: Log allowance values
            print(f"[VIEW_PAYSLIP] Contract Allowances - Housing: {housing_allowance}, Transport: {transport_allowance}, Other: {other_allowance}")
            
            # Start with basic pay
            basic_pay = float(data.get("basic_pay", payslip.basic_pay or 0))
            
            # Fetch deductions from database for this employee and payslip period
            deductions_queryset = Deduction.objects.filter(
                specific_employees=employee,
                only_show_under_employee=True
            )
            
            # Filter by date if one_time_date is set and falls within payslip period
            if data.get("start_date") and data.get("end_date"):
                deductions_queryset = deductions_queryset.filter(
                    Q(one_time_date__isnull=True) | 
                    Q(one_time_date__gte=data["start_date"], one_time_date__lte=data["end_date"])
                )
            
            # STEP 1: Collect basic_pay deductions for display (DO NOT apply again - already applied in payroll_calculation)
            # CRITICAL: basic_pay from payslip model already has deductions with update_compensation="basic_pay" applied
            # We only collect them for display purposes, not to deduct again
            basic_pay_deductions_list = []
            for deduction in deductions_queryset:
                if deduction.update_compensation == "basic_pay":
                    amount = 0
                    if deduction.is_fixed:
                        amount = float(deduction.amount or 0)
                    else:
                        # Use original basic_pay (before deductions) for rate calculation
                        # Get from payslip contract_wage or calculate from current basic_pay + deductions
                        original_basic_pay = payslip.contract_wage or basic_pay
                        rate = float(deduction.rate or 0)
                        amount = (original_basic_pay * rate) / 100
                    
                    if amount > 0:
                        basic_pay_deductions_list.append({
                            "title": deduction.title,
                            "amount": round(amount, 2),
                            "id": deduction.id,
                            "update_compensation": deduction.update_compensation
                        })
            
            # CRITICAL: Do NOT apply basic_pay deductions again - they're already in payslip.basic_pay
            # The basic_pay from payslip model already has these deductions applied via update_compensation_deduction
            data["basic_pay"] = basic_pay  # Use basic_pay as-is from payslip
            
            # STEP 2: Calculate gross pay
            # CRITICAL: Gross Pay = Basic Pay + Housing Allowance + Transport Allowance + Other Allowance + Overtime + Salary Advance + Bonus
            housing_allowance_val = float(data.get("housing_allowance", 0))
            transport_allowance_val = float(data.get("transport_allowance", 0))
            other_allowance_val = float(data.get("other_allowance", 0))
            
            # Extract Overtime, Salary Advance, Bonus, and Other Allowances from allowances_list
            overtime_val = 0
            salary_advance_val = 0
            bonus_val = 0
            other_allowances_total = 0  # CRITICAL: Total of all other allowances (not overtime, salary_advance, or bonus)
            
            for allowance in allowances_list:
                title_lower = allowance.get("title", "").lower()
                amount = allowance.get("amount", 0)
                if "overtime" in title_lower:
                    overtime_val += amount
                elif "salary advance" in title_lower or "advanced salary" in title_lower:
                    salary_advance_val += amount
                elif "bonus" in title_lower:
                    bonus_val += amount
                else:
                    # CRITICAL: Include all other allowances in gross pay (like 'ty' allowance)
                    other_allowances_total += amount
            
            # Also check direct fields in pay_head_data
            if not overtime_val:
                overtime_val = float(data.get("overtime", 0))
            if not salary_advance_val:
                salary_advance_val = float(data.get("salary_advance", 0))
            if not bonus_val:
                bonus_val = float(data.get("bonus", 0))
            
            # CRITICAL: Calculate gross pay: Basic Pay + Housing + Transport + Other + All Dynamic Allowances
            # All Dynamic Allowances = Overtime + Salary Advance + Bonus + Other Allowances (like 'ty')
            gross_pay = round(
                basic_pay +
                housing_allowance_val + 
                transport_allowance_val + 
                other_allowance_val + 
                overtime_val + 
                salary_advance_val + 
                bonus_val + 
                other_allowances_total,  # CRITICAL: Include all other allowances
                2
            )
            
            print(f"[VIEW_PAYSLIP] Gross Pay Calculation: {basic_pay} + {housing_allowance_val} + {transport_allowance_val} + {other_allowance_val} + {overtime_val} + {salary_advance_val} + {bonus_val} + {other_allowances_total} (other allowances) = {gross_pay}")
            
            # STEP 3: Apply gross_pay deductions
            gross_pay_deductions_list = []
            gross_pay_deduction_total = 0
            for deduction in deductions_queryset:
                if deduction.update_compensation == "gross_pay":
                    amount = 0
                    if deduction.is_fixed:
                        amount = float(deduction.amount or 0)
                    else:
                        rate = float(deduction.rate or 0)
                        amount = (gross_pay * rate) / 100
                    
                    if amount > 0:
                        gross_pay_deduction_total += amount
                        gross_pay_deductions_list.append({
                            "title": deduction.title,
                            "amount": round(amount, 2),
                            "id": deduction.id,
                            "update_compensation": deduction.update_compensation
                        })
            
            # Apply gross_pay deductions
            gross_pay = round(gross_pay - gross_pay_deduction_total, 2)
            data["gross_pay"] = gross_pay
            
            # STEP 4: Calculate other deductions (pretax, post_tax, tax) - these don't update compensation
            pretax_deductions_list = []
            post_tax_deductions_list = []
            tax_deductions_list = []
            
            for deduction in deductions_queryset:
                # Skip deductions that update compensation (already handled)
                if deduction.update_compensation:
                    continue
                    
                # Calculate amount
                amount = 0
                if deduction.is_fixed:
                    amount = float(deduction.amount or 0)
                else:
                    if deduction.based_on == "basic_pay":
                        base_amount = basic_pay
                    elif deduction.based_on == "gross_pay":
                        base_amount = gross_pay
                    else:
                        base_amount = basic_pay
                    
                    rate = float(deduction.rate or 0)
                    amount = (base_amount * rate) / 100
                
                if amount > 0:
                    deduction_dict = {
                        "title": deduction.title,
                        "amount": round(amount, 2),
                        "id": deduction.id,
                        "update_compensation": deduction.update_compensation
                    }
                    
                    if deduction.is_pretax:
                        pretax_deductions_list.append(deduction_dict)
                    elif deduction.is_tax:
                        tax_deductions_list.append(deduction_dict)
                    else:
                        post_tax_deductions_list.append(deduction_dict)
            
            # Calculate net pay before net_pay deductions
            total_other_deductions = (
                sum(d.get("amount", 0) for d in pretax_deductions_list) +
                sum(d.get("amount", 0) for d in post_tax_deductions_list) +
                sum(d.get("amount", 0) for d in tax_deductions_list)
            )
            # CRITICAL: Only include LOP in deductions if it's NOT deducted from basic_pay
            # If contract.deduct_leave_from_basic_pay is True, LOP is already in basic_pay calculation
            lop_for_deduction = float(data.get("loss_of_pay", 0))
            net_pay = round(gross_pay - total_other_deductions - lop_for_deduction, 2)
            
            # STEP 5: Apply net_pay deductions
            net_deductions_list = []
            net_pay_deduction_total = 0
            for deduction in deductions_queryset:
                if deduction.update_compensation == "net_pay":
                    amount = 0
                    if deduction.is_fixed:
                        amount = float(deduction.amount or 0)
                    else:
                        rate = float(deduction.rate or 0)
                        amount = (net_pay * rate) / 100
                    
                    if amount > 0:
                        net_pay_deduction_total += amount
                        net_deductions_list.append({
                            "title": deduction.title,
                            "amount": round(amount, 2),
                            "id": deduction.id,
                            "update_compensation": deduction.update_compensation
                        })
            
            # Apply net_pay deductions
            net_pay = round(net_pay - net_pay_deduction_total, 2)
            data["net_pay"] = net_pay
            
            # Merge with deductions from pay_head_data if any (deduplicate by deduction ID and title)
            # CRITICAL: Deduplicate deductions to prevent showing the same deduction multiple times
            def deduplicate_deductions(new_list, existing_list):
                """Deduplicate deductions by ID and title, preferring new_list items"""
                existing_ids = {d.get("id") for d in existing_list if d.get("id")}
                existing_titles = {d.get("title", "").lower().strip() for d in existing_list if d.get("title")}
                # Add new deductions that don't exist in existing list (check both ID and title)
                for deduction in new_list:
                    deduction_id = deduction.get("id")
                    deduction_title = deduction.get("title", "").lower().strip()
                    
                    # Skip if already exists (by ID or by title)
                    if deduction_id and deduction_id in existing_ids:
                        continue
                    if deduction_title and deduction_title in existing_titles:
                        continue
                    
                    # Add if not duplicate
                    existing_list.append(deduction)
                    if deduction_id:
                        existing_ids.add(deduction_id)
                    if deduction_title:
                        existing_titles.add(deduction_title)
                return existing_list
            
            # CRITICAL: For basic_pay_deductions and gross_pay_deductions, start with empty list
            # These are compensation deductions that are already applied - we only need to show them once from database query
            # Don't merge with pay_head_data to avoid duplicates
            data["basic_pay_deductions"] = basic_pay_deductions_list
            data["gross_pay_deductions"] = gross_pay_deductions_list
            
            # CRITICAL: Filter out "Advanced Salary" from deduction lists - it should only be in allowances
            def filter_advanced_salary_from_deductions(deduction_list):
                """Remove any deductions with 'Advanced Salary' in title - it belongs in allowances, not deductions"""
                return [d for d in deduction_list if "advanced salary" not in d.get("title", "").lower()]
            
            # For other deductions, merge with pay_head_data (deduplicate) and filter out "Advanced Salary" and "Salary Advance Loan Recovery"
            pretax_merged = deduplicate_deductions(
                pretax_deductions_list, 
                data.get("pretax_deductions", [])
            )
            pretax_filtered = filter_advanced_salary_from_deductions(pretax_merged)
            # CRITICAL: Also filter out "Salary Advance Loan Recovery" - it's shown as a separate field
            def filter_salary_advance_loan_recovery_from_deductions(deduction_list):
                """Remove any deductions with 'Salary Advance Loan Recovery' in title - it's displayed as a separate field"""
                return [d for d in deduction_list if "salary advance loan recovery" not in d.get("title", "").lower()]
            data["pretax_deductions"] = filter_salary_advance_loan_recovery_from_deductions(pretax_filtered)
            
            post_tax_merged = deduplicate_deductions(
                post_tax_deductions_list, 
                data.get("post_tax_deductions", [])
            )
            data["post_tax_deductions"] = filter_advanced_salary_from_deductions(post_tax_merged)
            
            tax_merged = deduplicate_deductions(
                tax_deductions_list, 
                data.get("tax_deductions", [])
            )
            data["tax_deductions"] = filter_advanced_salary_from_deductions(tax_merged)
            
            net_merged = deduplicate_deductions(
                net_deductions_list, 
                data.get("net_deductions", [])
            )
            data["net_deductions"] = filter_advanced_salary_from_deductions(net_merged)
            
            # CRITICAL: Store all component values in pay_head_data for table view (same as import functionality)
            # This ensures all values are visible in payslip_table.html
            # Create a clean dict with only JSON-serializable values
            existing_pay_head_data = payslip.pay_head_data or {}
            if isinstance(existing_pay_head_data, str):
                try:
                    import json
                    existing_pay_head_data = json.loads(existing_pay_head_data)
                except (json.JSONDecodeError, TypeError):
                    existing_pay_head_data = {}
            
            # Create clean pay_head_data with only JSON-serializable values
            # Copy existing values but ensure they're serializable
            pay_head_data_to_save = {}
            for key, value in existing_pay_head_data.items():
                # Only copy JSON-serializable values (skip Employee objects, etc.)
                if isinstance(value, (str, int, float, bool, type(None))):
                    pay_head_data_to_save[key] = value
                elif isinstance(value, (list, dict)):
                    # For lists and dicts, ensure they contain only serializable values
                    try:
                        import json
                        json.dumps(value)  # Test if serializable
                        pay_head_data_to_save[key] = value
                    except (TypeError, ValueError):
                        pass  # Skip non-serializable lists/dicts
            
            # Store all component values in pay_head_data for table view (ensure JSON-serializable)
            pay_head_data_to_save['bonus'] = round(bonus_val, 2)
            pay_head_data_to_save['overtime'] = round(overtime_val, 2)
            pay_head_data_to_save['salary_advance'] = round(salary_advance_val, 2)
            pay_head_data_to_save['gross_pay'] = gross_pay
            pay_head_data_to_save['net_pay'] = net_pay
            # Ensure allowances_list contains only serializable dicts (title, amount, id)
            clean_allowances_list = []
            for allowance in allowances_list:
                if isinstance(allowance, dict):
                    clean_allowance = {
                        'title': str(allowance.get('title', '')),
                        'amount': float(allowance.get('amount', 0))
                    }
                    # Only include id if it exists and is valid
                    allowance_id = allowance.get('id')
                    if allowance_id is not None:
                        try:
                            clean_allowance['id'] = int(allowance_id)
                        except (ValueError, TypeError):
                            pass  # Skip invalid id
                    clean_allowances_list.append(clean_allowance)
            pay_head_data_to_save['allowances'] = clean_allowances_list
            pay_head_data_to_save['housing_allowance'] = housing_allowance_val
            pay_head_data_to_save['transport_allowance'] = transport_allowance_val
            pay_head_data_to_save['other_allowance'] = other_allowance_val
            pay_head_data_to_save['basic_pay'] = basic_pay
            
            # Also update data dict for template (for individual payslip view)
            data['bonus'] = round(bonus_val, 2)
            data['overtime'] = round(overtime_val, 2)
            data['salary_advance'] = round(salary_advance_val, 2)
            
            # Update payslip model's pay_head_data to persist these values (for table view)
            # This ensures all component values are available in payslip_table.html (same as import functionality)
            payslip.pay_head_data = pay_head_data_to_save
            payslip.save(update_fields=['pay_head_data'])
        
        # UNIFIED LOGIC: For both imported and non-imported payslips, merge bonuses from database
        # This ensures bonuses added after import or creation are always included
        if is_imported:
            # Use Excel values directly - don't recalculate
            pay_head = payslip.pay_head_data or {}
            
            # CRITICAL: Merge bonuses that were added AFTER import with imported allowances
            # Start with imported allowances from pay_head_data (these include bonuses added via add_bonus)
            imported_allowances = pay_head.get("allowances", [])
            if not isinstance(imported_allowances, list):
                imported_allowances = []
            
            # UNIFIED: Populate db_allowances_list for imported payslips by fetching bonuses from database
            # This ensures bonuses added after import are included
            if data.get("start_date") and data.get("end_date"):
                bonus_allowances_db = Allowance.objects.filter(
                    specific_employees=employee,
                    only_show_under_employee=True
                ).filter(
                    Q(one_time_date__isnull=True) | 
                    Q(one_time_date__gte=data["start_date"], one_time_date__lte=data["end_date"])
                )
                
                # Populate db_allowances_list with bonuses from database
                for allowance in bonus_allowances_db:
                    if "bonus" in allowance.title.lower():
                        amount = 0
                        if allowance.is_fixed:
                            amount = float(allowance.amount or 0)
                        else:
                            basic_pay = float(data.get("basic_pay", payslip.basic_pay or 0))
                            rate = float(allowance.rate or 0)
                            amount = (basic_pay * rate) / 100
                        
                        if amount > 0:
                            db_allowances_list.append({
                                "title": allowance.title,
                                "amount": round(amount, 2),
                                "id": allowance.id
                            })
            
            # UNIFIED: db_allowances_list is now populated for imported payslips
            # CRITICAL: Merge with database bonuses (from db_allowances_list)
            # This ensures bonuses added via add_bonus (stored in pay_head_data) AND bonuses from database are both included
            existing_bonus_titles = {a.get("title", "").lower() for a in imported_allowances if "bonus" in a.get("title", "").lower()}
            
            # Add bonuses from db_allowances_list that aren't already in imported_allowances
            for bonus in db_allowances_list:
                bonus_title = bonus.get("title", "").lower()
                if bonus_title not in existing_bonus_titles:
                    imported_allowances.append(bonus)
                    existing_bonus_titles.add(bonus_title)
            
            data["allowances"] = imported_allowances
            data["all_allowances"] = imported_allowances.copy()  # CRITICAL: Also update all_allowances to prevent DB values
            
            print(f"[VIEW_PAYSLIP] Imported allowances count: {len(imported_allowances)}, DB allowances count: {len(db_allowances_list)}")
            
            # CRITICAL: Check if bonus, overtime, and salary_advance are already in allowances list
            # This prevents duplicate display in the template
            bonus_in_allowances = any("bonus" in str(a.get("title", "")).lower() for a in imported_allowances)
            overtime_in_allowances = any("overtime" in str(a.get("title", "")).lower() for a in imported_allowances)
            salary_advance_in_allowances = any(
                "salary advance" in str(a.get("title", "")).lower() or 
                "advanced salary" in str(a.get("title", "")).lower() 
                for a in imported_allowances
            )
            
            # Set flags for template to know if these should be shown separately
            bonus_val = float(data.get("bonus", 0) or 0)
            overtime_val = float(data.get("overtime", 0) or 0)
            salary_advance_val = float(data.get("salary_advance", 0) or 0)
            
            data["show_bonus_separately"] = bonus_val != 0 and not bonus_in_allowances
            data["show_overtime_separately"] = overtime_val != 0 and not overtime_in_allowances
            data["show_salary_advance_separately"] = salary_advance_val != 0 and not salary_advance_in_allowances
            for allowance in imported_allowances:
                print(f"[VIEW_PAYSLIP] Allowance: {allowance.get('title')} = {allowance.get('amount')}")
            
            # CRITICAL: Always show contract components, even if 0 - fetch from contract if not in pay_head_data
            housing_allowance = pay_head.get("housing_allowance", 0)
            transport_allowance = pay_head.get("transport_allowance", 0)
            other_allowance = pay_head.get("other_allowance", 0)
            
            # If values are missing or 0, try to get from contract to ensure all components are shown
            if (housing_allowance == 0 and transport_allowance == 0 and other_allowance == 0):
                contract = Contract.objects.filter(
                    employee_id=employee, contract_status="active"
                ).first()
                if contract:
                    # Use contract values if pay_head_data doesn't have them or they're 0
                    if housing_allowance == 0:
                        housing_allowance = float(contract.housing_allowance or 0)
                    if transport_allowance == 0:
                        transport_allowance = float(contract.transport_allowance or 0)
                    if other_allowance == 0:
                        other_allowance = float(contract.other_allowance or 0)
            
            data["housing_allowance"] = housing_allowance
            data["transport_allowance"] = transport_allowance
            data["other_allowance"] = other_allowance
            data["basic_pay"] = pay_head.get("basic_pay", payslip.basic_pay or 0)
            
            # CRITICAL: Recalculate gross_pay to include bonuses added after import
            basic_pay = float(data["basic_pay"])
            housing = float(data["housing_allowance"])
            transport = float(data["transport_allowance"])
            other = float(data["other_allowance"])
            # Use imported_allowances (which includes bonuses from pay_head_data and database)
            bonus_total = sum(a.get("amount", 0) for a in imported_allowances if "bonus" in a.get("title", "").lower())
            
            # CRITICAL: Also check direct "bonus" field in pay_head_data if not in allowances list
            excel_bonus = float(pay_head.get("bonus", 0) or 0)
            if excel_bonus > 0 and bonus_total == 0:
                # If there's a direct bonus field and no bonuses in allowances list, use it
                bonus_total = excel_bonus
            elif excel_bonus > 0 and bonus_total > 0:
                # If both exist, prefer allowances list (as it might include database bonuses)
                # But ensure we don't double count - this case shouldn't happen, but just in case
                pass
            
            # CRITICAL: For imported payslips, extract overtime and salary_advance from pay_head_data
            # These are separate fields, not in allowances list
            overtime = float(pay_head.get("overtime", 0) or 0)
            salary_advance = float(pay_head.get("salary_advance", 0) or 0)
            
            # CRITICAL: Recalculate gross pay to include ALL earning components
            # Gross Pay = Basic Pay + Housing Allowance + Transport Allowance + Other Allowance + Overtime + Salary Advance + Bonus
            gross_pay = round(basic_pay + housing + transport + other + overtime + salary_advance + bonus_total, 2)
            data["gross_pay"] = gross_pay
            
            # CRITICAL: Get deductions from database that were added AFTER import
            deductions_queryset = Deduction.objects.filter(
                specific_employees=employee,
                only_show_under_employee=True
            )
            if data.get("start_date") and data.get("end_date"):
                deductions_queryset = deductions_queryset.filter(
                    Q(one_time_date__isnull=True) | 
                    Q(one_time_date__gte=data["start_date"], one_time_date__lte=data["end_date"])
                )
            
            # Build database deductions list (excluding update_compensation deductions - those are already applied)
            db_deductions_list = []
            for deduction in deductions_queryset:
                if not deduction.update_compensation:  # Only show non-compensation deductions
                    amount = 0
                    if deduction.is_fixed:
                        amount = float(deduction.amount or 0)
                    else:
                        base_amount = float(basic_pay) if deduction.based_on == "basic_pay" else float(gross_pay)
                        rate = float(deduction.rate or 0)
                        amount = (base_amount * rate) / 100
                    
                    if amount > 0:
                        db_deductions_list.append({
                            "title": deduction.title,
                            "amount": round(amount, 2),
                            "id": deduction.id,
                            "update_compensation": None
                        })
            
            # Recalculate net pay using Excel formula: (Gross Pay + Overtime + Salary Advance + Bonus) - (LOP + Loan Recovery + Deduction + DB Deductions)
            # Excel Formula: =(H3+M3+N3+O3)-(J3+K3+L3)
            # Where: H=Gross Pay, M=Overtime, N=salary_advance, O=bonus
            #        J=Loss of Pay, K=salary_advance_loan_recovery, L=Deduction
            lop = float(pay_head.get("loss_of_pay", pay_head.get("lop", 0)))
            loan_recovery = float(pay_head.get("salary_advance_loan_recovery", 0))
            deduction = float(pay_head.get("deduction", 0))
            overtime = float(pay_head.get("overtime", 0))
            salary_advance = float(pay_head.get("salary_advance", 0))
            excel_bonus = float(pay_head.get("bonus", 0))
            
            # CRITICAL: Calculate total bonus from imported_allowances (includes bonuses from add_bonus)
            # This ensures bonuses added via add_bonus are included in net pay calculation
            db_bonus_total = sum(a.get("amount", 0) for a in imported_allowances if "bonus" in a.get("title", "").lower())
            # Use database bonuses if available (from add_bonus), otherwise use Excel bonus
            total_bonus = db_bonus_total if db_bonus_total > 0 else excel_bonus
            
            # Calculate total database deductions (added after import) - these are "Other Deductions"
            db_deduction_total = sum(d.get("amount", 0) for d in db_deductions_list)
            
            # CRITICAL: Total Deduction = Loss of Pay + Salary Advance Loan Recovery + Other Deductions
            total_deductions = round(lop + loan_recovery + deduction + db_deduction_total, 2)
            data["total_deductions"] = total_deductions
            
            # CRITICAL: Net Pay = Gross Pay - Total Deduction
            net_pay = round(gross_pay - total_deductions, 2)
            data["net_pay"] = net_pay
            
            # CRITICAL: Extract Excel-specific components for template display
            # CRITICAL: Set bonus to total_bonus (includes bonuses from add_bonus via imported_allowances)
            # The template will show bonuses from data["allowances"] list, but we also set bonus for backward compatibility
            data["overtime"] = overtime
            data["salary_advance"] = salary_advance
            data["bonus"] = total_bonus
            data["salary_advance_loan_recovery"] = loan_recovery
            data["deduction"] = deduction
            # CRITICAL: Ensure loss_of_pay is set for template display (for both imported and non-imported)
            # Convert to float and round to 2 decimal places to ensure it's numeric and properly formatted
            try:
                data["loss_of_pay"] = round(float(lop) if lop else 0.0, 2)
            except (ValueError, TypeError):
                data["loss_of_pay"] = 0.0
            
            # CRITICAL: Merge database deductions with Excel deductions (deduplicate by ID)
            def deduplicate_deductions(new_list, existing_list):
                """Deduplicate deductions by ID, preferring existing_list items"""
                existing_ids = {d.get("id") for d in existing_list if d.get("id")}
                # Add new deductions that don't exist in existing list
                for deduction in new_list:
                    if deduction.get("id") not in existing_ids:
                        existing_list.append(deduction)
                        existing_ids.add(deduction.get("id"))
                return existing_list
            
            # CRITICAL: Filter out "Advanced Salary" from deduction lists - it should only be in allowances
            def filter_advanced_salary_from_deductions(deduction_list):
                """Remove any deductions with 'Advanced Salary' in title - it belongs in allowances, not deductions"""
                return [d for d in deduction_list if "advanced salary" not in d.get("title", "").lower()]
            
            # CRITICAL: Filter out "Salary Advance Loan Recovery" from pretax_deductions - it's displayed as a separate field
            def filter_salary_advance_loan_recovery_from_deductions(deduction_list):
                """Remove any deductions with 'Salary Advance Loan Recovery' in title - it's displayed as a separate field"""
                return [d for d in deduction_list if "salary advance loan recovery" not in d.get("title", "").lower()]
            
            # Start with Excel deductions from pay_head_data
            data["basic_pay_deductions"] = pay_head.get("basic_pay_deductions", [])
            data["gross_pay_deductions"] = pay_head.get("gross_pay_deductions", [])
            data["pretax_deductions"] = pay_head.get("pretax_deductions", [])
            data["post_tax_deductions"] = pay_head.get("post_tax_deductions", [])
            data["posttax_deductions"] = pay_head.get("posttax_deductions", [])
            data["tax_deductions"] = pay_head.get("tax_deductions", [])
            data["net_deductions"] = pay_head.get("net_deductions", [])
            
            # Merge database deductions (added after import) - deduplicate and filter
            pretax_merged = deduplicate_deductions(
                db_deductions_list,
                data["pretax_deductions"]
            )
            pretax_filtered = filter_advanced_salary_from_deductions(pretax_merged)
            data["pretax_deductions"] = filter_salary_advance_loan_recovery_from_deductions(pretax_filtered)
            
            # Filter all deduction lists to remove "Advanced Salary"
            data["basic_pay_deductions"] = filter_advanced_salary_from_deductions(data["basic_pay_deductions"])
            data["gross_pay_deductions"] = filter_advanced_salary_from_deductions(data["gross_pay_deductions"])
            data["post_tax_deductions"] = filter_advanced_salary_from_deductions(data["post_tax_deductions"])
            data["tax_deductions"] = filter_advanced_salary_from_deductions(data["tax_deductions"])
            data["net_deductions"] = filter_advanced_salary_from_deductions(data["net_deductions"])
            
            # Use the deduction value from pay_head_data, not total_deductions
            data["deduction"] = pay_head.get("deduction", 0)
            
            # CRITICAL: Build all_deductions from all deduction lists (including merged DB deductions)
            all_deductions_list = []
            all_deductions_list.extend(data["basic_pay_deductions"])
            all_deductions_list.extend(data["gross_pay_deductions"])
            all_deductions_list.extend(data["pretax_deductions"])
            all_deductions_list.extend(data["post_tax_deductions"])
            all_deductions_list.extend(data["tax_deductions"])
            all_deductions_list.extend(data["net_deductions"])
            data["all_deductions"] = all_deductions_list
            
            # Update zipped_data with empty lists to prevent template from showing DB values
            equalize_lists_length(data["all_allowances"], data["all_deductions"])
            data["zipped_data"] = zip(data["all_allowances"], data["all_deductions"])
        else:
            # CRITICAL: Total Deduction = Loss of Pay + Salary Advance Loan Recovery + Other Deductions
            # Other Deductions include: pretax, post_tax, tax, net, and gross_pay deductions
            # EXCLUDE basic_pay_deductions - already deducted from basic_pay
            other_deductions_total = (
                sum(d.get("amount", 0) for d in data["pretax_deductions"]) +
                sum(d.get("amount", 0) for d in data["post_tax_deductions"]) +
                sum(d.get("amount", 0) for d in data["tax_deductions"]) +
                sum(d.get("amount", 0) for d in data["net_deductions"]) +
                sum(d.get("amount", 0) for d in data["gross_pay_deductions"])
                # NOTE: basic_pay_deductions are NOT included - they're already in basic_pay calculation
            )
            
            # CRITICAL: Extract salary_advance_loan_recovery and deduction from pay_head_data for non-imported payslips
            # These values are set when creating payslip via "Create Payslip" and need to be displayed
            # Extract salary_advance_loan_recovery
            salary_advance_loan_recovery_val = data.get("salary_advance_loan_recovery", 0)
            try:
                salary_advance_loan_recovery_val = float(salary_advance_loan_recovery_val) if salary_advance_loan_recovery_val else 0.0
            except (ValueError, TypeError):
                salary_advance_loan_recovery_val = 0.0
            data["salary_advance_loan_recovery"] = salary_advance_loan_recovery_val
            
            # CRITICAL: Extract deduction from pay_head_data for non-imported payslips
            # This is a separate field (like in imported payslips), not the other_deductions_total
            deduction_val = data.get("deduction", 0)
            # If not in data, try to get from payslip model
            if not deduction_val or deduction_val == 0:
                deduction_val = payslip.deduction or 0
            try:
                deduction_val = float(deduction_val) if deduction_val else 0.0
            except (ValueError, TypeError):
                deduction_val = 0.0
            data["deduction"] = deduction_val
            
            # Get Loss of Pay
            loss_of_pay = float(data.get("loss_of_pay", 0))
            print(f"[VIEW_PAYSLIP] Extracted loss_of_pay 3740: {loss_of_pay}")
            
            # Total Deduction = Loss of Pay + Salary Advance Loan Recovery + Deduction + Other Deductions
            total_deductions_amount = round(loss_of_pay + salary_advance_loan_recovery_val + deduction_val + other_deductions_total, 2)
            data["total_deductions"] = total_deductions_amount
            
            # Calculate Net Pay = Gross Pay - Total Deduction
            net_pay = round(float(data.get("gross_pay", 0)) - total_deductions_amount, 2)
            data["net_pay"] = net_pay
        
        # CRITICAL: Save calculated loss_of_pay back to payslip.pay_head_data to ensure it persists
        # This ensures the value is available for future views and edits
        if isinstance(pay_head_data, dict):
            pay_head_data["loss_of_pay"] = data.get("loss_of_pay", 0)
            pay_head_data["lop"] = data.get("loss_of_pay", 0)
            # Update payslip model's pay_head_data (but don't save to avoid unnecessary writes)
            # Only update if the value changed
            current_lop = payslip.pay_head_data.get("loss_of_pay") if isinstance(payslip.pay_head_data, dict) else None
            if current_lop != data.get("loss_of_pay", 0):
                payslip.pay_head_data = pay_head_data
                # Only save if the value actually changed
                payslip.save(update_fields=['pay_head_data'])
                print(f"[VIEW_PAYSLIP] Saved loss_of_pay to payslip.pay_head_data: {data.get('loss_of_pay', 0)}")
        
        print(f"[VIEW_PAYSLIP] Final values - paid_days: {data['paid_days']}, unpaid_days: {data['unpaid_days']}, loss_of_pay: {data['loss_of_pay']}, total_deductions: {data['total_deductions']}")
        print(f"[VIEW_PAYSLIP] Deduction lists - basic_pay: {len(data['basic_pay_deductions'])}, gross_pay: {len(data['gross_pay_deductions'])}, pretax: {len(data['pretax_deductions'])}, post_tax: {len(data['post_tax_deductions'])}, tax: {len(data['tax_deductions'])}, net: {len(data['net_deductions'])}")
        print(f"[VIEW_PAYSLIP] Allowances found: {len(allowances_list)}")
        
        # Ensure messages are available in template context (Django messages framework automatically provides this)
        # Import messages to ensure they're available
        from django.contrib import messages
        
        return render(request, "payroll/payslip/individual_payslip.html", data)
 
    return render(request, "404.html")

 

@login_required
@permission_required("payroll.delete_payslip")
def delete_payslip(request, payslip_id):
    """
    This method is used to delete payslip instances
    Args:
        payslip_id (int): Payslip model instance id
    """
    from .component_views import filter_payslip
    from payroll.models.models import Allowance, Deduction
    from django.db.models import Q

    try:
        payslip = Payslip.objects.get(id=payslip_id)
        employee = payslip.employee_id
        start_date = payslip.start_date
        end_date = payslip.end_date
        
        # CRITICAL: Delete all allowances linked to this payslip/employee/period
        # Delete allowances that are:
        # 1. Specific to this employee
        # 2. Only show under employee (manually added for this payslip)
        # 3. Have one_time_date within payslip period (if set)
        allowances_to_delete = Allowance.objects.filter(
            specific_employees=employee,
            only_show_under_employee=True
        )
        
        # Filter by date if one_time_date is set and falls within payslip period
        allowances_to_delete = allowances_to_delete.filter(
            Q(one_time_date__isnull=True) | 
            Q(one_time_date__gte=start_date, one_time_date__lte=end_date)
        )
        
        allowances_count = allowances_to_delete.count()
        if allowances_count > 0:
            allowances_to_delete.delete()
            print(f"[DELETE_PAYSLIP] Deleted {allowances_count} allowances linked to payslip {payslip_id}")
        
        # CRITICAL: Delete all deductions linked to this payslip/employee/period
        # Delete deductions that are:
        # 1. Specific to this employee
        # 2. Only show under employee (manually added for this payslip)
        # 3. Have one_time_date within payslip period (if set)
        deductions_to_delete = Deduction.objects.filter(
            specific_employees=employee,
            only_show_under_employee=True
        )
        
        # Filter by date if one_time_date is set and falls within payslip period
        deductions_to_delete = deductions_to_delete.filter(
            Q(one_time_date__isnull=True) | 
            Q(one_time_date__gte=start_date, one_time_date__lte=end_date)
        )
        
        deductions_count = deductions_to_delete.count()
        if deductions_count > 0:
            deductions_to_delete.delete()
            print(f"[DELETE_PAYSLIP] Deleted {deductions_count} deductions linked to payslip {payslip_id}")
        
        # Now delete the payslip itself
        payslip.delete()
        messages.success(request, _("Payslip and related allowances/deductions deleted"))
        
    except Payslip.DoesNotExist:
        messages.error(request, _("Payslip not found."))
    except ProtectedError:
        messages.error(request, _("Something went wrong"))
    except Exception as e:
        print(f"[DELETE_PAYSLIP] Error deleting payslip {payslip_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        messages.error(request, _("Error deleting payslip: {}").format(str(e)))
    
    # Handle HTMX requests - return table HTML directly
    if request.headers.get("HX-Request"):
        view_param = request.POST.get("view", request.GET.get("view", "table"))
        qd = QueryDict(mutable=True)
        qd.update({"view": view_param})
        if request.GET:
            for key, value in request.GET.items():
                if key != "view":
                    qd[key] = value
        request.GET = qd
        return filter_payslip(request)
    
    if not Payslip.objects.filter():
        return HttpResponse("<script>window.location.reload()</script>")
    return redirect(filter_payslip)



@login_required
@permission_required("payroll.add_contract")
def contract_info_initial(request):
    """
    This is an ajax method to return json response to auto fill the contract
    form fields
    """
    employee_id = request.GET.get("employee_id")
    work_info = EmployeeWorkInformation.objects.filter(employee_id=employee_id).first()

    # If no work_info found, return empty values
    if not work_info:
        return JsonResponse({
            "department": "",
            "job_position": "",
            "job_role": "",
            "shift": "",
            "work_type": "",
            "housing_allowance": "",
            "transport_allowance": "",
            "other_allowance": "",
            "wage": "",
            "contract_start_date": "",
            "contract_end_date": "",
        })

    response_data = {
        "department": work_info.department_id.id if work_info.department_id else "",
        "job_position": work_info.job_position_id.id if work_info.job_position_id else "",
        "job_role": work_info.job_role_id.id if work_info.job_role_id else "",
        "shift": work_info.shift_id.id if work_info.shift_id else "",
        "work_type": work_info.work_type_id.id if work_info.work_type_id else "",
        "wage": work_info.basic_salary or "",
        "housing_allowance": work_info.housing_allowance or "",
        "transport_allowance": work_info.transport_allowance or "",
        "other_allowance": work_info.other_allowance or "",
        "contract_start_date": work_info.date_joining or "",
        "contract_end_date": work_info.contract_end_date or "",
    }

    return JsonResponse(response_data)


@login_required
@permission_required("payroll.view_contract")
def view_payroll_dashboard(request):
    """
    Dashboard rendering views
    """
    from payroll.forms.forms import DashboardExport

    paid = Payslip.objects.filter(status="paid")
    posted = Payslip.objects.filter(status="confirmed")
    review_ongoing = Payslip.objects.filter(status="review_ongoing")
    draft = Payslip.objects.filter(status="draft")
    export_form = DashboardExport()
    context = {
        "paid": paid,
        "posted": posted,
        "review_ongoing": review_ongoing,
        "draft": draft,
        "export_form": export_form,
    }
    return render(request, "payroll/dashboard.html", context=context)


@login_required
def dashboard_employee_chart(request):
    """
    payroll dashboard employee chart data
    """

    date = request.GET.get("period")
    year = date.split("-")[0]
    month = date.split("-")[1]
    dataset = []

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if is_ajax and request.method == "GET":
        employee_list = Payslip.objects.filter(
            Q(start_date__month=month) & Q(start_date__year=year)
        )
        labels = []
        for employee in employee_list:
            labels.append(employee.employee_id)

        colors = [
            "rgba(255, 99, 132, 1)",  # Red
            "rgba(255, 206, 86, 1)",  # Yellow
            "rgba(54, 162, 235, 1)",  # Blue
            "rgba(75, 242, 182, 1)",  # green
        ]

        for choice, color in zip(Payslip.status_choices, colors):
            dataset.append(
                {
                    "label": choice[0],
                    "data": [],
                    "backgroundColor": color,
                }
            )

        employees = [employee.employee_id for employee in employee_list]

        employees = list(set(employees))
        total_pay_with_status = defaultdict(lambda: defaultdict(float))

        for label in employees:
            payslips = employee_list.filter(employee_id=label)
            for payslip in payslips:
                total_pay_with_status[payslip.status][label] += round(
                    payslip.net_pay, 2
                )

        for data in dataset:
            dataset_label = data["label"]
            data["data"] = [
                total_pay_with_status[dataset_label][label] for label in employees
            ]

        employee_label = []
        for employee in employees:
            employee_label.append(
                f"{employee.employee_first_name} {employee.employee_last_name}"
            )

        for value, choice in zip(dataset, Payslip.status_choices):
            if value["label"] == choice[0]:
                value["label"] = choice[1]

        list_of_employees = list(
            Employee.objects.values_list(
                "id", "employee_first_name", "employee_last_name"
            )
        )
        response = {
            "dataset": dataset,
            "labels": employee_label,
            "employees": list_of_employees,
            "message": _("No payslips generated for this month."),
        }
        return JsonResponse(response)


def payslip_details(request):
    """
    payroll dashboard payslip details data
    """

    date = request.GET.get("period")
    year = date.split("-")[0]
    month = date.split("-")[1]
    employee_list = []
    employee_list = Payslip.objects.filter(
        Q(start_date__month=month) & Q(start_date__year=year)
    )
    total_amount = 0
    for employee in employee_list:
        total_amount += employee.net_pay

    response = {
        "no_of_emp": len(employee_list),
        "total_amount": round(total_amount, 2),
    }
    return JsonResponse(response)


@login_required
def dashboard_department_chart(request):
    """
    payroll dashboard department chart data
    """

    date = request.GET.get("period")
    year = date.split("-")[0]
    month = date.split("-")[1]
    dataset = [
        {
            "label": "",
            "data": [],
            "backgroundColor": ["#8de5b3", "#f0a8a6", "#8ed1f7", "#f8e08e", "#c2c7cc"],
        }
    ]
    department = []
    department_total = []

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if is_ajax and request.method == "GET":
        employee_list = Payslip.objects.filter(
            Q(start_date__month=month) & Q(start_date__year=year)
        )

        for employee in employee_list:
            department.append(
                employee.employee_id.employee_work_info.department_id.department
            )

        department = list(set(department))
        for depart in department:
            department_total.append({"department": depart, "amount": 0})

        for employee in employee_list:
            employee_department = (
                employee.employee_id.employee_work_info.department_id.department
            )

            for depart in department_total:
                if depart["department"] == employee_department:
                    depart["amount"] += round(employee.net_pay, 2)

        colors = generate_colors(len(department))

        dataset = [
            {
                "label": "",
                "data": [],
                "backgroundColor": colors,
            }
        ]

        for depart_total, depart in zip(department_total, department):
            if depart == depart_total["department"]:
                dataset[0]["data"].append(depart_total["amount"])

        response = {
            "dataset": dataset,
            "labels": department,
            "department_total": department_total,
            "message": _("No payslips generated for this month."),
        }
        return JsonResponse(response)


def contract_ending(request):
    """
    payroll dashboard contract ending details data
    """

    date = request.GET.get("period")
    month = date.split("-")[1]
    year = date.split("-")[0]

    if request.GET.get("initialLoad") == "true":
        if month == "12":
            month = 0
            year = int(year) + 1

        contract_end = Contract.objects.filter(
            contract_end_date__month=int(month) + 1, contract_end_date__year=int(year)
        )
    else:
        contract_end = Contract.objects.filter(
            contract_end_date__month=int(month), contract_end_date__year=int(year)
        )

    ending_contract = []
    for contract in contract_end:
        ending_contract.append(
            {"contract_name": contract.contract_name, "contract_id": contract.id}
        )

    response = {
        "contract_end": ending_contract,
        "message": _("No contracts ending this month"),
    }
    return JsonResponse(response)


def payslip_export(request):
    """
    payroll dashboard exporting to excell data

    Args:
    - request (HttpRequest): The HTTP request object.
    - contract_id (int): The ID of the contract to view.

    """

    start_date = request.POST.get("start_date")
    end_date = request.POST.get("end_date")
    employee = request.POST.getlist("employees")
    status = request.POST.get("status")
    contributions = (
        request.POST.getlist("contributions")
        if request.POST.getlist("contributions")
        else get_active_employees(None)["get_active_employees"].values_list(
            "id", flat=True
        )
    )
    department = []
    total_amount = 0

    table1_data = []
    table2_data = []
    table3_data = []
    table4_data = []
    table5_data = []

    employee_payslip_list = Payslip.objects.all()

    if start_date:
        employee_payslip_list = employee_payslip_list.filter(start_date__gte=start_date)

    if end_date:
        employee_payslip_list = employee_payslip_list.filter(end_date__lte=end_date)

    if employee:
        employee_payslip_list = employee_payslip_list.filter(employee_id__in=employee)

    if status:
        employee_payslip_list = employee_payslip_list.filter(status=status)

    for employ in contributions:
        payslips = Payslip.objects.filter(employee_id__id=employ)
        if end_date:
            payslips = Payslip.objects.filter(
                employee_id__id=employ, end_date__lte=end_date
            )
        if start_date:
            payslips = Payslip.objects.filter(
                employee_id__id=employ, start_date__gte=start_date
            )
            if end_date:
                payslips = payslips.filter(end_date__lte=end_date)
        pay_heads = payslips.values_list("pay_head_data", flat=True)
        # contribution_deductions = []
        deductions = []
        for head in pay_heads:
            for deduction in head["gross_pay_deductions"]:
                if deduction.get("deduction_id"):
                    deductions.append(deduction)
            for deduction in head["basic_pay_deductions"]:
                if deduction.get("deduction_id"):
                    deductions.append(deduction)
            for deduction in head["pretax_deductions"]:
                if deduction.get("deduction_id"):
                    deductions.append(deduction)
            for deduction in head["post_tax_deductions"]:
                if deduction.get("deduction_id"):
                    deductions.append(deduction)
            for deduction in head["tax_deductions"]:
                if deduction.get("deduction_id"):
                    deductions.append(deduction)
            for deduction in head["net_deductions"]:
                deductions.append(deduction)

        deductions.sort(key=lambda x: x["deduction_id"])
        grouped_deductions = {
            key: list(group)
            for key, group in groupby(deductions, key=lambda x: x["deduction_id"])
        }

        for deduction_id, group in grouped_deductions.items():
            employee_contribution = sum(item["amount"] for item in group)
            try:
                employer_contribution = sum(
                    item["employer_contribution_amount"] for item in group
                )
            except:
                employer_contribution = 0
            if employer_contribution > 0:
                table5_data.append(
                    {
                        "Employee": Employee.objects.get(id=employ),
                        "Employer Contribution": employer_contribution,
                        "Employee Contribution": employee_contribution,
                    }
                )

    emp = request.user.employee_get
    if employee_payslip_list:
        for payslip in employee_payslip_list:
            # Taking the company_name of the user
            info = EmployeeWorkInformation.objects.filter(employee_id=emp).first()

            if info:
                employee_company = info.company_id
                company_name = Company.objects.filter(company=employee_company).first()
                date_format = (
                    company_name.date_format
                    if company_name and company_name.date_format
                    else "MMM. D, YYYY"
                )
            else:
                date_format = "MMM. D, YYYY"

            start_date_str = str(payslip.start_date)
            end_date_str = str(payslip.end_date)

            # Convert the string to a datetime.date object
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()

            for format_name, format_string in HORILLA_DATE_FORMATS.items():
                if format_name == date_format:
                    formatted_start_date = start_date.strftime(format_string)

            for format_name, format_string in HORILLA_DATE_FORMATS.items():
                if format_name == date_format:
                    formatted_end_date = end_date.strftime(format_string)

            table1_data.append(
                {
                    "employee": f"{payslip.employee_id.employee_first_name} {payslip.employee_id.employee_last_name}",
                    "start_date": formatted_start_date,
                    "end_date": formatted_end_date,
                    "basic_pay": round(payslip.basic_pay, 2),
                    "deduction": round(payslip.deduction, 2),
                    "allowance": round(payslip.gross_pay - payslip.basic_pay, 2),
                    "gross_pay": round(payslip.gross_pay, 2),
                    "net_pay": round(payslip.net_pay, 2),
                    "status": status_choices.get(payslip.status),
                },
            )
    else:
        table1_data.append(
            {
                "employee": "None",
                "start_date": "None",
                "end_date": "None",
                "basic_pay": "None",
                "deduction": "None",
                "allowance": "None",
                "gross_pay": "None",
                "net_pay": "None",
                "status": "None",
            },
        )

    for employee in employee_payslip_list:
        department.append(
            employee.employee_id.employee_work_info.department_id.department
        )

    department = list(set(department))

    for depart in department:
        table2_data.append({"Department": depart, "Amount": 0})

    for employee in employee_payslip_list:
        employee_department = (
            employee.employee_id.employee_work_info.department_id.department
        )

        for depart in table2_data:
            if depart["Department"] == employee_department:
                depart["Amount"] += round(employee.net_pay, 2)

    if not employee_payslip_list:
        table2_data.append({"Department": "None", "Amount": 0})

    contract_end = Contract.objects.all()
    if not start_date and not end_date:
        contract_end = contract_end.filter(
            Q(contract_end_date__month=datetime.now().month)
            & Q(contract_end_date__year=datetime.now().year)
        )
    if end_date:
        contract_end = contract_end.filter(contract_end_date__lte=end_date)

    if start_date:
        if not end_date:
            contract_end = contract_end.filter(
                Q(contract_end_date__gte=start_date)
                & Q(contract_end_date__lte=datetime.now())
            )
        else:
            contract_end = contract_end.filter(contract_end_date__gte=start_date)

    table3_data = {"contract_ending": []}

    for contract in contract_end:
        table3_data["contract_ending"].append(contract.contract_name)

    if not contract_end:
        table3_data["contract_ending"].append("None")

    for employee in employee_payslip_list:
        total_amount += round(employee.net_pay, 2)

    table4_data = {
        "no_of_payslip_generated": len(employee_payslip_list),
        "total_amount": [total_amount],
    }

    df_table1 = pd.DataFrame(table1_data)
    df_table2 = pd.DataFrame(table2_data)
    df_table3 = pd.DataFrame(table3_data)
    df_table4 = pd.DataFrame(table4_data)
    df_table5 = pd.DataFrame(table5_data)

    df_table1 = df_table1.rename(
        columns={
            "employee": "Employee",
            "start_date": "Start Date",
            "end_date": "End Date",
            "deduction": "Deduction",
            "allowance": "Allowance",
            "gross_pay": "Gross Pay",
            "net_pay": "Net Pay",
            "status": "Status",
        }
    )

    df_table3 = df_table3.rename(
        columns={
            "contract_ending": (
                f"Contract Ending {start_date} to {end_date}"
                if start_date and end_date
                else f"Contract Ending"
            ),
        }
    )

    df_table4 = df_table4.rename(
        columns={
            "no_of_payslip_generated": "Number of payslips generated",
            "total_amount": "Total Amount",
        }
    )

    df_table5 = df_table5.rename(
        columns={
            "contract_ending": (
                f"Employee - Employer Contributions {start_date} to {end_date}"
                if start_date and end_date
                else f"Contract Ending"
            ),
        }
    )

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = "attachment; filename=payslip.xlsx"

    writer = pd.ExcelWriter(response, engine="xlsxwriter")
    df_table1.to_excel(
        writer, sheet_name="Payroll Dashboard details", index=False, startrow=3
    )
    df_table2.to_excel(
        writer,
        sheet_name="Payroll Dashboard details",
        index=False,
        startrow=len(df_table1) + 3 + 3,
    )
    df_table3.to_excel(
        writer,
        sheet_name="Payroll Dashboard details",
        index=False,
        startrow=len(df_table1) + 3 + len(df_table2) + 6,
    )
    df_table5.to_excel(
        writer,
        sheet_name="Payroll Dashboard details",
        index=False,
        startrow=len(df_table1) + 3 + len(df_table2) + len(df_table3) + 9,
    )
    df_table4.to_excel(
        writer,
        sheet_name="Payroll Dashboard details",
        index=False,
        startrow=len(df_table1)
        + 3
        + len(df_table2)
        + len(df_table3)
        + len(df_table5)
        + 12,
    )

    workbook = writer.book
    worksheet = writer.sheets["Payroll Dashboard details"]
    max_columns = max(
        len(df_table1.columns),
        len(df_table2.columns),
        len(df_table3.columns),
        len(df_table4.columns),
        len(df_table5.columns),
    )

    heading_format = workbook.add_format(
        {
            "bold": True,
            "font_size": 14,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#eb7968",
            "font_size": 20,
        }
    )

    worksheet.set_row(0, 30)
    worksheet.merge_range(
        0,
        0,
        0,
        max_columns - 1,
        (
            f"Payroll details {start_date} to {end_date}"
            if start_date and end_date
            else f"Payroll details"
        ),
        heading_format,
    )

    header_format = workbook.add_format(
        {"bg_color": "#eb7968", "bold": True, "text_wrap": True}
    )

    for col_num, value in enumerate(df_table1.columns.values):
        worksheet.write(3, col_num, value, header_format)
        col_letter = chr(65 + col_num)

        header_width = max(len(value) + 2, len(df_table1[value].astype(str).max()) + 2)
        worksheet.set_column(f"{col_letter}:{col_letter}", header_width)

    for col_num, value in enumerate(df_table2.columns.values):
        worksheet.write(len(df_table1) + 3 + 3, col_num, value, header_format)
        col_letter = chr(65 + col_num)

        header_width = max(len(value) + 2, len(df_table2[value].astype(str).max()) + 2)
        worksheet.set_column(f"{col_letter}:{col_letter}", header_width)

    for col_num, value in enumerate(df_table3.columns.values):
        worksheet.write(
            len(df_table1) + 3 + len(df_table2) + 6, col_num, value, header_format
        )
        col_letter = chr(65 + col_num)

        header_width = max(len(value) + 2, len(df_table3[value].astype(str).max()) + 2)
        worksheet.set_column(f"{col_letter}:{col_letter}", header_width)

    for col_num, value in enumerate(df_table5.columns.values):
        worksheet.write(
            len(df_table1) + 3 + len(df_table2) + len(df_table3) + 9,
            col_num,
            value,
            header_format,
        )
        col_letter = chr(65 + col_num)

    for col_num, value in enumerate(df_table4.columns.values):
        worksheet.write(
            len(df_table1) + 3 + len(df_table2) + len(df_table3) + len(df_table5) + 12,
            col_num,
            value,
            header_format,
        )
        col_letter = chr(65 + col_num)

        header_width = max(len(value) + 2, len(df_table4[value].astype(str).max()) + 2)
        worksheet.set_column(f"{col_letter}:{col_letter}", header_width)

    worksheet.set_row(len(df_table1) + len(df_table2) + 9, 30)

    writer.close()

    return response


@login_required
@permission_required("payroll.delete_payslip")
def payslip_bulk_delete(request):
    """
    This method is used to bulk delete for Payslip
    """
    ids = request.POST["ids"]
    ids = json.loads(ids)
    for id in ids:
        try:
            payslip = Payslip.objects.get(id=id)
            employee = payslip.employee_id
            start_date = payslip.start_date
            end_date = payslip.end_date
            period = f"{start_date} to {end_date}"
            
            # CRITICAL: Delete all allowances linked to this payslip/employee/period
            # Delete allowances that are:
            # 1. Specific to this employee
            # 2. Only show under employee (manually added for this payslip)
            # 3. Have one_time_date within payslip period (if set)
            allowances_to_delete = Allowance.objects.filter(
                specific_employees=employee,
                only_show_under_employee=True
            )
            
            # Filter by date if one_time_date is set and falls within payslip period
            allowances_to_delete = allowances_to_delete.filter(
                Q(one_time_date__isnull=True) | 
                Q(one_time_date__gte=start_date, one_time_date__lte=end_date)
            )
            
            allowances_count = allowances_to_delete.count()
            if allowances_count > 0:
                allowances_to_delete.delete()
                print(f"[BULK_DELETE_PAYSLIP] Deleted {allowances_count} allowances linked to payslip {id}")
            
            # CRITICAL: Delete all deductions linked to this payslip/employee/period
            # Delete deductions that are:
            # 1. Specific to this employee
            # 2. Only show under employee (manually added for this payslip)
            # 3. Have one_time_date within payslip period (if set)
            deductions_to_delete = Deduction.objects.filter(
                specific_employees=employee,
                only_show_under_employee=True
            )
            
            # Filter by date if one_time_date is set and falls within payslip period
            deductions_to_delete = deductions_to_delete.filter(
                Q(one_time_date__isnull=True) | 
                Q(one_time_date__gte=start_date, one_time_date__lte=end_date)
            )
            
            deductions_count = deductions_to_delete.count()
            if deductions_count > 0:
                deductions_to_delete.delete()
                print(f"[BULK_DELETE_PAYSLIP] Deleted {deductions_count} deductions linked to payslip {id}")
            
            # Now delete the payslip itself
            payslip.delete()
            messages.success(
                request,
                _("{employee} {period} payslip and related allowances/deductions deleted.").format(
                    employee=employee, period=period
                ),
            )
        except Payslip.DoesNotExist:
            messages.error(request, _("Payslip not found."))
        except ProtectedError:
            messages.error(
                request,
                _("You cannot delete {payslip}").format(payslip=payslip),
            )
        except Exception as e:
            print(f"[BULK_DELETE_PAYSLIP] Error deleting payslip {id}: {str(e)}")
            import traceback
            traceback.print_exc()
            messages.error(request, _("Error deleting payslip: {}").format(str(e)))
    return JsonResponse({"message": "Success"})


@login_required
@permission_required("payroll.change_payslip")
def slip_group_name_update(request):
    """
    This method is used to update the group of the payslip
    """
    new_name = request.POST["newName"]
    group_name = request.POST["previousName"]
    Payslip.objects.filter(group_name=group_name).update(group_name=new_name)
    return JsonResponse(
        {"type": "success", "message": "Batch name updated.", "new_name": new_name}
    )


@login_required
@permission_required("payroll.add_contract")
def contract_export(request):
    hx_request = request.META.get("HTTP_HX_REQUEST")
    if hx_request:
        export_filter = ContractFilter()
        export_column = ContractExportFieldForm()
        content = {
            "export_filter": export_filter,
            "export_column": export_column,
        }
        return render(
            request,
            "payroll/contract/contract_export_filter.html",
            context=content,
        )
    return export_data(
        request=request,
        model=Contract,
        filter_class=ContractFilter,
        form_class=ContractExportFieldForm,
        file_name="Contract_export",
    )


@login_required
@permission_required("payroll.delete_contract")
def contract_bulk_delete(request):
    """
    This method is used to bulk delete Contract
    """
    ids = request.POST["ids"]
    ids = json.loads(ids)
    for id in ids:
        try:
            contract = Contract.objects.get(id=id)
            name = f"{contract.contract_name}"
            contract.delete()
            messages.success(
                request,
                _("{name} deleted.").format(name=name),
            )
        except Payslip.DoesNotExist:
            messages.error(request, _("Contract not found."))
        except ProtectedError:
            messages.error(
                request,
                _("You cannot delete {contract}").format(contract=contract),
            )
    return JsonResponse({"message": "Success"})


def equalize_lists_length(allowances, deductions):
    """
    Equalize the lengths of two lists by appending empty dictionaries to the shorter list.

    Args:
    deductions (list): List of dictionaries representing deductions.
    allowances (list): List of dictionaries representing allowances.

    Returns:
    tuple: Tuple containing two lists with equal lengths.
    """
    num_deductions = len(deductions)
    num_allowances = len(allowances)

    while num_deductions < num_allowances:
        deductions.append({"title": "", "amount": ""})
        num_deductions += 1

    while num_allowances < num_deductions:
        allowances.append({"title": "", "amount": ""})
        num_allowances += 1

    return deductions, allowances


def generate_payslip_pdf(template_path, context, html=False):
    """
    Generate a PDF file from an HTML template and context data.

    Args:
        template_path (str): The path to the HTML template.
        context (dict): The context data to render the template.
        html (bool): If True, return raw HTML instead of a PDF.

    Returns:
        HttpResponse: A response with the generated PDF file or raw HTML.
    """
    try:
        # Render the HTML content from the template and context
        html_content = render_to_string(template_path, context)

        # Return raw HTML if requested
        if html:
            return HttpResponse(html_content, content_type="text/html")

        # PDF options for pdfkit
        pdf_options = {
            "page-size": "A4",
            "margin-top": "10mm",
            "margin-bottom": "10mm",
            "margin-left": "10mm",
            "margin-right": "10mm",
            "encoding": "UTF-8",
            "enable-local-file-access": None,  # Required to load local CSS/images
            "dpi": 300,
            "zoom": 1.3,
            "footer-center": "[page]/[topage]",  # Required to load local CSS/images
        }

        # Generate the PDF as binary content
        pdf = pdfkit.from_string(html_content, False, options=pdf_options)

        # Return an HttpResponse containing the PDF content
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = "inline; filename=payslip.pdf"
        return response
    except Exception as e:
        # Handle errors gracefully
        return HttpResponse(f"Error generating PDF: {str(e)}", status=500)


def payslip_pdf(request, id):
    """
    Generate the payslip as a PDF and return it in an HttpResponse.

    Args:
        request (HttpRequest): The request object.
        id (int): The ID of the payslip to generate.

    Returns:
        HttpResponse: A response containing the PDF content.
    """

    from .component_views import filter_payslip

    if Payslip.objects.filter(id=id).exists():
        payslip = Payslip.objects.get(id=id)
        company = Company.objects.filter(hq=True).first()
        if (
            request.user.has_perm("payroll.view_payslip")
            or payslip.employee_id.employee_user_id == request.user
        ):
            user = request.user
            employee = user.employee_get

            # Taking the company_name of the user
            info = EmployeeWorkInformation.objects.filter(employee_id=employee)
            if info.exists():
                for data in info:
                    employee_company = data.company_id
                company_name = Company.objects.filter(company=employee_company)
                emp_company = company_name.first()

                # Access the date_format attribute directly
                date_format = (
                    emp_company.date_format
                    if emp_company and emp_company.date_format
                    else "MMM. D, YYYY"
                )

            data = payslip.pay_head_data
            start_date_str = data["start_date"]
            end_date_str = data["end_date"]

            # Convert the string to a datetime.date object
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()

            # Format the start and end dates
            for format_name, format_string in HORILLA_DATE_FORMATS.items():
                if format_name == date_format:
                    formatted_start_date = start_date.strftime(format_string)
                    formatted_end_date = end_date.strftime(format_string)

            # Prepare context for the template
            data.update(
                {
                    "month_start_name": start_date.strftime("%B %d, %Y"),
                    "month_end_name": end_date.strftime("%B %d, %Y"),
                    "formatted_start_date": formatted_start_date,
                    "formatted_end_date": formatted_end_date,
                    "employee": payslip.employee_id,
                    "payslip": payslip,
                    "json_data": data.copy(),
                    "currency": PayrollSettings.objects.first().currency_symbol,
                    "all_deductions": [],
                    "all_allowances": data["allowances"].copy(),
                    "host": request.get_host(),
                    "protocol": "https" if request.is_secure() else "http",
                    "company": company,
                }
            )

            # Merge deductions and allowances for display
            for deduction_list in [
                data["basic_pay_deductions"],
                data["gross_pay_deductions"],
                data["pretax_deductions"],
                data["post_tax_deductions"],
                data["tax_deductions"],
                data["net_deductions"],
            ]:
                data["all_deductions"].extend(deduction_list)

            equalize_lists_length(data["allowances"], data["all_deductions"])
            data["zipped_data"] = zip(data["allowances"], data["all_deductions"])
            template_path = "payroll/payslip/payslip_pdf.html"

            return generate_payslip_pdf(template_path, context=data, html=False)
        return redirect(filter_payslip)
    return render(request, "405.html")


@login_required
@permission_required("payroll.view_contract")
def contract_select(request):
    page_number = request.GET.get("page")

    if page_number == "all":
        employees = Contract.objects.all()

    contract_ids = [str(emp.id) for emp in employees]
    total_count = employees.count()

    context = {"contract_ids": contract_ids, "total_count": total_count}

    return JsonResponse(context, safe=False)


@login_required
def contract_select_filter(request):
    page_number = request.GET.get("page")
    filtered = request.GET.get("filter")
    filters = json.loads(filtered) if filtered else {}

    if page_number == "all":
        contract_filter = ContractFilter(filters, queryset=Contract.objects.all())

        # Get the filtered queryset
        filtered_employees = contract_filter.qs

        contract_ids = [str(emp.id) for emp in filtered_employees]
        total_count = filtered_employees.count()

        context = {"contract_ids": contract_ids, "total_count": total_count}

        return JsonResponse(context)


@login_required
def payslip_select(request):
    page_number = request.GET.get("page")

    if page_number == "all":
        if request.user.has_perm("payroll.view_payslip"):
            employees = Payslip.objects.all()
        else:
            employees = Payslip.objects.filter(
                employee_id__employee_user_id=request.user
            )

    payslip_ids = [str(emp.id) for emp in employees]
    total_count = employees.count()

    context = {"payslip_ids": payslip_ids, "total_count": total_count}

    return JsonResponse(context, safe=False)


@login_required
def payslip_select_filter(request):
    page_number = request.GET.get("page")
    filtered = request.GET.get("filter")
    filters = json.loads(filtered) if filtered else {}

    if page_number == "all":
        payslip_filter = PayslipFilter(filters, queryset=Payslip.objects.all())

        # Get the filtered queryset
        filtered_employees = payslip_filter.qs

        payslip_ids = [str(emp.id) for emp in filtered_employees]
        total_count = filtered_employees.count()

        context = {"payslip_ids": payslip_ids, "total_count": total_count}

        return JsonResponse(context)


@login_required
def create_payrollrequest_comment(request, payroll_id):
    """
    This method renders form and template to create Reimbursement request comments
    """
    from payroll.forms.forms import ReimbursementRequestCommentForm

    payroll = Reimbursement.objects.filter(id=payroll_id).first()
    emp = request.user.employee_get
    form = ReimbursementRequestCommentForm(
        initial={"employee_id": emp.id, "request_id": payroll_id}
    )

    if request.method == "POST":
        form = ReimbursementRequestCommentForm(request.POST)
        if form.is_valid():
            form.instance.employee_id = emp
            form.instance.request_id = payroll
            form.save()
            comments = ReimbursementrequestComment.objects.filter(
                request_id=payroll_id
            ).order_by("-created_at")
            no_comments = False
            if not comments.exists():
                no_comments = True
            form = ReimbursementRequestCommentForm(
                initial={"employee_id": emp.id, "request_id": payroll_id}
            )
            messages.success(request, _("Comment added successfully!"))

            if payroll.employee_id.employee_work_info.reporting_manager_id is not None:

                if request.user.employee_get.id == payroll.employee_id.id:
                    rec = (
                        payroll.employee_id.employee_work_info.reporting_manager_id.employee_user_id
                    )
                    notify.send(
                        request.user.employee_get,
                        recipient=rec,
                        verb=f"{payroll.employee_id}'s reimbursement request has received a comment.",
                        verb_ar=f"تلقى طلب استرداد نفقات {payroll.employee_id} تعليقًا.",
                        verb_de=f"{payroll.employee_id}s Rückerstattungsantrag hat einen Kommentar erhalten.",
                        verb_es=f"La solicitud de reembolso de gastos de {payroll.employee_id} ha recibido un comentario.",
                        verb_fr=f"La demande de remboursement de frais de {payroll.employee_id} a reçu un commentaire.",
                        redirect=reverse("view-reimbursement"),
                        icon="chatbox-ellipses",
                    )
                elif (
                    request.user.employee_get.id
                    == payroll.employee_id.employee_work_info.reporting_manager_id.id
                ):
                    rec = payroll.employee_id.employee_user_id
                    notify.send(
                        request.user.employee_get,
                        recipient=rec,
                        verb="Your reimbursement request has received a comment.",
                        verb_ar="تلقى طلب استرداد نفقاتك تعليقًا.",
                        verb_de="Ihr Rückerstattungsantrag hat einen Kommentar erhalten.",
                        verb_es="Tu solicitud de reembolso ha recibido un comentario.",
                        verb_fr="Votre demande de remboursement a reçu un commentaire.",
                        redirect=reverse("view-reimbursement"),
                        icon="chatbox-ellipses",
                    )
                else:
                    rec = [
                        payroll.employee_id.employee_user_id,
                        payroll.employee_id.employee_work_info.reporting_manager_id.employee_user_id,
                    ]
                    notify.send(
                        request.user.employee_get,
                        recipient=rec,
                        verb=f"{payroll.employee_id}'s reimbursement request has received a comment.",
                        verb_ar=f"تلقى طلب استرداد نفقات {payroll.employee_id} تعليقًا.",
                        verb_de=f"{payroll.employee_id}s Rückerstattungsantrag hat einen Kommentar erhalten.",
                        verb_es=f"La solicitud de reembolso de gastos de {payroll.employee_id} ha recibido un comentario.",
                        verb_fr=f"La demande de remboursement de frais de {payroll.employee_id} a reçu un commentaire.",
                        redirect=reverse("view-reimbursement"),
                        icon="chatbox-ellipses",
                    )
            else:
                rec = payroll.employee_id.employee_user_id
                notify.send(
                    request.user.employee_get,
                    recipient=rec,
                    verb="Your reimbursement request has received a comment.",
                    verb_ar="تلقى طلب استرداد نفقاتك تعليقًا.",
                    verb_de="Ihr Rückerstattungsantrag hat einen Kommentar erhalten.",
                    verb_es="Tu solicitud de reembolso ha recibido un comentario.",
                    verb_fr="Votre demande de remboursement a reçu un commentaire.",
                    redirect=reverse("view-reimbursement"),
                    icon="chatbox-ellipses",
                )

            return render(
                request,
                "payroll/reimbursement/reimbursement_comment.html",
                {
                    "comments": comments,
                    "no_comments": no_comments,
                    "request_id": payroll_id,
                },
            )
    return render(
        request,
        "payroll/reimbursement/reimbursement_comment.html",
        {"form": form, "request_id": payroll_id},
    )


@login_required
@hx_request_required
def view_payrollrequest_comment(request, payroll_id):
    """
    This method is used to show Reimbursement request comments
    """
    comments = ReimbursementrequestComment.objects.filter(
        request_id=payroll_id
    ).order_by("-created_at")

    req = Reimbursement.objects.get(id=payroll_id)
    no_comments = False
    if not comments.exists():
        no_comments = True

    if request.FILES:
        files = request.FILES.getlist("files")
        comment_id = request.GET["comment_id"]
        comment = ReimbursementrequestComment.objects.get(id=comment_id)
        attachments = []
        for file in files:
            file_instance = ReimbursementFile()
            file_instance.file = file
            file_instance.save()
            attachments.append(file_instance)
        comment.files.add(*attachments)
    return render(
        request,
        "payroll/reimbursement/reimbursement_comment.html",
        {
            "comments": comments,
            "no_comments": no_comments,
            "request_id": payroll_id,
            "req": req,
        },
    )


@login_required
def delete_payrollrequest_comment(request, comment_id):
    """
    This method is used to delete Reimbursement request comments
    """
    script = ""
    comment = ReimbursementrequestComment.objects.filter(id=comment_id)
    comment.delete()
    messages.success(request, _("Comment deleted successfully!"))
    return HttpResponse(script)


@login_required
def delete_reimbursement_comment_file(request):
    """
    Used to delete attachment
    """
    script = ""
    ids = request.GET.getlist("ids")
    records = ReimbursementFile.objects.filter(id__in=ids)
    if not request.user.has_perm("payroll.delete_reimbursmentfile"):
        records = records.filter(employee_id__employee_user_id=request.user)
    records.delete()
    messages.success(request, _("File deleted successfully"))
    return HttpResponse(script)


@login_required
@permission_required("payroll.add_payrollgeneralsetting")
def initial_notice_period(request):
    """
    This method is used to set initial value notice period
    """
    notice_period = eval_validate(request.GET["notice_period"])
    settings = PayrollGeneralSetting.objects.first()
    settings = settings if settings else PayrollGeneralSetting()
    settings.notice_period = max(notice_period, 0)
    settings.save()
    messages.success(
        request, _("The initial notice period has been successfully updated.")
    )
    if request.META.get("HTTP_HX_REQUEST"):
        return HttpResponse()
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))


# ===========================Auto payslip generate================================


@login_required
@permission_required("payroll.view_PayslipAutoGenerate")
def auto_payslip_settings_view(request):
    payslip_auto_generate = PayslipAutoGenerate.objects.all()

    context = {"payslip_auto_generate": payslip_auto_generate}
    return render(request, "payroll/settings/auto_payslip_settings.html", context)


@login_required
@hx_request_required
@permission_required("payroll.change_PayslipAutoGenerate")
def create_or_update_auto_payslip(request, auto_id=None):
    auto_payslip = None
    if auto_id:
        auto_payslip = PayslipAutoGenerate.objects.get(id=auto_id)
    form = PayslipAutoGenerateForm(instance=auto_payslip)
    if request.method == "POST":
        form = PayslipAutoGenerateForm(request.POST, instance=auto_payslip)
        if form.is_valid():
            auto_payslip = form.save()
            company = (
                auto_payslip.company_id if auto_payslip.company_id else "All company"
            )
            messages.success(
                request, _(f"Payslip Auto generate for {company} created successfully ")
            )
            return HttpResponse("<script>window.location.reload()</script>")
    return render(
        request, "payroll/settings/auto_payslip_create_or_update.html", {"form": form}
    )


@login_required
@permission_required("payroll.change_PayslipAutoGenerate")
def activate_auto_payslip_generate(request):
    """
    ajax function to update is active field in PayslipAutoGenerate.
    Args:
    - isChecked: Boolean value representing the state of PayslipAutoGenerate,
    - autoId: Id of PayslipAutoGenerate object
    """
    isChecked = request.POST.get("isChecked")
    autoId = request.POST.get("autoId")
    payslip_auto = PayslipAutoGenerate.objects.get(id=autoId)
    if isChecked == "true":
        payslip_auto.auto_generate = True
        response = {
            "type": "success",
            "message": _("Auto paslip generate activated successfully."),
        }
    else:
        payslip_auto.auto_generate = False
        response = {
            "type": "success",
            "message": _("Auto paslip generate deactivated successfully."),
        }
    payslip_auto.save()
    return JsonResponse(response)


@login_required
@hx_request_required
@permission_required("payroll.delete_PayslipAutoGenerate")
def delete_auto_payslip(request, auto_id):
    """
    Delete a PayslipAutoGenerate object.

    Args:
        auto_id: The ID of PayslipAutoGenerate object to delete.

    Returns:
        Redirects to the contract view after successfully deleting the contract.

    """
    try:
        auto_payslip = PayslipAutoGenerate.objects.get(id=auto_id)
        if not auto_payslip.auto_generate:
            company = (
                auto_payslip.company_id if auto_payslip.company_id else "All company"
            )
            auto_payslip.delete()
            messages.success(
                request, _(f"Payslip auto generate for {company} deleted successfully.")
            )
        else:
            messages.info(request, _(f"Active 'Payslip auto generate' cannot delete."))
        return HttpResponse("<script>window.location.reload();</script>")
    except PayslipAutoGenerate.DoesNotExist:
        messages.error(request, _("Payslip auto generate not found."))
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))
