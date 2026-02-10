"""
methods.py

Payroll related module to write custom calculation methods
"""

import calendar
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.core.paginator import Paginator
from django.db.models import F, Q

# from attendance.models import Attendance
from base.methods import (
    get_company_leave_dates,
    get_date_range,
    get_holiday_dates,
    get_pagination,
    get_working_days,
)
from base.models import CompanyLeaves, Holidays
from horilla.methods import get_horilla_model_class
from payroll.models.models import Contract, Deduction, Payslip


def get_total_days(start_date, end_date):
    """
    Calculates the total number of days in a given period.

    Args:
        start_date (date): The start date of the period.

        end_date (date): The end date of the period.
    Returns:
        int: The total number of days in the period, including the end date.

    Example:
        start_date = date(2023, 1, 1)
        end_date = date(2023, 1, 10)
        days_on_period = get_total_days(start_date, end_date)
    """
    print(f"--- get_total_days called with start_date={start_date}, end_date={end_date} ---")
    delta = end_date - start_date
    total_days = delta.days + 1  # Add 1 to include the end date itself
    print(f"Total days calculated: {total_days}")
    return total_days


def get_leaves(employee, start_date, end_date):
    """
    This method is used to return all the leaves taken by the employee
    between the period.

    Args:
        employee (obj): Employee model instance
        start_date (obj): the start date from the data needed
        end_date (obj): the end date till the date needed
    """
    print(f"--- get_leaves called for employee ID={employee.id} from {start_date} to {end_date} ---")
    if apps.is_installed("leave"):
        approved_leaves = employee.leaverequest_set.filter(status="approved")
    else:
        approved_leaves = None
    paid_leave = 0
    unpaid_leave = 0
    paid_half = 0
    unpaid_half = 0
    paid_leave_dates = []
    unpaid_leave_dates = []
    company = None
    if hasattr(employee, "employee_work_info") and employee.employee_work_info:
        company = employee.employee_work_info.company_id
    company_leave_dates = get_working_days(start_date, end_date, company=company)["company_leave_dates"]
    print(f"Approved leaves queryset exists: {approved_leaves and approved_leaves.exists()}")

    if approved_leaves and approved_leaves.exists():
        for instance in approved_leaves:
            if instance.leave_type_id.payment == "paid":
                # if the taken leave is paid
                # for the start date
                all_the_paid_leave_taken_dates = instance.requested_dates()
                paid_leave_dates = paid_leave_dates + [
                    date
                    for date in all_the_paid_leave_taken_dates
                    if start_date <= date <= end_date
                ]
            else:
                # if the taken leave is unpaid
                # for the start date
                all_unpaid_leave_taken_dates = instance.requested_dates()
                unpaid_leave_dates = unpaid_leave_dates + [
                    date
                    for date in all_unpaid_leave_taken_dates
                    if start_date <= date <= end_date
                ]

    half_day_data = find_half_day_leaves()
    print(f"Half day data: {half_day_data}")

    unpaid_half = half_day_data["half_unpaid_leaves"]
    paid_half = half_day_data["half_paid_leaves"]

    paid_leave_dates = list(set(paid_leave_dates) - set(company_leave_dates))
    unpaid_leave_dates = list(set(unpaid_leave_dates) - set(company_leave_dates))
    paid_leave = len(paid_leave_dates) - paid_half
    unpaid_leave = len(unpaid_leave_dates) - unpaid_half
    print(f"Calculated paid_leave: {paid_leave}, unpaid_leave: {unpaid_leave}")
    return {
        "paid_leave": paid_leave,
        "unpaid_leaves": unpaid_leave,
        "total_leaves": paid_leave + unpaid_leave,
        # List of paid leave date between range
        "paid_leave_dates": paid_leave_dates,
        # List of un paid date between range
        "unpaid_leave_dates": unpaid_leave_dates,
        "leave_dates": unpaid_leave_dates + paid_leave_dates,
    }


