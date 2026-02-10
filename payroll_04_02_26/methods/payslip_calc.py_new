"""
This module contains various functions for calculating payroll-related information for employees.
It includes functions for calculating gross pay, taxable gross pay, allowances, tax deductions,
pre-tax deductions, and post-tax deductions.
"""

import contextlib
import operator
from decimal import Decimal
from django.apps import apps
from horilla.methods import get_horilla_model_class
from payroll.methods.deductions import update_compensation_deduction
from payroll.methods.limits import compute_limit
from employee.methods.duration_methods import strtime_seconds
from payroll.models import models
from payroll.models.models import Contract
from payroll.models.models import (
    Allowance,
    Contract, # <--- Contract model imported
    Deduction,
    LoanAccount,
    MultipleCondition,
)

try:
    from payroll.methods.methods import get_total_days_in_month, get_total_days
except ImportError:
    # Fallback: Calculate days based on start_date and end_date
    from calendar import monthrange
    def get_total_days_in_month(d):
        """Get total days in the month of the given date"""
        if isinstance(d, str):
            from datetime import datetime
            d = datetime.strptime(d, '%Y-%m-%d').date()
        return monthrange(d.year, d.month)[1]
    
    def get_total_days(start_date, end_date):
        """Get total calendar days between start_date and end_date (inclusive)"""
        if isinstance(start_date, str):
            from datetime import datetime
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            from datetime import datetime
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        return (end_date - start_date).days + 1


def return_none(a, b):
    return None


operator_mapping = {
    "equal": operator.eq,
    "notequal": operator.ne,
    "lt": operator.lt,
    "gt": operator.gt,
    "le": operator.le,
    "ge": operator.ge,
    "icontains": operator.contains,
    "range": return_none,
}
filter_mapping = {
    "work_type_id": {
        "filter": lambda employee, allowance, start_date, end_date: {
            "employee_id": employee,
            "work_type_id__id": allowance.work_type_id.id,
            "attendance_date__range": (start_date, end_date),
            "attendance_validated": True,
        }
    },
    "shift_id": {
        "filter": lambda employee, allowance, start_date, end_date: {
            "employee_id": employee,
            "shift_id__id": allowance.shift_id.id,
            "attendance_date__range": (start_date, end_date),
            "attendance_validated": True,
        }
    },
    "overtime": {
        "filter": lambda employee, allowance, start_date, end_date: {
            "employee_id": employee,
            "attendance_date__range": (start_date, end_date),
            "is_overtime": True,
            "attendance_validated": True,
        }
    },
    "attendance": {
        "filter": lambda employee, allowance, start_date, end_date: {
            "employee_id": employee,
            "attendance_date__range": (start_date, end_date),
            "attendance_validated": True,
        }
    },
}



tets = {
    "net_pay": 35140.905000000006,
    "employee": 1,
    "allowances": [
        {
            "allowance_id": 5,
            "title": "Low Basic Pay Assistance",
            "is_taxable": True,
            "amount": 0,
        },
        {
            "allowance_id": 13,
            "title": "Bonus point Redeem for Adam Luis ",
            "is_taxable": True,
            "amount": 75.0,
        },
        {
            "allowance_id": 17,
            "title": "Motorcycle",
            "is_taxable": True,
            "amount": 5000.0,
        },
        {
            "allowance_id": 2,
            "title": "Meal Allowance",
            "is_taxable": False,
            "amount": 800.0,
        },
    ],
    "gross_pay": 39284.09090909091,
    "contract_wage": 35000.0,
    "basic_pay": 33409.09090909091,
    "paid_days": 21.0,
    "unpaid_days": 1.0,
    "taxable_gross_pay": {"taxable_gross_pay": 35848.47727272727},
    "basic_pay_deductions": [],
    "gross_pay_deductions": [],
    "pretax_deductions": [
        {
            "deduction_id": 1,
            "title": "Social Security (FICA)",
            "is_pretax": True,
            "amount": 2435.6136363636365,
            "employer_contribution_rate": 6.2,
        },
        {
            "deduction_id": 62,
            "title": "Late Come penalty",
            "is_pretax": True,
            "amount": 200.0,
            "employer_contribution_rate": 0.0,
        },
    ],
    "post_tax_deductions": [
        {
            "deduction_id": 2,
            "title": "Medicare tax",
            "is_pretax": False,
            "amount": 484.43181818181824,
            "employer_contribution_rate": 1.45,
        },
        {
            "deduction_id": 55,
            "title": "ESI",
            "is_pretax": False,
            "amount": 0,
            "employer_contribution_rate": 3.25,
        },
        {
            "deduction_id": 73,
            "title": "Test",
            "is_pretax": False,
            "amount": 0.0,
            "employer_contribution_rate": 0.0,
        },
    ],
    "tax_deductions": [
        {
            "deduction_id": 75,
            "title": "test tax netpay",
            "is_tax": True,
            "amount": 668.1818181818182,
            "employer_contribution_rate": 3.0,
        }
    ],
    "net_deductions": [
        {
            "deduction_id": 74,
            "title": "Test Netpay",
            "is_pretax": False,
            "amount": 354.9586363636364,
            "employer_contribution_rate": 2.0,
        }
    ],
    "total_deductions": 3788.227272727273,
    "loss_of_pay": 1590.909090909091,
    "federal_tax": 0,
    "start_date": "2024-02-01",
    "end_date": "2024-02-29",
    "range": "Feb 01 2024 - Feb 29 2024",
}


