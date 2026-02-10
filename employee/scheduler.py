import datetime
import sys
from datetime import timedelta, datetime as dt

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from django.urls import reverse
from notifications.signals import notify


def update_experience():
    from employee.models import EmployeeWorkInformation

    """
    This scheduled task to trigger the experience calculator
    to update the employee work experience
    """
    queryset = EmployeeWorkInformation.objects.filter(employee_id__is_active=True)
    for instance in queryset:
        instance.experience_calculator()
    return


def block_unblock_disciplinary():
    """
    This scheduled task to trigger the Disciplinary action and take the suspens
    """
    from base.models import EmployeeShiftSchedule
    from employee.models import DisciplinaryAction
    from employee.policies import employee_account_block_unblock

    dis_action = DisciplinaryAction.objects.all()
    for dis in dis_action:

        if dis.action.block_option:
            if dis.action.action_type == "suspension":
                if dis.days:
                    day = dis.days
                    end_date = dis.start_date + timedelta(days=day)
                    if (
                        datetime.date.today() >= dis.start_date
                        or datetime.date.today() >= end_date
                    ):
                        if datetime.date.today() >= dis.start_date:
                            r = False
                        if datetime.date.today() >= end_date:
                            r = True

                        employees = dis.employee_id.all()
                        for emp in employees:
                            employee_account_block_unblock(emp_id=emp.id, result=r)

                if dis.hours:
                    hour_str = dis.hours + ":00"
                    if hour_str > "00:00:00":

                        # Checking the date of action date.
                        if datetime.date.today() >= dis.start_date:

                            employees = dis.employee_id.all()
                            for emp in employees:

                                # Taking the shift of employee for taking the work start time
                                shift = emp.employee_work_info.shift_id
                                shift_detail = EmployeeShiftSchedule.objects.filter(
                                    shift_id=shift
                                )
                                for shi in shift_detail:
                                    today = datetime.datetime.today()
                                    day_of_week = today.weekday()

                                    # List of weekday names
                                    weekday_names = [
                                        "monday",
                                        "tuesday",
                                        "wednesday",
                                        "thursday",
                                        "friday",
                                        "saturday",
                                        "sunday",
                                    ]
                                    if weekday_names[day_of_week] == shi.day.day:

                                        st_time = shi.start_time

                                        hour_time = datetime.datetime.strptime(
                                            hour_str, "%H:%M:%S"
                                        ).time()

                                        time1 = st_time
                                        time2 = hour_time

                                        # Convert them to datetime objects
                                        datetime1 = datetime.datetime.combine(
                                            datetime.date.today(), time1
                                        )
                                        datetime2 = datetime.datetime.combine(
                                            datetime.date.today(), time2
                                        )

                                        # Add the datetime objects
                                        result_datetime = (
                                            datetime1
                                            + datetime.timedelta(
                                                hours=datetime2.hour,
                                                minutes=datetime2.minute,
                                                seconds=datetime2.second,
                                            )
                                        )

                                        # Extract the time component from the result
                                        result_time = result_datetime.time()

                                        # Get the current time
                                        current_time = datetime.datetime.now().time()

                                        # Check if the current time matches st_time
                                        if current_time >= st_time:
                                            r = False
                                        if current_time >= result_time:
                                            r = True

                                    employee_account_block_unblock(
                                        emp_id=emp.id, result=r
                                    )

            if dis.action.action_type == "dismissal":
                if datetime.date.today() >= dis.start_date:
                    if datetime.date.today() >= dis.start_date:
                        r = False
                    employees = dis.employee_id.all()
                    for emp in employees:
                        employee_account_block_unblock(emp_id=emp.id, result=r)

    return


def notify_expiring_documents():
    """
    This scheduled task to check for expiring or expired documents
    and send notifications to the employee's reporting manager.
    """
    from django.contrib.auth.models import User
    
    from horilla_documents.models import Document

    today = datetime.date.today()
    
    # Get all documents with expiry dates
    documents = Document.objects.filter(
        expiry_date__isnull=False,
        employee_id__is_active=True,
    )
    
    bot = User.objects.filter(username="Horilla Bot").first()
    if not bot:
        # Fallback to superuser if bot doesn't exist
        bot = User.objects.filter(is_superuser=True).first()
    
    if not bot:
        return
    
    for document in documents:
        try:
            employee = document.employee_id
            if not employee:
                continue
                
            # Get the reporting manager
            reporting_manager = employee.get_reporting_manager()
            if not reporting_manager:
                continue
            
            # Get the user object for the reporting manager
            if not hasattr(reporting_manager, 'employee_user_id') or not reporting_manager.employee_user_id:
                continue
            
            recipient = reporting_manager.employee_user_id
            if not recipient:
                continue
            
            expiry_date = document.expiry_date
            if not expiry_date:
                continue
                
            notify_before = document.notify_before or 1  # Default to 1 day if not set
            
            # Calculate the notification date (expiry_date - notify_before days)
            notify_date = expiry_date - timedelta(days=notify_before)
            
            # Check if document has expired (today >= expiry_date)
            # Only check past/current dates as per system's attendance logic
            if today >= expiry_date:
                notify.send(
                    employee,
                    recipient=recipient,
                    verb=f"Document '{document.title}' has expired",
                    verb_ar=f"انتهت صلاحية المستند '{document.title}'",
                    verb_de=f"Dokument '{document.title}' ist abgelaufen",
                    verb_es=f"El documento '{document.title}' ha expirado",
                    verb_fr=f"Le document '{document.title}' a expiré",
                    redirect=reverse(
                        "employee-view-individual",
                        kwargs={"obj_id": employee.id},
                    ),
                    icon="chatbox-ellipses",
                )
            # Check if document is expiring soon (today == notify_date)
            # Only check past/current dates as per system's attendance logic
            elif today == notify_date:
                notify.send(
                    employee,
                    recipient=recipient,
                    verb=f"Document '{document.title}' is expiring in {notify_before} day(s)",
                    verb_ar=f"ينتهي المستند '{document.title}' خلال {notify_before} يوم(أيام)",
                    verb_de=f"Dokument '{document.title}' läuft in {notify_before} Tag(en) ab",
                    verb_es=f"El documento '{document.title}' caduca en {notify_before} día(s)",
                    verb_fr=f"Le document '{document.title}' expire dans {notify_before} jour(s)",
                    redirect=reverse(
                        "employee-view-individual",
                        kwargs={"obj_id": employee.id},
                    ),
                    icon="chatbox-ellipses",
                )
        except Exception:
            # Continue processing other documents if one fails
            continue
    
    return


if not any(
    cmd in sys.argv
    for cmd in ["makemigrations", "migrate", "compilemessages", "flush", "shell"]
):
    """
    Initializes and starts background tasks using APScheduler when the server is running.
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_experience, "interval", hours=4)
    scheduler.add_job(block_unblock_disciplinary, "interval", seconds=25)
    scheduler.add_job(notify_expiring_documents, "interval", days=1)
    scheduler.start()