if apps.is_installed("attendance"):

    def get_attendance(employee, start_date, end_date):
        """
        This method is used to render attendance details between the range

        Args:
            employee (obj): Employee user instance
            start_date (obj): start date of the period
            end_date (obj): end date of the period
        """
        print(f"--- get_attendance called for employee ID={employee.id} from {start_date} to {end_date} ---")
        Attendance = get_horilla_model_class(app_label="attendance", model="attendance")
        attendances_on_period = Attendance.objects.filter(
            employee_id=employee,
            attendance_date__range=(start_date, end_date),
            attendance_validated=True,
        )
        present_on = [
            attendance.attendance_date for attendance in attendances_on_period
        ]
        print(f"Number of validated attendances found: {len(attendances_on_period)}")
        
        # Get employee company
        company = None
        if hasattr(employee, 'employee_work_info') and employee.employee_work_info:
            company = employee.employee_work_info.company_id
        
        print(f"get_attendance: Resolved Company ID: {company}")

        # Get working days (excludes holidays and company leaves usually)
        working_days_dict = get_working_days(start_date, end_date, company=company)
        working_days_between_range = working_days_dict["working_days_on"]
        
        # Get approved leaves
        leaves_data = get_leaves(employee, start_date, end_date)
        leave_dates = leaves_data["leave_dates"]
        
        # Get Holidays and Company Leaves explicitly to ensure they are excluded from Conflict
        # (Even if get_working_days handles them, double safety involves ensuring we don't count them as absent)
        holiday_dates = get_holiday_dates(start_date, end_date, company=company)
        company_leave_dates = get_company_leave_dates(start_date.year, company=company) + \
                              get_company_leave_dates(end_date.year, company=company)
        
        # Calculate Conflict (Unaccounted Absence)
        # Conflict = Working Days - Present - Approved Leaves - Holidays - Company Leaves
        # Note: get_working_days result should already exclude Holidays/Company Leaves, but we do set difference for safety.
        
        potential_conflict = set(working_days_between_range) - set(present_on) - set(leave_dates)
        conflict_dates = list(potential_conflict - set(holiday_dates) - set(company_leave_dates))
        
        # Sort for display/debugging
        conflict_dates.sort()
        
        print(f"Calculated conflict_dates (Absent): {len(conflict_dates)}")
        print(f"Conflict Dates List: {conflict_dates}")
        
        return {
            "attendances_on_period": attendances_on_period,
            "present_on": present_on,
            "conflict_dates": conflict_dates,
            "leave_dates": leave_dates,
            "working_days": working_days_between_range
        }


def hourly_computation(employee, wage, start_date, end_date):
    """
    Hourly salary computation for period.

    Args:
        employee (obj): Employee instance
        wage (float): wage of the employee
        start_date (obj): start of the pay period
        end_date (obj): end date of the period
    """
    print(f"--- hourly_computation called for employee ID={employee.id} with wage={wage} from {start_date} to {end_date} ---")
    if not apps.is_installed("attendance"):
        print("Attendance app not installed. Returning basic pay 0.")
        return {
            "basic_pay": 0,
            "loss_of_pay": 0,
        }
    attendance_data = get_attendance(employee, start_date, end_date)
    attendances_on_period = attendance_data["attendances_on_period"]
    total_worked_hour_in_second = 0
    for attendance in attendances_on_period:
        total_worked_hour_in_second = total_worked_hour_in_second + (
            attendance.at_work_second - attendance.overtime_second
        )
    print(f"Total worked seconds: {total_worked_hour_in_second}")

    # to find wage per second
    # wage_per_second = wage_per_hour / total_seconds_in_hour
    wage_in_second = wage / 3600
    basic_pay = float(f"{(wage_in_second * total_worked_hour_in_second):.2f}")
    print(f"Calculated basic_pay: {basic_pay}")

    return {
        "basic_pay": basic_pay,
        "loss_of_pay": 0,
        "paid_days": len(attendances_on_period),
        "unpaid_days": 0,
    }


def find_half_day_leaves():
    """
    This method is used to return the half day leave details

    Args:
        employee (obj): Employee model instance
        start_date (obj): start date of the period
        end_date (obj): end date of the period
    """
    print("--- find_half_day_leaves called ---")
    paid_queryset = []
    unpaid_queryset = []

    paid_leaves = list(filter(None, list(set(paid_queryset))))
    unpaid_leaves = list(filter(None, list(set(unpaid_queryset))))
    print(f"Paid half day leaves count (from queryset): {len(paid_leaves)}")
    print(f"Unpaid half day leaves count (from queryset): {len(unpaid_leaves)}")

    paid_half = len(paid_leaves) * 0.5
    unpaid_half = len(unpaid_leaves) * 0.5
    queryset = paid_leaves + unpaid_leaves
    total_leaves = len(queryset) * 0.50
    print(f"Calculated half_paid_leaves: {paid_half}, half_unpaid_leaves: {unpaid_half}")
    return {
        "half_day_query_set": queryset,
        "half_day_leaves": total_leaves,
        "half_paid_leaves": paid_half,
        "half_unpaid_leaves": unpaid_half,
    }


