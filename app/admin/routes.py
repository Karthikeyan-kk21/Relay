from functools import wraps
from flask import render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
import pytz
from datetime import datetime, date

from app.admin import admin_bp
from app.extensions import db
from app.models import User, Attendance, Worksheet, Setting, Holiday

IST = pytz.timezone("Asia/Kolkata")


def get_ist_now():
    return datetime.now(IST).replace(tzinfo=None)


def get_ist_today():
    return datetime.now(IST).date()


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ─── Dashboard ────────────────────────────────────────────────────────────────

@admin_bp.route("/dashboard")
@login_required
@admin_required
def dashboard():
    date_str = request.args.get("date")
    selected_date = get_ist_today()
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    employees = User.query.filter_by(role="user", active=True).all()

    # Build enriched employee data for the selected date
    emp_data = []
    for emp in employees:
        attendance = Attendance.query.filter_by(user_id=emp.id, date=selected_date).first()
        worksheet = Worksheet.query.filter_by(user_id=emp.id, date=selected_date).first()
        emp_data.append({
            "user": emp,
            "attendance": attendance,
            "worksheet": worksheet,
        })

    # Summary counts
    statuses = [e["attendance"].status if e["attendance"] else "Absent" for e in emp_data]
    summary = {
        "total": len(employees),
        "present": statuses.count("Present") + statuses.count("On Time"),
        "late": statuses.count("Late"),
        "absent": statuses.count("Absent"),
        "wfh": statuses.count("WFH"),
        "hd": statuses.count("HD") + statuses.count("Half Day"),
        "worksheet_updated": sum(
            1 for e in emp_data if e["worksheet"] and e["worksheet"].is_submitted()
        ),
        "worksheet_pending": sum(
            1 for e in emp_data if not e["worksheet"] or not e["worksheet"].is_submitted()
        ),
    }

    # Calculate previous and next dates for navigation
    from datetime import timedelta
    prev_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)

    return render_template(
        "admin/dashboard.html",
        emp_data=emp_data,
        summary=summary,
        today=selected_date,
        prev_date_str=prev_date.strftime("%Y-%m-%d"),
        next_date_str=next_date.strftime("%Y-%m-%d"),
        selected_date_str=selected_date.strftime("%Y-%m-%d"),
        is_today=(selected_date == get_ist_today()),
    )


# ─── Mark WFH / HD ────────────────────────────────────────────────────────────