def dynamic_attr(obj, attribute_path):
    """
    Retrieves the value of a nested attribute from a related object dynamically.

    Args:
        obj: The base object from which to start accessing attributes.
        attribute_path (str): The path of the nested attribute to retrieve, using
        double underscores ('__') to indicate relationship traversal.

    Returns:
        The value of the nested attribute if it exists, or None if it doesn't exist.
    """
    attributes = attribute_path.split("__")

    for attr in attributes:
        with contextlib.suppress(Exception):
            if isinstance(obj.first(), Contract):
                obj = obj.filter(is_active=True).first()

        obj = getattr(obj, attr, None)
        if obj is None:
            break
    return obj

# --- PLACEHOLDER/HELPER FUNCTIONS ---

def calculate_based_on_basic_pay(*_args, **kwargs):
    """Placeholder function for calculation based on basic pay."""
    return 0.0

def calculate_based_on_gross_pay(*_args, **kwargs):
    """
    Calculates the Gross Pay by summing Basic Pay, Dynamic Allowances, and Fixed Contract Allowances (pro-rata).
    Updates kwargs with fixed allowance details and the final gross_pay value.
    """
    employee = kwargs["employee"]
    # basic_pay को Decimal में लें ताकि floating point issues कम हों
    basic_pay = Decimal(kwargs["basic_pay"]) 
    # kwargs.get() का उपयोग करें ताकि total_allowance (dynamic allowance) ना होने पर 0.0 मिले।
    total_dynamic_allowance = Decimal(kwargs.get("total_allowance", 0.0)) 
    
    start_date = kwargs.get("start_date")
    end_date = kwargs.get("end_date")

    # --- Fixed Allowances Contract से लें (अब start_date और end_date पास कर रहे हैं) ---
    (
        housing_a,
        transport_a,
        other_a,
        total_fixed_allowances
    ) = get_contract_fixed_allowances(employee.id, start_date, end_date)

    # Total Allowance को अपडेट करें (dynamic + fixed)
    total_allowance = total_dynamic_allowance + Decimal(total_fixed_allowances)
    
    # Gross Pay की गणना (basic_pay + total_allowance)
    gross_pay = basic_pay + total_allowance


    kwargs["housing_allowance"] = float(housing_a)
    kwargs["transport_allowance"] = float(transport_a)
    kwargs["other_allowance"] = float(other_a)
    

    kwargs["total_allowance"] = float(total_allowance)
    kwargs["gross_pay"] = float(gross_pay) 

    if "pay_head_data" not in kwargs:
        kwargs["pay_head_data"] = {}
    

    kwargs["pay_head_data"]["contract_allowances"] = {
        "housing_allowance": float(housing_a),
        "transport_allowance": float(transport_a),
        "other_allowance": float(other_a),
        "total_fixed_allowances": float(total_fixed_allowances)
    }
    

    return float(gross_pay)

def calculate_based_on_net_pay(*_args, **kwargs):

    taxable_gross_pay = kwargs.get("taxable_gross_pay", 0.0)
    total_deductions = kwargs.get("total_deductions", 0.0)
    
    net_pay = taxable_gross_pay - total_deductions
    
    kwargs["total_net_pay"] = float(net_pay)
    kwargs["net_pay"] = float(net_pay) # Often payslip model uses 'net_pay' field
    return float(net_pay)

def calculate_pre_tax_deduction(*_args, **kwargs):
    """
    Placeholder for calculating pre-tax deductions.
    Assumes it returns a dict with 'pretax_deductions' key containing a list of deductions.
    """
    return {"pretax_deductions": []}

def calculate_net_pay(*_args, **kwargs):
    """Placeholder function for calculating net pay."""
    return 0.0

def get_fixed_contract_allowances(contract, paid_days_in_period, total_days_in_month):
    """
    Calculates fixed (pro-rata) allowances from the contract for the payslip period.
    """
    allowances = {
        "housing_allowance": 0.0,
        "transport_allowance": 0.0,
        "other_allowance": 0.0,
        "total_fixed_allowances": 0.0, 
    }

    if not contract:
        return allowances


    pro_rata_factor = paid_days_in_period / total_days_in_month if total_days_in_month else 0

    allowances["housing_allowance"] = contract.housing_allowance * pro_rata_factor
    allowances["transport_allowance"] = contract.transport_allowance * pro_rata_factor
    allowances["other_allowance"] = contract.other_allowance * pro_rata_factor
    
    # Calculate total fixed allowance for easier gross pay calculation
    allowances["total_fixed_allowances"] = (
        allowances["housing_allowance"] + 
        allowances["transport_allowance"] + 
        allowances["other_allowance"]
    )

    return allowances
    
    