def daily_computation(employee, wage, start_date, end_date):
    """
    Hourly salary computation for period.

    Args:
        employee (obj): Employee instance
        wage (float): wage of the employee
        start_date (obj): start of the pay period
        end_date (obj): end date of the period
    """
    print(f"--- daily_computation called for employee ID={employee.id} with wage={wage} from {start_date} to {end_date} ---")
    company = None
    if hasattr(employee, "employee_work_info") and employee.employee_work_info:
        company = employee.employee_work_info.company_id
    working_day_data = get_working_days(start_date, end_date, company=company)
    total_working_days = working_day_data["total_working_days"]
    print(f"Total working days in period: {total_working_days}")

    leave_data = get_leaves(employee, start_date, end_date)
    print(f"Leave data: {leave_data}")

    contract = employee.contract_set.filter(contract_status="active").first()
    basic_pay = wage * total_working_days
    loss_of_pay = 0
    print(f"Initial basic_pay: {basic_pay}")

    date_range = get_date_range(start_date, end_date)
    half_day_leaves_between_period_on_start_date = (
        employee.leaverequest_set.filter(
            leave_type_id__payment="unpaid",
            start_date__in=date_range,
            status="approved",
        )
        .exclude(start_date_breakdown="full_day")
        .count()
    )

    half_day_leaves_between_period_on_end_date = (
        employee.leaverequest_set.filter(
            leave_type_id__payment="unpaid", end_date__in=date_range, status="approved"
        )
        .exclude(end_date_breakdown="full_day")
        .exclude(start_date=F("end_date"))
        .count()
    )
    unpaid_half_leaves = (
        half_day_leaves_between_period_on_start_date
        + half_day_leaves_between_period_on_end_date
    ) * 0.5
    print(f"Calculated unpaid_half_leaves: {unpaid_half_leaves}")

    contract = employee.contract_set.filter(
        is_active=True, contract_status="active"
    ).first()

    unpaid_leaves = leave_data["unpaid_leaves"] - unpaid_half_leaves
    
    # Add unaccounted absences (conflict dates) to unpaid leaves
    conflict_dates_count = 0
    if apps.is_installed("attendance"):
        attendance_data = get_attendance(employee, start_date, end_date)
        conflict_dates_count = len(attendance_data.get("conflict_dates", []))
        print(f"Adding {conflict_dates_count} conflict days (absent) to unpaid leaves.")
    
    unpaid_leaves += conflict_dates_count

    if contract and contract.calculate_daily_leave_amount:
        loss_of_pay = (unpaid_leaves) * wage
    elif contract:
        fixed_penalty = contract.deduction_for_one_leave_amount
        loss_of_pay = (unpaid_leaves) * fixed_penalty
    else: # Handle case if contract is None, though earlier check should prevent this.
        loss_of_pay = 0
        
    print(f"Unpaid leaves for LOP calculation: {unpaid_leaves}, Loss of Pay: {loss_of_pay}")
    
    if contract and contract.deduct_leave_from_basic_pay:
        basic_pay = basic_pay - loss_of_pay
        print(f"Basic pay after LOP deduction: {basic_pay}")

    return {
        "basic_pay": basic_pay,
        "loss_of_pay": loss_of_pay,
        "paid_days": total_working_days - unpaid_leaves, # Paid days should reflect absences
        "unpaid_days": unpaid_leaves,
    }


def get_daily_salary(wage, wage_date, company=None) -> dict:
    """
    This method is used to calculate daily salary for the date
    """
    print(f"--- get_daily_salary called with wage={wage}, wage_date={wage_date} ---")
    last_day = calendar.monthrange(wage_date.year, wage_date.month)[1]
    end_date = date(wage_date.year, wage_date.month, last_day)
    start_date = date(wage_date.year, wage_date.month, 1)
    working_days = get_working_days(start_date, end_date, company=company)["total_working_days"]
    day_wage = (
        wage / working_days if working_days else 0.0
    )  # if working_days != 0 else 0 #769

    print(f"Monthly working days: {working_days}, Calculated day_wage: {day_wage}")
    return {
        "day_wage": day_wage,
    }


def months_between_range(wage, start_date, end_date, company=None):
    """
    This method is used to find the months between range
    """
    print(f"--- months_between_range called with wage={wage} from {start_date} to {end_date} ---")
    months_data = []

    for current_date in (
        start_date + relativedelta(months=i)
        for i in range(
            (end_date.year - start_date.year) * 12
            + end_date.month
            - start_date.month
            + 1
        )
    ):
        month = current_date.month
        year = current_date.year

        days_in_month = (
            current_date + relativedelta(day=1, months=1) - relativedelta(days=1)
        ).day

        # Calculate the end date for the current month
        current_end_date = current_date + relativedelta(day=days_in_month)
        current_end_date = min(current_end_date, end_date)
        working_days_on_month = get_working_days(
            current_date.replace(day=1),
            current_date.replace(day=30),
            company=company,
        )["total_working_days"]

        month_start_date = (
            date(year=year, month=month, day=1)
            if start_date < date(year=year, month=month, day=1)
            else start_date
        )
        total_working_days_on_period = get_working_days(
            month_start_date, current_end_date, company=company
        )["total_working_days"]

        per_day_amount = (
            wage / working_days_on_month if working_days_on_month else 0.0
        )
        
        month_info = {
            "month": month,
            "year": year,
            "days": days_in_month,
            "start_date": month_start_date.strftime("%Y-%m-%d"),
            "end_date": current_end_date.strftime("%Y-%m-%d"),
            # month period
            "working_days_on_period": total_working_days_on_period,
            "working_days_on_month": working_days_on_month,
            "per_day_amount": per_day_amount,
            # if working_days_on_month != 0 else 0 #769,
        }
        print(f"Processed month: {month_info}")

        months_data.append(month_info)
        # Set the start date for the next month as the first day of the next month
        current_date = (current_date + relativedelta(day=1, months=1)).replace(day=1)

    return months_data