@admin_bp.route("/attendance/mark/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def mark_status(user_id):
    status = request.form.get("status")
    if status not in ("WFH", "Leave", "Present", "Late", "Absent"):
        return jsonify({"success": False, "message": "Invalid status."}), 400

    today = get_ist_today()
    attendance = Attendance.query.filter_by(user_id=user_id, date=today).first()

    if attendance:
        attendance.status = status
    else:
        attendance = Attendance(
            user_id=user_id,
            date=today,
            status=status,
        )
        db.session.add(attendance)

    db.session.commit()
    return jsonify({"success": True, "message": f"Status updated to {status}."})


# ─── Unlock Worksheet ─────────────────────────────────────────────────────────

@admin_bp.route("/worksheet/unlock/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def unlock_worksheet(user_id):
    today = get_ist_today()
    ws = Worksheet.query.filter_by(user_id=user_id, date=today).first()

    if not ws:
        ws = Worksheet(
            user_id=user_id,
            date=today,
            is_locked=False,
            admin_unlocked=True,
        )
        db.session.add(ws)
    else:
        ws.is_locked = False
        ws.admin_unlocked = True

    db.session.commit()
    return jsonify({"success": True, "message": "Worksheet unlocked for employee."})


# ─── Lock Worksheet ───────────────────────────────────────────────────────────

@admin_bp.route("/worksheet/lock/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def lock_worksheet(user_id):
    today = get_ist_today()
    ws = Worksheet.query.filter_by(user_id=user_id, date=today).first()

    if ws:
        ws.is_locked = True
        ws.admin_unlocked = False
        db.session.commit()

    return jsonify({"success": True, "message": "Worksheet locked."})


# ─── User Management ──────────────────────────────────────────────────────────

@admin_bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.filter_by(role="user").order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users)


@admin_bp.route("/users/create", methods=["POST"])
@login_required
@admin_required
def create_user():
    employee_id = request.form.get("employee_id", "").strip()
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    joining_date_str = request.form.get("joining_date", "").strip()

    if not all([employee_id, full_name, email, password]):
        flash("All fields are required.", "error")
        return redirect(url_for("admin.users"))

    if User.query.filter_by(employee_id=employee_id).first():
        flash(f"Employee ID '{employee_id}' already exists.", "error")
        return redirect(url_for("admin.users"))

    if User.query.filter_by(email=email).first():
        flash(f"Email '{email}' already registered.", "error")
        return redirect(url_for("admin.users"))

    joining_dt = get_ist_today()
    if joining_date_str:
        try:
            joining_dt = datetime.strptime(joining_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    user = User(
        employee_id=employee_id,
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
        role="user",
        active=True,
        joining_date=joining_dt,
    )
    db.session.add(user)
    db.session.commit()
    flash(f"Employee '{full_name}' created successfully.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/update/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    joining_date_str = request.form.get("joining_date", "").strip()

    if full_name:
        user.full_name = full_name
    if email:
        user.email = email
    if joining_date_str:
        try:
            user.joining_date = datetime.strptime(joining_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    db.session.commit()
    return jsonify({"success": True, "message": "Employee details updated successfully."})


@admin_bp.route("/users/toggle/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.active = not user.active
    db.session.commit()
    status = "activated" if user.active else "deactivated"
    return jsonify({"success": True, "message": f"Employee {status}.", "active": user.active})


@admin_bp.route("/users/reset-password/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get("new_password", "").strip()
    if not new_password or len(new_password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters."}), 400
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return jsonify({"success": True, "message": "Password reset successfully."})


# ─── Settings ─────────────────────────────────────────────────────────────────

@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    from app.models.setting import DEFAULT_SETTINGS

    if request.method == "POST":
        keys = ["office_ip", "checkin_time", "late_threshold", "worksheet_lock_time", "last_entry_time", "disable_timing_lock", "weekend_policy", "maintenance_mode"]
        for key in keys:
            val = request.form.get(key, "").strip()
            Setting.set_value(key, val)
        flash("Settings saved successfully.", "success")
        return redirect(url_for("admin.settings"))

    # Load current settings
    current_settings = {}
    for s in DEFAULT_SETTINGS:
        current_settings[s["key"]] = {
            "value": Setting.get(s["key"], s["value"]),
            "description": s["description"],
        }

    return render_template("admin/settings.html", settings=current_settings)


# ─── CEO Report ───────────────────────────────────────────────────────────────

@admin_bp.route("/report")
@login_required
@admin_required
def report():
    today = get_ist_today()
    return render_template("admin/report.html", today=today)


@admin_bp.route("/report/generate", methods=["POST"])
@login_required
@admin_required
def generate_report():
    from app.ai.gemini import generate_ceo_report
    date_str = request.form.get("date", str(get_ist_today()))
    try:
        from datetime import date
        report_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"success": False, "message": "Invalid date format."}), 400

    result = generate_ceo_report(report_date)
    return jsonify(result)


@admin_bp.route("/report/export/txt", methods=["POST"])
@login_required
@admin_required
def export_txt():
    from flask import Response
    content = request.form.get("content", "")
    date_str = request.form.get("date", str(get_ist_today()))
    filename = f"relay_report_{date_str}.txt"
    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@admin_bp.route("/report/export/pdf", methods=["POST"])
@login_required
@admin_required
def export_pdf():
    from flask import Response
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.units import cm

    content = request.form.get("content", "")
    date_str = request.form.get("date", str(get_ist_today()))
    filename = f"relay_report_{date_str}.pdf"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=12,
    )
    body_style = ParagraphStyle(
        "body",
        parent=styles["Normal"],
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#333333"),
    )

    story = []
    story.append(Paragraph(f"Relay Daily Report — {date_str}", title_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#4f8ef7")))
    story.append(Spacer(1, 0.3*cm))

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 0.2*cm))
        else:
            story.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), body_style))

    doc.build(story)
    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─── Unlock Check-in ──────────────────────────────────────────────────────────

@admin_bp.route("/attendance/unlock-checkin/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def unlock_checkin(user_id):
    date_str = request.form.get("date")
    selected_date = get_ist_today()
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    attendance = Attendance.query.filter_by(user_id=user_id, date=selected_date).first()
    if not attendance:
        attendance = Attendance(
            user_id=user_id,
            date=selected_date,
            status="Absent",
            admin_unlocked=True
        )
        db.session.add(attendance)
    else:
        attendance.admin_unlocked = True

    db.session.commit()
    return jsonify({"success": True, "message": "Check-in unlocked for employee."})


# ─── Edit Check-in/out Times ──────────────────────────────────────────────────

@admin_bp.route("/attendance/edit-times/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def edit_times(user_id):
    check_in_str = request.form.get("check_in", "").strip()
    check_out_str = request.form.get("check_out", "").strip()
    date_str = request.form.get("date")
    
    selected_date = get_ist_today()
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"success": False, "message": "Invalid date format."}), 400

    attendance = Attendance.query.filter_by(user_id=user_id, date=selected_date).first()

    # Convert times to datetimes
    check_in_dt = None
    if check_in_str:
        try:
            h, m = map(int, check_in_str.split(":"))
            check_in_dt = datetime.combine(selected_date, datetime.min.time().replace(hour=h, minute=m))
        except ValueError:
            return jsonify({"success": False, "message": "Invalid check-in time format."}), 400

    check_out_dt = None
    if check_out_str:
        try:
            h, m = map(int, check_out_str.split(":"))
            check_out_dt = datetime.combine(selected_date, datetime.min.time().replace(hour=h, minute=m))
        except ValueError:
            return jsonify({"success": False, "message": "Invalid check-out time format."}), 400

    # Re-calculate status if check-in is set or cleared
    status = "Absent"
    if check_in_dt:
        cal_day = Holiday.query.filter_by(date=selected_date).first()
        if cal_day and cal_day.day_type == "WFH":
            status = "WFH"
        elif cal_day and cal_day.day_type == "Half Day":
            status = "HD"
        else:
            checkin_deadline = Setting.get("checkin_time", "09:30")
            ch, cm = map(int, checkin_deadline.split(":"))
            on_time_limit = check_in_dt.replace(hour=ch, minute=cm, second=0, microsecond=0)
            if check_in_dt <= on_time_limit:
                status = "Present"
            else:
                status = "Late"

    if not attendance:
        attendance = Attendance(
            user_id=user_id,
            date=selected_date,
            check_in=check_in_dt,
            check_out=check_out_dt,
            status=status
        )
        db.session.add(attendance)
    else:
        attendance.check_in = check_in_dt
        attendance.check_out = check_out_dt
        if not check_in_dt:
            attendance.status = "Absent"
        elif attendance.status in ("Absent", "Present", "Late", "HD", "WFH"):
            attendance.status = status


    db.session.commit()
    return jsonify({
        "success": True,
        "message": "Times updated successfully.",
        "check_in": attendance.check_in_ist(),
        "check_out": attendance.check_out_ist(),
        "status": attendance.status,
        "status_color": attendance.status_color()
    })


# ─── Monthly Attendance Sheet Grid ──────────────────────────────────────────

@admin_bp.route("/sheet")
@login_required
@admin_required
def sheet():
    import calendar
    today = get_ist_today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
    except ValueError:
        year = today.year
        month = today.month

    # Get total days in month
    num_days = calendar.monthrange(year, month)[1]

    # Load Weekend Policy
    weekend_policy = Setting.get("weekend_policy", "sunday_only")

    # Build list of day objects
    days = []
    working_days_count = 0
    for day in range(1, num_days + 1):
        d = date(year, month, day)
        weekday_name = d.strftime("%a")
        is_sunday = d.weekday() == 6
        is_saturday = d.weekday() == 5

        if is_sunday:
            is_weekend_off = True
        elif is_saturday and weekend_policy == "sat_sun":
            is_weekend_off = True
        else:
            is_weekend_off = False

        if not is_weekend_off:
            working_days_count += 1

        days.append({
            "day": day,
            "date": d,
            "weekday": weekday_name,
            "label": f"{weekday_name} {day}",
            "is_weekend": is_weekend_off,
            "is_saturday": is_saturday
        })

    # Fetch all employees
    employees = User.query.filter_by(role="user", active=True).order_by(User.full_name).all()

    # Query all attendance records and holidays for this month
    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)

    all_attendance = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).all()

    all_holidays = Holiday.query.filter(
        Holiday.date >= start_date,
        Holiday.date <= end_date
    ).all()

    # Index attendance and holidays
    att_map = {(att.user_id, att.date.day): att for att in all_attendance}
    holiday_map = {h.date.day: h for h in all_holidays}

    # Build matrix rows for each employee
    matrix = []
    for idx, emp in enumerate(employees, start=1):
        emp_join_date = emp.joining_date or (emp.created_at.date() if emp.created_at else start_date)

        emp_row = {
            "s_no": idx,
            "user": emp,
            "days": {},
            "present_count": 0,
            "late_count": 0,
            "wfh_count": 0,
            "halfday_count": 0,
            "absent_count": 0,
            "weekend_count": 0,
            "holiday_count": 0,
            "percentage": 0.0
        }

        total_present_credits = 0.0
        emp_working_days = 0

        for d_info in days:
            day_num = d_info["day"]
            d_date = d_info["date"]
            att = att_map.get((emp.id, day_num))
            holiday = holiday_map.get(day_num)

            is_before_joining = d_date < emp_join_date
            is_company_halfday = holiday and holiday.day_type == "Half Day"

            if d_info["is_weekend"]:
                status = "OFF"
                check_in = ""
                check_out = ""
                emp_row["weekend_count"] += 1
            elif holiday and holiday.day_type == "Holiday":
                status = "Holiday"
                check_in = ""
                check_out = ""
                emp_row["holiday_count"] += 1
            elif is_before_joining:
                status = "--"
                check_in = ""
                check_out = ""
            elif att:
                emp_working_days += 1
                status = att.status
                check_in = att.check_in_ist()
                check_out = att.check_out_ist()

                if status in ("Present", "On Time"):
                    emp_row["present_count"] += 1
                    total_present_credits += 1.0
                elif status == "Late":
                    emp_row["late_count"] += 1
                    total_present_credits += 1.0
                elif status == "WFH":
                    emp_row["wfh_count"] += 1
                    total_present_credits += 1.0
                elif status in ("Half Day", "HD"):
                    emp_row["halfday_count"] += 1
                    # Company Half Day = 1.0 credit, Individual Half Day = 0.5 credit
                    if is_company_halfday:
                        total_present_credits += 1.0
                    else:
                        total_present_credits += 0.5
                elif status == "Absent":
                    emp_row["absent_count"] += 1
            else:
                if is_company_halfday:
                    status = "Half Day"
                    check_in = ""
                    check_out = ""
                    if d_date <= today:
                        emp_working_days += 1
                        emp_row["halfday_count"] += 1
                        total_present_credits += 1.0  # Company Half Day = 1.0 credit
                elif d_date <= today:
                    emp_working_days += 1
                    status = "Absent"
                    emp_row["absent_count"] += 1
                else:
                    status = "--"
                    check_in = ""
                    check_out = ""



            emp_row["days"][day_num] = {
                "status": status,
                "check_in": check_in,
                "check_out": check_out,
                "is_weekend": d_info["is_weekend"],
                "holiday_name": holiday.name if holiday else ""
            }

        if emp_working_days > 0:
            emp_row["percentage"] = round((total_present_credits / emp_working_days) * 100, 1)
        else:
            emp_row["percentage"] = 0.0

        matrix.append(emp_row)

    months_list = [(i, calendar.month_name[i]) for i in range(1, 13)]

    return render_template(
        "admin/attendance_sheet.html",
        matrix=matrix,
        days=days,
        year=year,
        month=month,
        month_name=calendar.month_name[month],
        months_list=months_list,
        working_days_count=working_days_count,
        today=today
    )