def calculate_gross_pay(*_args, **kwargs):
    print("327 DEBUG calculate_gross_pay called with kwargs:", kwargs)

    employee = kwargs["employee"]
    basic_pay = Decimal(str(kwargs.get("basic_pay", 0.0)))
    paid_days = kwargs.get("paid_days", 0)
    total_days_in_month = kwargs.get("total_days_in_month", 30)

    # ✅ Use fixed allowances from kwargs if provided, otherwise default to 0
    # This allows passing allowances without fetching contract
    housing_allowance = Decimal(str(kwargs.get("housing_allowance", 0.0)))
    transport_allowance = Decimal(str(kwargs.get("transport_allowance", 0.0)))
    other_allowance = Decimal(str(kwargs.get("other_allowance", 0.0)))

    # Check if we should skip dynamic allowances (for imports or no contract scenarios)
    skip_dynamic_allowances = kwargs.get("skip_dynamic_allowances", False)
    has_contract = kwargs.get("contract") is not None
    
    # CRITICAL FIX: For imports, recalculate basic_pay based on start_date and end_date (NOT attendance)
    # HORILLA-STYLE: Calculate based on date range only, ignore attendance
    if skip_dynamic_allowances:
        contract_wage = kwargs.get("contract_wage", 0)
        
        # Calculate based on start_date and end_date only (NO attendance logic)
        # paid_days should already be calculated as (end_date - start_date) + 1 from the calling function
        # total_days_in_month should be the actual calendar month days (30/31/28/29)
        if contract_wage and contract_wage > 0 and paid_days > 0 and total_days_in_month > 0:
            # Use actual calendar month days as divisor (from start_date/end_date)
            # This ensures correct calculation: Monthly Basic Pay / Calendar Month Days * Paid Days
            divisor = Decimal(str(total_days_in_month))
            
            # Recalculate basic_pay: per_day_basic = contract_wage / calendar_month_days, basic_pay = per_day_basic * paid_days
            per_day_basic = Decimal(str(contract_wage)) / divisor
            recalculated_basic_pay = per_day_basic * Decimal(str(paid_days))
                        
            basic_pay = recalculated_basic_pay
            print(f"[calculate_gross_pay] IMPORT MODE: Recalculated basic_pay from date range - contract_wage: {contract_wage}, calendar_days: {total_days_in_month}, paid_days: {paid_days}, basic_pay: {basic_pay}")
        elif contract_wage and contract_wage > 0 and paid_days == 0:
            # If paid_days is 0, set basic_pay to 0 (no calculation needed)
            basic_pay = Decimal("0.0")
            print(f"[calculate_gross_pay] IMPORT MODE: paid_days is 0, setting basic_pay to 0")
    
    # If no contract or explicitly skipping dynamic allowances, don't add previous allowances
    if skip_dynamic_allowances or not has_contract:
        total_dynamic_allowance = Decimal("0.0")
        print(f"[calculate_gross_pay] Skipping dynamic allowances - skip_dynamic: {skip_dynamic_allowances}, has_contract: {has_contract}")
    else:
        total_dynamic_allowance = Decimal(str(kwargs.get("total_allowance", 0.0)))
        print(f"[calculate_gross_pay] Using dynamic allowances: {total_dynamic_allowance}")

    # --- Add everything using Decimal
    total_fixed_allowance = housing_allowance + transport_allowance + other_allowance
    total_allowance = total_dynamic_allowance + total_fixed_allowance
    gross_pay = basic_pay + total_allowance

    # --- Update kwargs for later use
    kwargs.update({
        "housing_allowance": float(housing_allowance),
        "transport_allowance": float(transport_allowance),
        "other_allowance": float(other_allowance),
        "gross_pay": float(gross_pay),
        "total_allowance": float(total_allowance),
    })

    print(f"✅ Gross Pay Calculated: {gross_pay} "
          f"(Basic: {basic_pay}, Dyn Allow: {total_dynamic_allowance}, "
          f"Fixed: {total_fixed_allowance})")

    # --- Return values as floats for JSON serialization
    return {
        "gross_pay": float(gross_pay),
        "housing_allowance": float(housing_allowance),
        "transport_allowance": float(transport_allowance),
        "other_allowance": float(other_allowance),
        "deductions": [],
    }


def calculate_taxable_gross_pay(gross_data, **kwargs):
    """
    Calculate the taxable gross pay for an employee within a given date range.
    """
    # Safely get allowances data structure, defaulting to an empty list
    allowances_data = kwargs.get("payslip_data", {"allowances": []})
    
    # Correctly unpacks the tuple returned by calculate_gross_pay (basic_pay is first, gross_pay is second)
    # This call will now safely calculate gross_pay because calculate_gross_pay is fixed.
    gross_data = calculate_gross_pay(**kwargs)
    # basic_pay = gross_data["basic_pay"]
    # gross_pay = gross_data["gross_pay"]
    basic_pay = gross_data.get("basic_pay", 0)
    gross_pay = gross_data.get("gross_pay", 0)
    
    # Safely calculate pre-tax deductions
    pre_tax_deductions = calculate_pre_tax_deduction(**kwargs)
    
    # Calculate non-taxable allowances total
    non_taxable_allowance_total = sum(
        allowance["amount"]
        for allowance in allowances_data.get("allowances", [])
        if not allowance.get("is_taxable", True)
    )
    
    # Calculate total pre-tax deductions
    pretax_deduction_total = sum(
        deduction["amount"]
        for deduction in pre_tax_deductions.get("pretax_deductions", [])
        if deduction.get("is_pretax", False)
    )
    
    # Final calculation
    taxable_gross_pay = gross_pay - non_taxable_allowance_total - pretax_deduction_total
    
    return taxable_gross_pay