def compute_yearly_taxable_amount(
    monthly_taxable_amount=None,
    default_yearly_taxable_amount=None,
    *args,
    **kwargs,
):
    """
    Compute yearly taxable amount custom logic
    eg:
        default_yearly_taxable_amount = monthly_taxable_amount * 12
    """
    print(f"--- compute_yearly_taxable_amount called with monthly_taxable_amount={monthly_taxable_amount} and default_yearly_taxable_amount={default_yearly_taxable_amount} ---")
    print(f"Returning default_yearly_taxable_amount: {default_yearly_taxable_amount}")
    return default_yearly_taxable_amount


def convert_year_tax_to_period(
    federal_tax_for_period=None,
    yearly_tax=None,
    total_days=None,
    start_date=None,
    end_date=None,
    *args,
    **kwargs,
):
    """
    Method to convert yearly taxable to monthly
    """
    print(f"--- convert_year_tax_to_period called with yearly_tax={yearly_tax} for period {start_date} to {end_date} ---")
    print(f"Returning federal_tax_for_period: {federal_tax_for_period}")
    return federal_tax_for_period


def compute_net_pay(
    net_pay=None,
    gross_pay=None,
    total_pretax_deduction=None,
    total_post_tax_deduction=None,
    total_tax_deductions=None,
    federal_tax=None,
    loss_of_pay_amount=None,
    *args,
    **kwargs,
):
    """
    Compute net pay | Additional logic
    """
    print(f"--- compute_net_pay called with gross_pay={gross_pay}, total_tax_deductions={total_tax_deductions}, etc. ---")
    print(f"Returning net_pay: {net_pay}")
    return net_pay


# def monthly_computation(employee, wage, start_date, end_date, *args, **kwargs):
#     """
#     Monthly salary computation for period.
#     Calculates payable days and LOP days correctly based on attendance, leaves, holidays, and weekoffs.
#     Updated Basic Pay = (Actual Basic Pay / Total Days in Month) * Paid Days

#     Args:
#         employee (obj): Employee instance
#         wage (float): wage of the employee (Actual Basic Pay)
#         start_date (obj): start of the pay period
#         end_date (obj): end date of the period
#     """
#     print(f"--- monthly_computation called for employee ID={employee.id} with wage={wage} from {start_date} to {end_date} ---")
    
#     company = None
#     if hasattr(employee, "employee_work_info") and employee.employee_work_info:
#         company = employee.employee_work_info.company_id
        
#     month_data = months_between_range(wage, start_date, end_date, company=company)
#     print(f"Month data for computation: {month_data}")

#     # HORILLA-STYLE: Calculate payable days based on date range (calendar days)
#     # payable_days = (end_date - start_date) + 1 (calendar days in period)
#     payable_days_calendar = (end_date - start_date).days + 1
    
#     # Get total calendar days in the month for per_day calculation
#     # Use the month of start_date for consistency
#     from calendar import monthrange
#     total_calendar_days = monthrange(start_date.year, start_date.month)[1]
    
#     print(f"Date range: {start_date} to {end_date}")
#     print(f"Payable days (calendar): {payable_days_calendar}")
#     print(f"Total calendar days in month: {total_calendar_days}")

#     # Get all dates in the period
#     date_range = get_date_range(start_date, end_date)
    
#     # Get holidays
#     holiday_dates = set(get_holiday_dates(start_date, end_date, company=company))
    
#     # Get working days data to identify weekoffs
#     working_days_data = get_working_days(start_date, end_date, company=company)
#     working_days_list = set(working_days_data.get("working_days_on", []))
    
#     # Get leaves data
#     leave_data = get_leaves(employee, start_date, end_date)
#     paid_leave_dates = set(leave_data.get("paid_leave_dates", []))
#     unpaid_leave_dates = set(leave_data.get("unpaid_leave_dates", []))
#     all_leave_dates = set(leave_data.get("leave_dates", []))
    
#     # Get half-day leave dates (paid and unpaid)
#     # Half-day leaves have start_date_breakdown or end_date_breakdown as "half_day" or "first_half" or "second_half"
#     paid_half_day_leave_dates = set()
#     unpaid_half_day_leave_dates = set()
#     if apps.is_installed("leave"):
#         date_range_set = set(date_range)
        
#         # Get half-day paid leaves - check both start and end date breakdowns
#         paid_half_day_leaves_start = employee.leaverequest_set.filter(
#             leave_type_id__payment="paid",
#             status="approved",
#             start_date__lte=end_date,
#             end_date__gte=start_date
#         ).exclude(
#             start_date_breakdown__in=["full_day", None]
#         )
#         for leave in paid_half_day_leaves_start:
#             if leave.start_date in date_range_set:
#                 paid_half_day_leave_dates.add(leave.start_date)
        