# ─── Company Calendar Management ─────────────────────────────────────────────

@admin_bp.route("/calendar")
@login_required
@admin_required
def calendar_view():
    import calendar as cal_mod
    from app.models.holiday import DAY_TYPES, DAY_TYPE_COLORS

    today = get_ist_today()
    try:
        year  = int(request.args.get("year",  today.year))
        month = int(request.args.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month

    # clamp
    if month < 1:  month = 12; year -= 1
    if month > 12: month = 1;  year += 1

    # Calendar grid: list of weeks, each week a list of date/None
    cal = cal_mod.Calendar(firstweekday=0)   # Mon=0
    month_weeks = cal.monthdatescalendar(year, month)

    # All tagged dates for this month + surrounding days shown in grid
    grid_dates = [d for week in month_weeks for d in week]
    start, end = grid_dates[0], grid_dates[-1]
    tagged = Holiday.query.filter(Holiday.date >= start, Holiday.date <= end).all()
    tagged_map = {h.date: h for h in tagged}

    # All tagged dates for this year (for the list below calendar)
    year_tagged = Holiday.query.filter(
        Holiday.date >= date(year, 1, 1),
        Holiday.date <= date(year, 12, 31)
    ).order_by(Holiday.date).all()

    prev_month = month - 1 or 12
    prev_year  = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year  = year + 1 if month == 12 else year

    return render_template(
        "admin/calendar.html",
        year=year, month=month,
        month_name=cal_mod.month_name[month],
        month_weeks=month_weeks,
        tagged_map=tagged_map,
        year_tagged=year_tagged,
        today=today,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
        day_types=DAY_TYPES,
        day_type_colors=DAY_TYPE_COLORS,
    )


@admin_bp.route("/calendar/save", methods=["POST"])
@login_required
@admin_required
def calendar_save():
    """Add or update a tagged date."""
    from app.models.holiday import DAY_TYPES
    date_str  = request.form.get("date", "").strip()
    name      = request.form.get("name", "").strip()
    day_type  = request.form.get("day_type", "Holiday").strip()
    desc      = request.form.get("description", "").strip()

    if not date_str or not name:
        return jsonify({"success": False, "message": "Date and name are required."}), 400
    if day_type not in DAY_TYPES:
        return jsonify({"success": False, "message": "Invalid day type."}), 400
    try:
        h_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"success": False, "message": "Invalid date."}), 400

    existing = Holiday.query.filter_by(date=h_date).first()
    if existing:
        existing.name        = name
        existing.day_type    = day_type
        existing.description = desc
    else:
        existing = Holiday(date=h_date, name=name, day_type=day_type, description=desc)
        db.session.add(existing)

    db.session.commit()
    from app.models.holiday import DAY_TYPE_COLORS, DAY_TYPE_EMOJIS
    return jsonify({
        "success": True,
        "message": f"{day_type} saved for {h_date.strftime('%d %b %Y')}.",
        "id":    existing.id,
        "date":  date_str,
        "name":  existing.name,
        "day_type": existing.day_type,
        "color": existing.display_color(),
        "emoji": existing.emoji(),
    })