def calculate_allowance(**kwargs):
    """
    Calculate the allowances for an employee within the specified payroll period.

    Args:
        employee (Employee): The employee object for which to calculate the allowances.
        start_date (datetime.date): The start date of the payroll period.
        end_date (datetime.date): The end date of the payroll period.

    """
    employee = kwargs["employee"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    basic_pay = kwargs["basic_pay"]
    day_dict = kwargs["day_dict"]
    specific_allowances = Allowance.objects.filter(specific_employees=employee)
    conditional_allowances = Allowance.objects.filter(is_condition_based=True).exclude(
        exclude_employees=employee
    )
    active_employees = Allowance.objects.filter(include_active_employees=True).exclude(
        exclude_employees=employee
    )

    allowances = specific_allowances | conditional_allowances | active_employees

    allowances = (
        allowances.exclude(one_time_date__lt=start_date)
        .exclude(one_time_date__gt=end_date)
        .distinct()
    )

    employee_allowances = []
    tax_allowances = []
    no_tax_allowances = []
    tax_allowances_amt = []
    no_tax_allowances_amt = []
    # Append allowances based on condition, or unconditionally to employee
    for allowance in allowances:
        if allowance.is_condition_based:
            conditions = list(
                allowance.other_conditions.values_list("field", "condition", "value")
            )
            condition_field = allowance.field
            condition_operator = allowance.condition
            condition_value = allowance.value.lower().replace(" ", "_")
            conditions.append((condition_field, condition_operator, condition_value))
            applicable = True
            for condition in conditions:
                val = dynamic_attr(employee, condition[0])
                if val is not None:
                    operator_func = operator_mapping.get(condition[1])
                    condition_value = type(val)(condition[2])
                    if operator_func(val, condition_value):
                        applicable = applicable * True
                        continue
                    else:
                        applicable = False
                        break
                else:
                    applicable = False
                    break
            if applicable:
                employee_allowances.append(allowance)
        else:
            if allowance.based_on in filter_mapping:
                filter_params = filter_mapping[allowance.based_on]["filter"](
                    employee, allowance, start_date, end_date
                )
                if apps.is_installed("attendance"):
                    Attendance = get_horilla_model_class(
                        app_label="attendance", model="attendance"
                    )
                    if Attendance.objects.filter(**filter_params):
                        employee_allowances.append(allowance)
            else:
                employee_allowances.append(allowance)
    # Filter and append taxable allowance and not taxable allowance
    for allowance in employee_allowances:
        if allowance.is_taxable:
            tax_allowances.append(allowance)
        else:
            no_tax_allowances.append(allowance)
    # Find and append the amount of tax_allowances
    for allowance in tax_allowances:
        if allowance.is_fixed:
            amount = allowance.amount
            kwargs["amount"] = amount
            kwargs["component"] = allowance

            amount = if_condition_on(**kwargs)
            tax_allowances_amt.append(amount)
        else:
            calculation_function = calculation_mapping.get(allowance.based_on)
            amount = calculation_function(
                **{
                    "employee": employee,
                    "start_date": start_date,
                    "end_date": end_date,
                    "component": allowance,
                    "allowances": None,
                    "total_allowance": None,
                    "basic_pay": basic_pay,
                    "day_dict": day_dict,
                },
            )
            kwargs["amount"] = amount
            kwargs["component"] = allowance
            amount = if_condition_on(**kwargs)
            tax_allowances_amt.append(amount)
    # Find and append the amount of not tax_allowances
    for allowance in no_tax_allowances:
        if allowance.is_fixed:
            amount = allowance.amount
            kwargs["amount"] = amount
            kwargs["component"] = allowance
            amount = if_condition_on(**kwargs)
            no_tax_allowances_amt.append(amount)

        else:
            calculation_function = calculation_mapping.get(allowance.based_on)
            amount = calculation_function(
                **{
                    "employee": employee,
                    "start_date": start_date,
                    "end_date": end_date,
                    "component": allowance,
                    "day_dict": day_dict,
                    "basic_pay": basic_pay,
                }
            )
            kwargs["amount"] = amount
            kwargs["component"] = allowance
            amount = if_condition_on(**kwargs)
            no_tax_allowances_amt.append(amount)
    serialized_allowances = []

    # Serialize taxable allowances
    for allowance, amount in zip(tax_allowances, tax_allowances_amt):
        serialized_allowance = {
            "allowance_id": allowance.id,
            "title": allowance.title,
            "is_taxable": allowance.is_taxable,
            "amount": amount,
        }
        serialized_allowances.append(serialized_allowance)

    # Serialize no-taxable allowances
    for allowance, amount in zip(no_tax_allowances, no_tax_allowances_amt):
        serialized_allowance = {
            "allowance_id": allowance.id,
            "title": allowance.title,
            "is_taxable": allowance.is_taxable,
            "amount": amount,
        }
        serialized_allowances.append(serialized_allowance)
    return {"allowances": serialized_allowances}


def calculate_tax_deduction(*_args, **kwargs):
    """
    Calculates the tax deductions for the specified employee within the given date range.

    Args:
        employee (Employee): The employee for whom the tax deductions are being calculated.
        start_date (date): The start date of the tax deduction period.
        end_date (date): The end date of the tax deduction period.
        allowances (dict): Dictionary containing the calculated allowances.
        total_allowance (float): The total amount of allowances.
        basic_pay (float): The basic pay amount.
        day_dict (dict): Dictionary containing working day details.

    Returns:
        dict: A dictionary containing the serialized tax deductions.
    """
    employee = kwargs["employee"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    specific_deductions = models.Deduction.objects.filter(
        specific_employees=employee, is_pretax=False, is_tax=True
    )
    active_employee_deduction = models.Deduction.objects.filter(
        include_active_employees=True, is_pretax=False, is_tax=True
    ).exclude(exclude_employees=employee)
    deductions = specific_deductions | active_employee_deduction
    deductions = (
        deductions.exclude(one_time_date__lt=start_date)
        .exclude(one_time_date__gt=end_date)
        .exclude(update_compensation__isnull=False)
    )
    deductions_amt = []
    serialized_deductions = []
    for deduction in deductions:
        calculation_function = calculation_mapping.get(deduction.based_on)
        amount = calculation_function(
            **{
                "employee": employee,
                "start_date": start_date,
                "end_date": end_date,
                "component": deduction,
                "allowances": kwargs.get("allowances", []),
                "total_allowance": kwargs.get("total_allowance", 0.0),
                "basic_pay": kwargs.get("basic_pay", 0.0),
                "day_dict": kwargs.get("day_dict", {}),
            }
        )
        kwargs["amount"] = amount
        kwargs["component"] = deduction
        amount = if_condition_on(**kwargs)
        deductions_amt.append(amount)
    for deduction, amount in zip(deductions, deductions_amt):
        serialized_deduction = {
            "deduction_id": deduction.id,
            "title": deduction.title,
            "is_tax": deduction.is_tax,
            "amount": amount,
            "employer_contribution_rate": deduction.employer_rate,
        }
        serialized_deductions.append(serialized_deduction)
    return {"tax_deductions": serialized_deductions}


def calculate_pre_tax_deduction(*_args, **kwargs):
    """
    This function retrieves pre-tax deductions applicable to the employee and calculates
    their amounts

    Args:
        employee: The employee object for whom to calculate the pre-tax deductions.
        start_date: The start date of the period for which to calculate the pre-tax deductions.
        end_date: The end date of the period for which to calculate the pre-tax deductions.

    Returns:
        A dictionary containing the pre-tax deductions as the "pretax_deductions" key.

    """
    employee = kwargs["employee"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]

    specific_deductions = models.Deduction.objects.filter(
        specific_employees=employee, is_pretax=True, is_tax=False
    )
    conditional_deduction = models.Deduction.objects.filter(
        is_condition_based=True, is_pretax=True, is_tax=False
    ).exclude(exclude_employees=employee)
    active_employee_deduction = models.Deduction.objects.filter(
        include_active_employees=True, is_pretax=True, is_tax=False
    ).exclude(exclude_employees=employee)

    deductions = specific_deductions | conditional_deduction | active_employee_deduction
    deductions = (
        deductions.exclude(one_time_date__lt=start_date)
        .exclude(one_time_date__gt=end_date)
        .exclude(update_compensation__isnull=False)
    )
    # Installment deductions
    installments = deductions.filter(is_installment=True)

    pre_tax_deductions = []
    pre_tax_deductions_amt = []
    serialized_deductions = []

    for deduction in deductions:
        if deduction.is_condition_based:
            conditions = list(
                deduction.other_conditions.values_list("field", "condition", "value")
            )
            condition_field = deduction.field
            condition_operator = deduction.condition
            condition_value = deduction.value.lower().replace(" ", "_")
            conditions.append((condition_field, condition_operator, condition_value))
            operator_func = operator_mapping.get(condition_operator)
            applicable = True
            for condition in conditions:
                val = dynamic_attr(employee, condition[0])
                if val is not None:
                    operator_func = operator_mapping.get(condition[1])
                    condition_value = type(val)(condition[2])
                    if operator_func(val, condition_value):
                        applicable = applicable * True
                        continue
                    else:
                        applicable = False
                        break
                else:
                    applicable = False
                    break
            if applicable:
                pre_tax_deductions.append(deduction)
        else:
            pre_tax_deductions.append(deduction)

    for deduction in pre_tax_deductions:
        if deduction.is_fixed:
            kwargs["amount"] = deduction.amount
            kwargs["component"] = deduction
            pre_tax_deductions_amt.append(if_condition_on(**kwargs))
        else:
            calculation_function = calculation_mapping.get(deduction.based_on)
            amount = calculation_function(
                **{
                    "employee": employee,
                    "start_date": start_date,
                    "end_date": end_date,
                    "component": deduction,
                    "allowances": kwargs.get("allowances", []),
                    "total_allowance": kwargs.get("total_allowance", 0.0),
                    "basic_pay": kwargs.get("basic_pay", 0.0),
                    "day_dict": kwargs.get("day_dict", {}),
                }
            )
            kwargs["amount"] = amount
            kwargs["component"] = deduction
            pre_tax_deductions_amt.append(if_condition_on(**kwargs))
    for deduction, amount in zip(pre_tax_deductions, pre_tax_deductions_amt):
        serialized_deduction = {
            "deduction_id": deduction.id,
            "title": deduction.title,
            "is_pretax": deduction.is_pretax,
            "amount": amount,
            "employer_contribution_rate": deduction.employer_rate,
        }
        serialized_deductions.append(serialized_deduction)
    return {"pretax_deductions": serialized_deductions, "installments": installments}


def calculate_post_tax_deduction(*_args, **kwargs):
    """
    This function retrieves post-tax deductions applicable to the employee and calculates
    their amounts

    Args:
        employee: The employee object for whom to calculate the pre-tax deductions.
        start_date: The start date of the period for which to calculate the pre-tax deductions.
        end_date: The end date of the period for which to calculate the pre-tax deductions.

    Returns:
        A dictionary containing the pre-tax deductions as the "post_tax_deductions" key.

    """
    employee = kwargs["employee"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    allowances = kwargs.get("allowances", [])
    total_allowance = kwargs.get("total_allowance", 0.0)
    basic_pay = kwargs.get("basic_pay", 0.0)
    day_dict = kwargs.get("day_dict", {})
    specific_deductions = models.Deduction.objects.filter(
        specific_employees=employee, is_pretax=False, is_tax=False
    )
    conditional_deduction = models.Deduction.objects.filter(
        is_condition_based=True, is_pretax=False, is_tax=False
    ).exclude(exclude_employees=employee)
    active_employee_deduction = models.Deduction.objects.filter(
        include_active_employees=True, is_pretax=False, is_tax=False
    ).exclude(exclude_employees=employee)
    deductions = specific_deductions | conditional_deduction | active_employee_deduction
    deductions = (
        deductions.exclude(one_time_date__lt=start_date)
        .exclude(one_time_date__gt=end_date)
        .exclude(update_compensation__isnull=False)
    )
    # Installment deductions
    installments = deductions.filter(is_installment=True)

    post_tax_deductions = []
    post_tax_deductions_amt = []
    serialized_deductions = []
    serialized_net_pay_deductions = []

    for deduction in deductions:
        if deduction.is_condition_based:
            condition_field = deduction.field
            condition_operator = deduction.condition
            condition_value = deduction.value.lower().replace(" ", "_")
            employee_value = dynamic_attr(employee, condition_field)
            operator_func = operator_mapping.get(condition_operator)
            if employee_value is not None:
                condition_value = type(employee_value)(condition_value)
                if operator_func(employee_value, condition_value):
                    post_tax_deductions.append(deduction)
        else:
            post_tax_deductions.append(deduction)
    for deduction in post_tax_deductions:
        if deduction.is_fixed:
            amount = deduction.amount
            kwargs["amount"] = amount
            kwargs["component"] = deduction
            amount = if_condition_on(**kwargs)
            post_tax_deductions_amt.append(amount)
        else:
            if deduction.based_on != "net_pay":
                calculation_function = calculation_mapping.get(deduction.based_on)
                amount = calculation_function(
                    **{
                        "employee": employee,
                        "start_date": start_date,
                        "end_date": end_date,
                        "component": deduction,
                        "allowances": allowances,
                        "total_allowance": total_allowance,
                        "basic_pay": basic_pay,
                        "day_dict": day_dict,
                    }
                )
                kwargs["amount"] = amount
                kwargs["component"] = deduction
                amount = if_condition_on(**kwargs)
                post_tax_deductions_amt.append(amount)

    for deduction, amount in zip(post_tax_deductions, post_tax_deductions_amt):
        serialized_deduction = {
            "deduction_id": deduction.id,
            "title": deduction.title,
            "is_pretax": deduction.is_pretax,
            "amount": amount,
            "employer_contribution_rate": deduction.employer_rate,
        }
        serialized_deductions.append(serialized_deduction)
    for deduction in post_tax_deductions:
        if deduction.based_on == "net_pay":
            serialized_net_pay_deduction = {"deduction": deduction}
            serialized_net_pay_deductions.append(serialized_net_pay_deduction)
    return {
        "post_tax_deductions": serialized_deductions,
        "net_pay_deduction": serialized_net_pay_deductions,
        "installments": installments,
    }


def calculate_net_pay_deduction(net_pay, net_pay_deductions, **kwargs):
    """
    Calculates the deductions based on the net pay amount.

    Args:
        net_pay (float): The net pay amount.
        net_pay_deductions (list): List of net pay deductions.
        day_dict (dict): Dictionary containing working day details.

    Returns:
        dict: A dictionary containing the serialized deductions and deduction amount.
    """
    day_dict = kwargs["day_dict"]
    serialized_net_pay_deductions = []
    deductions = [item["deduction"] for item in net_pay_deductions]
    deduction_amt = []
    for deduction in deductions:
        amount = calculate_based_on_net_pay(deduction, net_pay, day_dict)
        kwargs["amount"] = amount
        kwargs["component"] = deduction
        amount = if_condition_on(**kwargs)
        deduction_amt.append(amount)
    net_deduction = 0
    for deduction, amount in zip(deductions, deduction_amt):
        serialized_deduction = {
            "deduction_id": deduction.id,
            "title": deduction.title,
            "is_pretax": deduction.is_pretax,
            "amount": amount,
            "employer_contribution_rate": deduction.employer_rate,
        }
        net_deduction = amount + net_deduction
        serialized_net_pay_deductions.append(serialized_deduction)
    return {
        "net_pay_deductions": serialized_net_pay_deductions,
        "net_deduction": net_deduction,
    }


def if_condition_on(*_args, **kwargs):
    """
    This method is used to check the allowance or deduction through the the conditions

    Args:
        employee (obj): Employee instance
        amount (float): calculated amount of the component
        component (obj): Allowance or Deduction instance
        start_date (obj): Start date of the period
        end_date (obj): End date of the period

    Returns:
        _type_: _description_
    """
    component = kwargs["component"]
    basic_pay = kwargs["basic_pay"]
    amount = kwargs["amount"]
    gross_pay = 0
    amount = float(amount)
    if not isinstance(component, Allowance):
        gross_pay = calculate_gross_pay(
            **kwargs,
        )["gross_pay"]
    condition_value = basic_pay if component.if_choice == "basic_pay" else gross_pay
    if component.if_condition == "range":
        if not component.start_range <= condition_value <= component.end_range:
            amount = 0
    else:
        operator_func = operator_mapping.get(component.if_condition)
        if not operator_func(condition_value, component.if_amount):
            amount = 0
    return amount


def calculate_based_on_basic_pay(*_args, **kwargs):
    """
    Calculate the amount of an allowance or deduction based on the employee's
    basic pay with rate provided in the allowance or deduction object

    Args:
        employee (Employee): The employee object for whom to calculate the amount.
        start_date (datetime.date): The start date of the period for which to calculate the amount.
        end_date (datetime.date): The end date of the period for which to calculate the amount.
        component (Component): The allowance or deduction object that defines the rate or percentage
        to apply.

    Returns:
        The calculated allowance or deduction amount based on the employee's basic pay.

    """
    component = kwargs["component"]
    basic_pay = kwargs["basic_pay"]
    day_dict = kwargs["day_dict"]
    rate = component.rate
    amount = basic_pay * rate / 100
    amount = compute_limit(component, amount, day_dict)

    return amount


def calculate_based_on_gross_pay(*_args, **kwargs):
    """
    Calculate the amount of an allowance or deduction based on the employee's gross pay with rate
    provided in the allowance or deduction object

    Args:
        employee (Employee): The employee object for whom to calculate the amount.
        start_date (datetime.date): The start date of the period for which to calculate the amount.
        end_date (datetime.date): The end date of the period for which to calculate the amount.
        component (Component): The allowance or deduction object that defines the rate or percentage
        to apply.

    Returns:+-
        The calculated allowance or deduction amount based on the employee's gross pay.

    """

    component = kwargs["component"]
    day_dict = kwargs["day_dict"]
    gross_pay = calculate_gross_pay(**kwargs)
    rate = component.rate
    amount = gross_pay["gross_pay"] * rate / 100
    amount = compute_limit(component, amount, day_dict)
    return amount


def calculate_based_on_taxable_gross_pay(*_args, **kwargs):
    # Placeholder
    # Net Pay और Taxable Gross Pay की गणना यहीं होगी, जो Gross Pay पर निर्भर करती है।
    # जब तक आप इन फंक्शन्स का कोड नहीं देते, तब तक यह 0.0 या Gross Pay के बराबर होगा।
    gross_pay = kwargs.get("gross_pay", 0.0)
    # yahan Taxable gross pay calculation logic aayega
    kwargs["taxable_gross_pay"] = float(gross_pay)
    return float(gross_pay)

def calculate_based_on_net_pay(component, net_pay, day_dict):
    """
    Calculates the amount of an allowance or deduction based on the net pay of an employee.

    Args:
        component (Allowance or Deduction): The allowance or deduction object.
        net_pay (float): The net pay of the employee.
        day_dict (dict): Dictionary containing working day details.

    Returns:
        float: The calculated amount of the component based on the net pay.
    """
    rate = float(component.rate)
    amount = net_pay * rate / 100
    amount = compute_limit(component, amount, day_dict)
    return amount


def calculate_based_on_attendance(*_args, **kwargs):
    """
    Calculates the amount of an allowance or deduction based on the attendance of an employee.
    ...
    """
    employee = kwargs["employee"]
    component = kwargs["component"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    day_dict = kwargs["day_dict"]
    Attendance = get_horilla_model_class("attendance", "Attendance")
    count = Attendance.objects.filter(
        **filter_mapping["attendance"]["filter"](
            employee, component, start_date, end_date
        )
    ).count()
    amount = count * component.per_attendance_amount

    amount = compute_limit(component, amount, day_dict)

    return amount


def calculate_based_on_shift(*_args, **kwargs):
    """
    Calculates the amount of an allowance or deduction based on the attendance of an employee.
    ...
    """
    employee = kwargs["employee"]
    component = kwargs["component"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    day_dict = kwargs["day_dict"]
    Attendance = get_horilla_model_class("attendance", "Attendance")
    count = Attendance.objects.filter(
        **filter_mapping["shift_id"]["filter"](
            employee, component, start_date, end_date
        )
    ).count()
    amount = count * component.shift_per_attendance_amount

    amount = compute_limit(component, amount, day_dict)

    return amount


def calculate_based_on_overtime(*_args, **kwargs):
    """
    Calculates the amount of an allowance or deduction based on the attendance of an employee.
    ...
    """
    employee = kwargs["employee"]
    component = kwargs["component"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    day_dict = kwargs["day_dict"]
    Overtime = get_horilla_model_class("attendance", "Overtime")
    qs = Overtime.objects.filter(
        **filter_mapping["overtime"]["filter"](
            employee, component, start_date, end_date
        )
    )
    total_duration = sum(strtime_seconds(i.duration) for i in qs)
    total_hours = total_duration / 3600
    amount = total_hours * component.overtime_per_hour_amount

    amount = compute_limit(component, amount, day_dict)

    return amount


def calculate_based_on_work_type(*_args, **kwargs):
    """
    Calculates the amount of an allowance or deduction based on the attendance of an employee.
    ...
    """
    employee = kwargs["employee"]
    component = kwargs["component"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    day_dict = kwargs["day_dict"]
    Attendance = get_horilla_model_class("attendance", "Attendance")
    count = Attendance.objects.filter(
        **filter_mapping["work_type_id"]["filter"](
            employee, component, start_date, end_date
        )
    ).count()
    amount = count * component.work_type_per_attendance_amount

    amount = compute_limit(component, amount, day_dict)

    return amount


def calculate_based_on_children(*_args, **kwargs):
    """
    Calculates the amount of an allowance or deduction based on the attendance of an employee.
    """
    employee = kwargs["employee"]
    component = kwargs["component"]
    day_dict = kwargs["day_dict"]
    # Ensure count is not None
    count = employee.children if employee.children is not None else 0
    amount = count * component.per_children_fixed_amount
    amount = compute_limit(component, amount, day_dict)
    return amount

# --- FUNCTION TO GET CONTRACT FIXED ALLOWANCES (Refined) ---
def get_contract_fixed_allowances(employee_id, start_date, end_date):
    from decimal import Decimal
    from datetime import datetime

    housing_a = transport_a = other_a = total_fixed_allowances = Decimal(0)

    contract = Contract.objects.filter(employee_id=employee_id, is_active=True).first()
    print("DEBUG CONTRACT:", contract)
    
    if not contract:
        return 0.0, 0.0, 0.0, 0.0

    # Convert dates if string
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

    # HORILLA-STYLE: Calculate days based on start_date and end_date (calendar days, not paid/unpaid)
    days_in_period = get_total_days(start_date, end_date)
    total_days_in_month = get_total_days_in_month(start_date)
    
    if total_days_in_month == 0:
        pro_rata_factor = Decimal(1)  # default to full month
    else:
        pro_rata_factor = Decimal(days_in_period) / Decimal(total_days_in_month)

    housing_a = Decimal(contract.housing_allowance or 0) * pro_rata_factor
    transport_a = Decimal(contract.transport_allowance or 0) * pro_rata_factor
    other_a = Decimal(contract.other_allowance or 0) * pro_rata_factor

    total_fixed_allowances = housing_a + transport_a + other_a

    print("DEBUG final allowances:", housing_a, transport_a, other_a, total_fixed_allowances)
    
    return float(housing_a), float(transport_a), float(other_a), float(total_fixed_allowances)



calculation_mapping = {
    "basic_pay": calculate_based_on_basic_pay,
    "gross_pay": calculate_based_on_gross_pay, # Using the existing name
    "taxable_gross_pay": calculate_based_on_taxable_gross_pay,
    "net_pay": calculate_based_on_net_pay,
    "attendance": calculate_based_on_attendance,
    "shift_id": calculate_based_on_shift,
    "overtime": calculate_based_on_overtime,
    "work_type_id": calculate_based_on_work_type,
    "children": calculate_based_on_children,
}