#         paid_half_day_leaves_end = employee.leaverequest_set.filter(
#             leave_type_id__payment="paid",
#             status="approved",
#             start_date__lte=end_date,
#             end_date__gte=start_date
#         ).exclude(
#             end_date_breakdown__in=["full_day", None]
#         ).exclude(start_date=F("end_date"))  # Don't double count same-day leaves
#         for leave in paid_half_day_leaves_end:
#             if leave.end_date in date_range_set:
#                 paid_half_day_leave_dates.add(leave.end_date)
        
#         # Get half-day unpaid leaves
#         unpaid_half_day_leaves_start = employee.leaverequest_set.filter(
#             leave_type_id__payment="unpaid",
#             status="approved",
#             start_date__lte=end_date,
#             end_date__gte=start_date
#         ).exclude(
#             start_date_breakdown__in=["full_day", None]
#         )
#         for leave in unpaid_half_day_leaves_start:
#             if leave.start_date in date_range_set:
#                 unpaid_half_day_leave_dates.add(leave.start_date)
        
#         unpaid_half_day_leaves_end = employee.leaverequest_set.filter(
#             leave_type_id__payment="unpaid",
#             status="approved",
#             start_date__lte=end_date,
#             end_date__gte=start_date
#         ).exclude(
#             end_date_breakdown__in=["full_day", None]
#         ).exclude(start_date=F("end_date"))
#         for leave in unpaid_half_day_leaves_end:
#             if leave.end_date in date_range_set:
#                 unpaid_half_day_leave_dates.add(leave.end_date)
        
#         print(f"Found {len(paid_half_day_leave_dates)} paid half-day leave dates and {len(unpaid_half_day_leave_dates)} unpaid half-day leave dates")
    
#     # Remove half-day leave dates from full-day leave dates to avoid double counting
#     paid_leave_dates = paid_leave_dates - paid_half_day_leave_dates
#     unpaid_leave_dates = unpaid_leave_dates - unpaid_half_day_leave_dates
    
#     # Get attendance data from WorkRecords
#     attendance_present_dates = set()
#     attendance_half_day_dates = set()
#     if apps.is_installed("attendance"):
#         WorkRecords = get_horilla_model_class(app_label="attendance", model="workrecords")
#         work_records = WorkRecords.objects.filter(
#             employee_id=employee,
#             date__range=(start_date, end_date)
#         )
#         for wr in work_records:
#             if wr.work_record_type == "FDP":  # Full Day Present
#                 attendance_present_dates.add(wr.date)
#             elif wr.work_record_type == "HDP":  # Half Day Present
#                 attendance_half_day_dates.add(wr.date)
#         print(f"Found {len(attendance_present_dates)} present days and {len(attendance_half_day_dates)} half-day days from WorkRecords")
    
#     # Check for sandwich rule (if contract has this setting)
#     contract = employee.contract_set.filter(
#         is_active=True, contract_status="active"
#     ).first()
#     sandwich_rule_enabled = False
#     if contract and hasattr(contract, 'sandwich_rule'):
#         sandwich_rule_enabled = contract.sandwich_rule
#     elif contract and hasattr(contract, 'sandwich_adjustment'):
#         sandwich_rule_enabled = contract.sandwich_adjustment
    
#     # Calculate payable_days and lop_days using Horilla-style priority logic
#     # Priority: HOLIDAY > WEEKOFF > LEAVE > ATTENDANCE > ABSENT
#     payable_days = 0
#     lop_days = 0
    
#     # Track weekoffs/holidays and their LOP status for sandwich adjustment
#     day_status_map = {}  # Track status of each day for sandwich rule
    
#     for day in date_range:
#         # HORILLA PRIORITY ORDER (check in exact order - first match wins):
#         # 1. HOLIDAY > 2. WEEKOFF > 3. LEAVE > 4. ATTENDANCE > 5. ABSENT
        
#         is_public_holiday = day in holiday_dates
#         is_weekoff = day not in working_days_list and day not in holiday_dates
        
#         # Check leaves (Priority 3: LEAVE)
#         is_paid_leave = day in paid_leave_dates
#         is_unpaid_leave = day in unpaid_leave_dates
#         is_paid_half_leave = day in paid_half_day_leave_dates
#         is_unpaid_half_leave = day in unpaid_half_day_leave_dates
#         has_any_leave = is_paid_leave or is_unpaid_leave or is_paid_half_leave or is_unpaid_half_leave
        
#         # Check attendance (Priority 4: ATTENDANCE) - only if no leave
#         is_present = day in attendance_present_dates and not has_any_leave
#         is_half_day_attendance = day in attendance_half_day_dates and not has_any_leave
        