@admin_bp.route("/calendar/delete/<int:holiday_id>", methods=["POST"])
@login_required
@admin_required
def calendar_delete(holiday_id):
    h = Holiday.query.get_or_404(holiday_id)
    db.session.delete(h)
    db.session.commit()
    return jsonify({"success": True, "message": "Entry removed from calendar."})


# Keep legacy /holidays route for backward compat → redirect to calendar
@admin_bp.route("/holidays")
@login_required
@admin_required
def holidays():
    return redirect(url_for("admin.calendar_view"))


# Employee read-only calendar view
@admin_bp.route("/calendar/data")
@login_required
def calendar_data():
    """JSON endpoint — returns tagged dates for a given year/month (used by employee calendar)."""
    import calendar as cal_mod
    today = get_ist_today()
    try:
        year  = int(request.args.get("year",  today.year))
        month = int(request.args.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month

    start = date(year, month, 1)
    end   = date(year, month, cal_mod.monthrange(year, month)[1])
    tagged = Holiday.query.filter(Holiday.date >= start, Holiday.date <= end).all()
    return jsonify([{
        "date":     h.date.strftime("%Y-%m-%d"),
        "name":     h.name,
        "day_type": h.day_type,
        "color":    h.display_color(),
        "emoji":    h.emoji(),
        "desc":     h.description or "",
    } for h in tagged])


# ─── Historical Attendance Import & Manual Entry ──────────────────────────────

@admin_bp.route("/attendance/import", methods=["GET", "POST"])
@login_required
@admin_required
def import_attendance():
    import csv
    import io
    from datetime import timedelta

    if request.method == "POST":
        action_type = request.form.get("action_type")

        # Option A: Manual Date Range Entry Form
        if action_type == "manual_range":
            user_id = request.form.get("user_id", type=int)
            start_date_str = request.form.get("start_date", "").strip()
            end_date_str = request.form.get("end_date", "").strip()
            status = request.form.get("status", "Present").strip()
            cin_str = request.form.get("check_in", "").strip()
            cout_str = request.form.get("check_out", "").strip()
            skip_weekends = request.form.get("skip_weekends") == "true"

            user = User.query.get_or_404(user_id)
            try:
                s_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                e_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            except ValueError:
                flash("Invalid date format for manual range entry.", "error")
                return redirect(url_for("admin.import_attendance"))

            if s_date > e_date:
                flash("Start date must be before or equal to end date.", "error")
                return redirect(url_for("admin.import_attendance"))

            curr = s_date
            count = 0
            while curr <= e_date:
                if skip_weekends and curr.weekday() in (5, 6):
                    curr += timedelta(days=1)
                    continue

                cin_dt = None
                cout_dt = None
                if cin_str:
                    try:
                        h, m = map(int, cin_str.split(":"))
                        cin_dt = datetime.combine(curr, datetime.min.time().replace(hour=h, minute=m))
                    except ValueError:
                        pass

                if cout_str:
                    try:
                        h, m = map(int, cout_str.split(":"))
                        cout_dt = datetime.combine(curr, datetime.min.time().replace(hour=h, minute=m))
                    except ValueError:
                        pass

                att = Attendance.query.filter_by(user_id=user.id, date=curr).first()
                if not att:
                    att = Attendance(user_id=user.id, date=curr, status=status, check_in=cin_dt, check_out=cout_dt)
                    db.session.add(att)
                else:
                    att.status = status
                    att.check_in = cin_dt
                    att.check_out = cout_dt

                count += 1
                curr += timedelta(days=1)

            db.session.commit()
            flash(f"Successfully recorded {count} historical attendance entries for {user.full_name}.", "success")
            return redirect(url_for("admin.import_attendance"))

        # Option B: Bulk CSV File Upload
        elif action_type == "csv_upload":
            file = request.files.get("csv_file")
            if not file or not file.filename.endswith(".csv"):
                flash("Please select a valid CSV file.", "error")
                return redirect(url_for("admin.import_attendance"))

            stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
            csv_reader = csv.DictReader(stream)

            # Map employee_id -> User object
            all_users = User.query.all()
            user_map = {u.employee_id.upper(): u for u in all_users}

            imported_count = 0
            error_rows = []

            for row_num, row in enumerate(csv_reader, start=2):
                emp_id = (row.get("employee_id") or row.get("Employee ID") or "").strip().upper()
                date_val = (row.get("date") or row.get("Date") or "").strip()
                status_val = (row.get("status") or row.get("Status") or "Present").strip()
                cin_val = (row.get("check_in") or row.get("Check In") or "").strip()
                cout_val = (row.get("check_out") or row.get("Check Out") or "").strip()

                if not emp_id or not date_val:
                    continue

                user = user_map.get(emp_id)
                if not user:
                    error_rows.append(f"Row {row_num}: Unknown Employee ID '{emp_id}'")
                    continue

                # Parse date
                rec_date = None
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
                    try:
                        rec_date = datetime.strptime(date_val, fmt).date()
                        break
                    except ValueError:
                        pass

                if not rec_date:
                    error_rows.append(f"Row {row_num}: Invalid date format '{date_val}'")
                    continue

                cin_dt = None
                cout_dt = None
                if cin_val and cin_val != "--":
                    for tfmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%H:%M:%S"):
                        try:
                            t_obj = datetime.strptime(cin_val, tfmt).time()
                            cin_dt = datetime.combine(rec_date, t_obj)
                            break
                        except ValueError:
                            pass

                if cout_val and cout_val != "--":
                    for tfmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%H:%M:%S"):
                        try:
                            t_obj = datetime.strptime(cout_val, tfmt).time()
                            cout_dt = datetime.combine(rec_date, t_obj)
                            break
                        except ValueError:
                            pass

                att = Attendance.query.filter_by(user_id=user.id, date=rec_date).first()
                if not att:
                    att = Attendance(user_id=user.id, date=rec_date, status=status_val, check_in=cin_dt, check_out=cout_dt)
                    db.session.add(att)
                else:
                    att.status = status_val
                    if cin_dt:
                        att.check_in = cin_dt
                    if cout_dt:
                        att.check_out = cout_dt

                imported_count += 1

            db.session.commit()

            if error_rows:
                flash(f"Imported {imported_count} records. Warnings: {'; '.join(error_rows[:5])}", "warning")
            else:
                flash(f"Successfully imported {imported_count} attendance records from CSV.", "success")

            return redirect(url_for("admin.import_attendance"))

    employees = User.query.filter_by(role="user", active=True).order_by(User.full_name).all()
    return render_template("admin/import_attendance.html", employees=employees)


@admin_bp.route("/attendance/download-template")
@login_required
@admin_required
def download_template():
    from flask import Response
    csv_content = "employee_id,date,status,check_in,check_out\n"
    csv_content += "EMP001,2026-07-01,Present,09:30,18:30\n"
    csv_content += "EMP001,2026-07-02,Present,09:25,18:35\n"
    csv_content += "EMP002,2026-07-01,Late,09:45,18:30\n"
    csv_content += "EMP002,2026-07-02,Half Day,09:30,13:30\n"

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=relay_attendance_template.csv"}
    )
