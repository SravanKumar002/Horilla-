"""
Middleware to automatically trigger employee clock-out based on shift schedules
"""

from datetime import datetime, timedelta

from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from attendance.methods.utils import Request
from notifications.signals import notify
from django.urls import reverse

class AttendanceMiddleware(MiddlewareMixin):
    """
    This middleware checks for employees who haven't clocked out by the end of their
    scheduled shift and automatically performs the clock-out action if the auto punch-out
    is enabled for their shift. It processes this during each request.
    """

    def process_request(self, request):
        """
        Triggers the `trigger_function` on each request.
        """
        self.trigger_function()

    def trigger_function(self):
        """
        Retrieves shift schedules with auto punch-out enabled and checks if there are
        any attendance activities that haven't been clocked out. If the scheduled
        auto punch-out time has passed, the function attempts to clock out the employee
        automatically by invoking the `clock_out` function.
        """
        from attendance.models import Attendance, AttendanceActivity, WorkRecords
        from attendance.views.clock_in_out import clock_out
        from base.models import EmployeeShiftSchedule

        automatic_check_out_shifts = EmployeeShiftSchedule.objects.filter(
            is_auto_punch_out_enabled=True
        )

        for shift_schedule in automatic_check_out_shifts:
            activities = AttendanceActivity.objects.filter(
                shift_day=shift_schedule.day,
                clock_out_date=None,
                clock_out=None,
            ).order_by("-created_at")

            for activity in activities:
                
                attendance = Attendance.objects.filter(
                    employee_id=activity.employee_id,
                    attendance_clock_out=None,
                    attendance_clock_out_date=None,
                    shift_id=shift_schedule.shift_id,
                    attendance_day=shift_schedule.day,
                    attendance_date=activity.attendance_date,
                ).first()

                if attendance:
                    date = activity.attendance_date
                    if shift_schedule.is_night_shift:
                        date += timedelta(days=1)

                    combined_datetime = timezone.make_aware(
                        datetime.combine(date, shift_schedule.auto_punch_out_time)
                    )
                    current_time = timezone.now()

                    if combined_datetime < current_time:
                        try:
                            clock_out(
                                Request(
                                    user=attendance.employee_id.employee_user_id,
                                    date=date,
                                    time=shift_schedule.auto_punch_out_time,
                                    datetime=combined_datetime,
                                )
                            )

                            # ==================================
                            #  NOTIFICATION FOR AUTO CLOCK-OUT
                            # ==================================
                            try:
                                formatted_date = date.strftime("%d-%m-%Y")

                                notify.send(
                                    attendance.employee_id,
                                    recipient=attendance.employee_id.employee_user_id,
                                    verb=f"You were automatically clocked out for {formatted_date} at {shift_schedule.auto_punch_out_time.strftime('%I:%M %p')}.",
                                    verb_ar=f"تم تسجيل خروجك تلقائيًا ليوم {formatted_date} في {shift_schedule.auto_punch_out_time.strftime('%I:%M %p')}.",
                                    verb_de=f"Sie wurden automatisch am {formatted_date} um {shift_schedule.auto_punch_out_time.strftime('%I:%M %p')} ausgestempelt.",
                                    verb_es=f"Se te marcó la salida automáticamente el {formatted_date} a las {shift_schedule.auto_punch_out_time.strftime('%I:%M %p')}.",
                                    verb_fr=f"Vous avez été déconnecté automatiquement le {formatted_date} à {shift_schedule.auto_punch_out_time.strftime('%I:%M %p')}.",
                                    icon="clock",
                                    redirect=reverse("request-attendance-view"),
                                )

                                print("Auto clock-out notification sent.")
                            except Exception as ne:
                                print("Auto clock-out notification failed:", ne)



                        # Mark WorkRecord as Missed Check Out after auto punch-out
                            try:
                                wr, _ = WorkRecords.objects.get_or_create(
                                    date=attendance.attendance_date,
                                    employee_id=attendance.employee_id,
                                )
                                wr.is_attendance_record = True
                                wr.attendance_id = attendance
                                wr.shift_id = attendance.shift_id
                                wr.work_record_type = "MCO"
                                wr.message = "Missed Check Out (Auto)"
                                wr.save()
                                print("WorkRecord updated for auto checkout.")
                            except Exception as we:
                                print(f"Failed to update WorkRecord for auto checkout: {we}")
                        except Exception as e:
                            print(f"{e}")