#         # Apply priority-based decision
#         if is_public_holiday:
#             # Priority 1: Public Holiday = Paid (always paid, even if no attendance)
#             payable_days += 1
#             day_status_map[day] = 'holiday'
#             print(f"  {day}: PUBLIC HOLIDAY → Paid")
#         elif is_weekoff:
#             # Priority 2: Weekly Off = Paid (always paid)
#             payable_days += 1
#             day_status_map[day] = 'weekoff'
#             print(f"  {day}: WEEKOFF → Paid")
#         elif is_paid_half_leave:
#             # Priority 3: Paid Half-Day Leave = 0.5 Paid (half day is paid, no LOP)
#             payable_days += 0.5
#             lop_days += 0.5  # The other half day is LOP
#             day_status_map[day] = 'paid_half_leave_lop'
#             print(f"  {day}: PAID HALF-DAY LEAVE → 0.5 Paid + 0.5 LOP")
#         elif is_paid_leave:
#             # Priority 3: Paid Leave = Paid
#             payable_days += 1
#             day_status_map[day] = 'paid_leave'
#             print(f"  {day}: PAID LEAVE → Paid")
#         elif is_unpaid_half_leave:
#             # Priority 3: Unpaid Half-Day Leave = 0.5 Paid + 0.5 LOP
#             payable_days += 0.5
#             lop_days += 0.5
#             day_status_map[day] = 'unpaid_half_leave_lop'
#             print(f"  {day}: UNPAID HALF-DAY LEAVE → 0.5 Paid + 0.5 LOP")
#         elif is_unpaid_leave:
#             # Priority 3: Unpaid Leave = LOP
#             lop_days += 1
#             day_status_map[day] = 'unpaid_leave_lop'
#             print(f"  {day}: UNPAID LEAVE → LOP")
#         elif is_present:
#             # Priority 4: Present = Paid
#             payable_days += 1
#             day_status_map[day] = 'present'
#             print(f"  {day}: PRESENT → Paid")
#         elif is_half_day_attendance:
#             # Priority 4: Half Day Attendance = 0.5 Paid + 0.5 LOP
#             payable_days += 0.5
#             lop_days += 0.5
#             day_status_map[day] = 'half_day_lop'
#             print(f"  {day}: HALF-DAY ATTENDANCE → 0.5 Paid + 0.5 LOP")
#         else:
#             # Priority 5: Absent = LOP (no holiday, no weekoff, no leave, no attendance)
#             lop_days += 1
#             day_status_map[day] = 'absent_lop'
#             print(f"  {day}: ABSENT → LOP")
    
#     # Apply Sandwich Adjustment if enabled
#     # Sandwich Rule: If a Weekoff/Holiday is between two LOP days, convert it to LOP
#     if sandwich_rule_enabled:
#         print(f"Sandwich rule enabled, applying adjustment...")
#         sandwich_adjustments = 0
#         for day in date_range:
#             # Only check weekoffs and holidays for sandwich adjustment
#             if day_status_map.get(day) not in ['holiday', 'weekoff']:
#                 continue
            
#             prev_date = day - timedelta(days=1)
#             next_date = day + timedelta(days=1)
            
#             # Skip if dates are outside the period
#             if prev_date < start_date or next_date > end_date:
#                 continue
            
#             # Check if previous day is LOP (any LOP status)
#             prev_status = day_status_map.get(prev_date)
#             prev_is_lop = prev_status and 'lop' in prev_status.lower()
            
#             # Check if next day is LOP
#             next_status = day_status_map.get(next_date)
#             next_is_lop = next_status and 'lop' in next_status.lower()
            
#             if prev_is_lop and next_is_lop:
#                 # Apply sandwich adjustment: convert holiday/weekoff to LOP
#                 payable_days -= 1
#                 lop_days += 1
#                 sandwich_adjustments += 1
#                 day_status_map[day] = 'sandwich_lop'
#                 print(f"Sandwich adjustment applied for {day} (sandwiched between LOP days: {prev_date} and {next_date})")
        
#         if sandwich_adjustments > 0:
#             print(f"Total sandwich adjustments: {sandwich_adjustments}")
    
#     # HORILLA-STYLE: Calculate basic_pay based on date range (calendar days)
#     # payable_days = (end_date - start_date) + 1 (calendar days in period)
#     # per_day_basic = monthly_basic / total_calendar_days
#     # basic_pay = per_day_basic * payable_days
    
#     # Use calendar days for basic pay calculation (not attendance-based payable_days)
#     payable_days_for_basic = payable_days_calendar  # Calendar days in period
    
#     # Calculate per_day_basic using total calendar days in month
#     if total_calendar_days > 0:
#         per_day_basic = wage / total_calendar_days
#     else:
#         per_day_basic = 0
    
#     # Calculate basic_pay = per_day_basic * payable_days
#     updated_basic_pay = per_day_basic * payable_days_for_basic
    
