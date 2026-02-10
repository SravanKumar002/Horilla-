from datetime import date, datetime
from calendar import monthrange

from django.shortcuts import render

from attendance.models import Attendance, AttendanceLateComeEarlyOut


def own_attendance_month(request):
    """
    Render a table view listing every date in a requested month for the
    current user's employee record, with attendance data where present.

    Query params (optional): `year`, `month`.
    """
    try:
        year = int(request.GET.get("year", datetime.now().year))
        month = int(request.GET.get("month", datetime.now().month))
    except Exception:
        year = datetime.now().year
        month = datetime.now().month

    user = request.user
    employee = getattr(user, "employee_get", None) or getattr(user, "employee", None)

    # If no employee for this user, render empty calendar message
    if not employee:
        return render(request, "attendance/own_attendance/attendances_month.html", {"days": [], "month": month, "year": year})

    _, last_day = monthrange(year, month)
    first = date(year, month, 1)
    last = date(year, month, last_day)

    attendances_qs = Attendance.objects.filter(employee_id=employee, attendance_date__range=(first, last))
    attendances = list(attendances_qs)
    att_map = {a.attendance_date: a for a in attendances}

    # Build late/early map and penalties map similar to other views
    late_map = {}
    late_penalties_map = {}
    late_entries = AttendanceLateComeEarlyOut.objects.select_related("attendance_id").filter(attendance_id__in=attendances)
    for entry in late_entries:
        att_id = entry.attendance_id_id
        if not att_id:
            continue
        item = {"type": entry.get_type_display(), "penalties": entry.get_penalties_count()}
        late_map.setdefault(att_id, []).append(item)
        late_penalties_map[att_id] = late_penalties_map.get(att_id, 0) + item["penalties"]

    days = []
    for d in range(1, last_day + 1):
        cur = date(year, month, d)
        att = att_map.get(cur)
        if att:
            if att.is_validate_request_approved or att.attendance_validated:
                status = "approved"
            elif att.is_validate_request:
                status = "requested"
            else:
                status = "on_time"
            types = [it["type"] for it in late_map.get(att.id, [])]
            penalties = late_penalties_map.get(att.id, 0)
        else:
            status = "no_record"
            types = []
            penalties = 0

        days.append(
            {
                "date": cur,
                "attendance": att,
                "types": types,
                "penalties": penalties,
                "status": status,
            }
        )

    return render(request, "attendance/own_attendance/attendances_month.html", {"days": days, "month": month, "year": year})