#     # For display/reporting: keep attendance-based paid_days and unpaid_days
#     paid_days = payable_days  # Attendance-based paid days (for reporting)
#     unpaid_days = lop_days  # LOP days from attendance logic
    
#     print(f"Calculated - Paid Days (attendance): {paid_days}, LOP Days: {unpaid_days}")
#     print(f"Payable Days (calendar): {payable_days_for_basic}")
    
#     print(f"=== BASIC PAY CALCULATION (HORILLA-STYLE) ===")
#     print(f"Monthly Basic Pay (wage): {wage}")
#     print(f"Total Calendar Days in Month: {total_calendar_days}")
#     print(f"Per day basic: {per_day_basic:.2f}")
#     print(f"Payable Days (calendar): {payable_days_for_basic}")
#     print(f"Basic Pay = {per_day_basic:.2f} * {payable_days_for_basic} = {updated_basic_pay:.2f}")
#     print(f"=============================================")
    
#     # Calculate loss of pay amount (using per_day_basic)
#     loss_of_pay = per_day_basic * unpaid_days
    
#     # Calculate daily computed salary (for compatibility with existing code)
#     daily_computed_salary = get_daily_salary(wage=wage, wage_date=start_date, company=company)[
#         "day_wage"
#     ]
    
#     # Use updated_basic_pay as the basic_pay (this is what shows as "Updated Basic Pay" in payslip)
#     basic_pay = updated_basic_pay
    
#     print(f"Final Basic Pay (Updated): {basic_pay:.2f}, Loss of Pay: {loss_of_pay:.2f}")
        
#     return {
#         "basic_pay": basic_pay,
#         "loss_of_pay": loss_of_pay,
#         "month_data": month_data,
#         "unpaid_days": unpaid_days,
#         "paid_days": paid_days,
#         "contract": contract,
#     }

def monthly_computation(employee, wage, start_date, end_date, *args, **kwargs):
    """
    Hourly salary computation for period.

    Args:
        employee (obj): Employee instance
        wage (float): wage of the employee
        start_date (obj): start of the pay period
        end_date (obj): end date of the period
    """
    basic_pay = 0
    month_data = months_between_range(wage, start_date, end_date)

    leave_data = get_leaves(employee, start_date, end_date)

    for data in month_data:
        basic_pay = basic_pay + (
            data["working_days_on_period"] * data["per_day_amount"]
        )

    contract = employee.contract_set.filter(contract_status="active").first()
    loss_of_pay = 0
    date_range = get_date_range(start_date, end_date)
    if apps.is_installed("leave"):
        start_date_leaves = (
            employee.leaverequest_set.filter(
                leave_type_id__payment="unpaid",
                start_date__in=date_range,
                status="approved",
            )
            .exclude(start_date_breakdown="full_day")
            .count()
        )
        end_date_leaves = (
            employee.leaverequest_set.filter(
                leave_type_id__payment="unpaid",
                end_date__in=date_range,
                status="approved",
            )
            .exclude(end_date_breakdown="full_day")
            .exclude(start_date=F("end_date"))
            .count()
        )
    else:
        start_date_leaves = 0
        end_date_leaves = 0

    half_day_leaves_between_period_on_start_date = start_date_leaves

    half_day_leaves_between_period_on_end_date = end_date_leaves

    unpaid_half_leaves = (
        half_day_leaves_between_period_on_start_date
        + half_day_leaves_between_period_on_end_date
    ) * 0.5

    contract = employee.contract_set.filter(
        is_active=True, contract_status="active"
    ).first()
    unpaid_leaves = abs(leave_data["unpaid_leaves"] - unpaid_half_leaves)
    paid_days = month_data[0]["working_days_on_period"] - unpaid_leaves
    daily_computed_salary = get_daily_salary(wage=wage, wage_date=start_date)[
        "day_wage"
    ]
    if contract.calculate_daily_leave_amount:
        loss_of_pay = (unpaid_leaves) * daily_computed_salary
    else:
        fixed_penalty = contract.deduction_for_one_leave_amount
        loss_of_pay = (unpaid_leaves) * fixed_penalty

    if contract.deduct_leave_from_basic_pay:
        basic_pay = basic_pay - loss_of_pay
    return {
        "basic_pay": basic_pay,
        "loss_of_pay": loss_of_pay,
        "month_data": month_data,
        "unpaid_days": unpaid_leaves,
        "paid_days": paid_days,
        "contract": contract,
    }



def compute_salary_on_period(employee, start_date, end_date, wage=None):
    """
    This method is used to compute salary on the start to end date period

    Args:
        employee (obj): Employee instance
        start_date (obj): start date of the period
        end_date (obj): end date of the period
        wage (float, optional): The wage to be used for calculation. If provided and no contract exists, uses this wage with monthly computation.
    """
    print(f"--- compute_salary_on_period called for employee ID={employee.id} from {start_date} to {end_date} ---")
    contract = Contract.objects.filter(
        employee_id=employee, contract_status="active"
    ).first()
    
    # If no contract but wage is provided, use monthly computation with provided wage
    if contract is None:
        if wage is not None and wage > 0:
            print(f"No active contract found, but wage provided ({wage}). Using monthly computation with provided wage.")
            # Use monthly computation as default when no contract exists
            company = None
            if hasattr(employee, "employee_work_info") and employee.employee_work_info:
                company = employee.employee_work_info.company_id
            data = monthly_computation(employee, wage, start_date, end_date)
            month_data = months_between_range(wage, start_date, end_date, company=company)
            data["month_data"] = month_data
            data["contract_wage"] = wage
            data["contract"] = None  # No contract, but we have wage
            return data
        else:
            print("No active contract found and no wage provided.")
            return None

    wage = contract.wage if wage is None else wage
    wage_type = contract.wage_type
    data = None
    print(f"Contract wage_type: {wage_type}, wage: {wage}")
    
    company = None
    if hasattr(employee, "employee_work_info") and employee.employee_work_info:
        company = employee.employee_work_info.company_id

    if wage_type == "hourly":
        data = hourly_computation(employee, wage, start_date, end_date)
        month_data = months_between_range(wage, start_date, end_date, company=company)
        data["month_data"] = month_data
    elif wage_type == "daily":
        data = daily_computation(employee, wage, start_date, end_date)
        month_data = months_between_range(wage, start_date, end_date, company=company)
        data["month_data"] = month_data

    else:
        data = monthly_computation(employee, wage, start_date, end_date)
        
    data["contract_wage"] = wage
    data["contract"] = contract
    print(f"Returning computed salary data for {wage_type} type.")
    return data


def paginator_qry(qryset, page_number):
    """
    This method is used to paginate queryset
    """
    print(f"--- paginator_qry called for queryset with page_number={page_number} ---")
    paginator = Paginator(qryset, get_pagination())
    qryset = paginator.get_page(page_number)
    print(f"Paginator returned page {page_number}")
    return qryset


def calculate_employer_contribution(data):
    """
    This method is used to calculate the employer contribution
    """
    print("--- calculate_employer_contribution called ---")
    pay_head_data = data.get("pay_data", {}) or {}

    deductions_to_process = [
        pay_head_data.get("pretax_deductions"),
        pay_head_data.get("post_tax_deductions"),
        pay_head_data.get("tax_deductions"),
        pay_head_data.get("net_deductions"),
    ]

    for deductions in deductions_to_process:
        if not deductions:
            continue

        for deduction in deductions:
            deduction_id = deduction.get("deduction_id")
            employer_rate = deduction.get("employer_contribution_rate", 0)

            if deduction_id and employer_rate > 0:
                obj = Deduction.objects.filter(id=deduction_id).first()
                if not obj:
                    continue

                # ✅ Use 0 if not found or not numeric
                amount = pay_head_data.get(obj.based_on) or 0
                try:
                    amount = float(amount)
                except (TypeError, ValueError):
                    amount = 0.0

                employer_contribution_amount = (amount * float(obj.employer_rate or 0)) / 100
                print(f"Deduction ID {deduction_id}: Calculated employer contribution amount: {employer_contribution_amount}")

                deduction["based_on"] = obj.based_on
                deduction["employer_contribution_amount"] = employer_contribution_amount

    print("Returning data with updated employer contributions.")
    return data


def save_payslip(**kwargs):
    """
    This method is used to save the generated payslip
    """
    print(f"--- save_payslip called for employee ID={kwargs.get('employee').id} from {kwargs.get('start_date')} to {kwargs.get('end_date')} ---")
    filtered_instance = Payslip.objects.filter(
        employee_id=kwargs["employee"],
        start_date=kwargs["start_date"],
        end_date=kwargs["end_date"],
    ).first()
    
    if filtered_instance:
        print(f"Existing payslip found (ID: {filtered_instance.id}). Updating.")
    else:
        print("New payslip instance created for saving.")
        
    instance = filtered_instance if filtered_instance is not None else Payslip()
    instance.employee_id = kwargs["employee"]
    instance.group_name = kwargs.get("group_name")
    instance.start_date = kwargs["start_date"]
    instance.end_date = kwargs["end_date"]
    instance.status = kwargs["status"]
    instance.basic_pay = round(kwargs["basic_pay"], 2)
    instance.contract_wage = round(kwargs["contract_wage"], 2)
    instance.gross_pay = round(kwargs["gross_pay"], 2)
    instance.deduction = round(kwargs["deduction"], 2)
    instance.net_pay = round(kwargs["net_pay"], 2)
    instance.pay_head_data = kwargs["pay_data"]
    instance.save()
    instance.installment_ids.set(kwargs["installments"])
    
    print(f"Payslip saved/updated with ID: {instance.id}")
    return instance