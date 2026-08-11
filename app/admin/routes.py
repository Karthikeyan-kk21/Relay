import calendar
import csv
from datetime import datetime, date, timedelta
from functools import wraps
import io
import json
import os
import pytz

from flask import (
    render_template, redirect, url_for, flash, request, jsonify, abort,
    Response, send_file, current_app
)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

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

    employees = User.query.filter_by(role="user", active=True).order_by(User.employee_id.asc()).all()



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
            1 for e in emp_data if e["user"].section != "Section 1" and e["worksheet"] and e["worksheet"].is_submitted()
        ),
        "worksheet_pending": sum(
            1 for e in emp_data if e["user"].section != "Section 1" and (not e["worksheet"] or not e["worksheet"].is_submitted())
        ),
    }


    # Calculate previous and next dates for navigation
    from datetime import timedelta
    prev_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)

    sec1_items = [e for e in emp_data if e["user"].section == "Section 1"]
    sec2_items = [e for e in emp_data if e["user"].section != "Section 1"]

    pending_ws_requests = Worksheet.query.filter_by(unlock_requested=True).order_by(Worksheet.unlock_requested_at.desc()).all()

    return render_template(
        "admin/dashboard.html",
        emp_data=emp_data,
        sec1_items=sec1_items,
        sec2_items=sec2_items,
        summary=summary,
        today=selected_date,
        prev_date_str=prev_date.strftime("%Y-%m-%d"),
        next_date_str=next_date.strftime("%Y-%m-%d"),
        selected_date_str=selected_date.strftime("%Y-%m-%d"),
        is_today=(selected_date == get_ist_today()),
        pending_ws_requests=pending_ws_requests
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


@admin_bp.route("/worksheet/approve-unlock/<int:ws_id>", methods=["POST"])
@login_required
@admin_required
def approve_worksheet_unlock(ws_id):
    ws = Worksheet.query.get_or_404(ws_id)
    ws.admin_unlocked = True
    ws.is_locked = False
    ws.unlock_requested = False
    db.session.commit()
    return jsonify({
        "success": True,
        "message": f"Worksheet unlocked for {ws.user.full_name} on {ws.date.strftime('%d %b %Y')}."
    })


@admin_bp.route("/worksheet/unlock-date", methods=["POST"])
@login_required
@admin_required
def unlock_worksheet_date():
    user_id = request.form.get("user_id")
    date_str = request.form.get("date")
    if not user_id or not date_str:
        return jsonify({"success": False, "message": "Missing required parameters."}), 400
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"success": False, "message": "Invalid date format."}), 400

    ws = Worksheet.query.filter_by(user_id=user_id, date=target_date).first()
    if not ws:
        ws = Worksheet(
            user_id=user_id,
            date=target_date,
            content="",
            is_locked=False,
            admin_unlocked=True,
            unlock_requested=False,
        )
        db.session.add(ws)
    else:
        ws.admin_unlocked = True
        ws.is_locked = False
        ws.unlock_requested = False

    db.session.commit()
    return jsonify({
        "success": True,
        "message": f"Worksheet unlocked for date {target_date.strftime('%d %b %Y')}."
    })



# ─── User Management ──────────────────────────────────────────────────────────

@admin_bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.filter_by(role="user").order_by(User.employee_id.asc()).all()

    sec1_users = [u for u in all_users if u.section == "Section 1"]
    sec2_users = [u for u in all_users if u.section != "Section 1"]
    return render_template("admin/users.html", users=all_users, sec1_users=sec1_users, sec2_users=sec2_users)



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

    section = request.form.get("section", "Section 2").strip()
    user = User(
        employee_id=employee_id,
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
        role="user",
        active=True,
        joining_date=joining_dt,
        section=section,
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
    section = request.form.get("section", "").strip()

    if full_name:
        user.full_name = full_name
    if email:
        user.email = email
    if section:
        user.section = section
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


@admin_bp.route("/users/delete/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    """Safely delete employee and their attendance/worksheet history."""
    if current_user.id == user_id:
        return jsonify({"success": False, "message": "You cannot delete your logged-in admin account."}), 400
    user = User.query.get_or_404(user_id)
    emp_name = user.full_name
    Attendance.query.filter_by(user_id=user.id).delete()
    Worksheet.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    return jsonify({"success": True, "message": f"Employee '{emp_name}' deleted successfully."})


@admin_bp.route("/backup/download")
@login_required
@admin_required
def download_backup():
    """Generate and download a complete database backup."""
    import os, io, json
    from flask import send_file, current_app

    today_str = get_ist_today().strftime("%Y%m%d_%H%M%S")
    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")

    if "sqlite" in db_uri:
        db_path = os.path.abspath(os.path.join(current_app.root_path, "..", "dev_relay.db"))
        if not os.path.exists(db_path):
            db_path = os.path.abspath(os.path.join(current_app.root_path, "..", "relay.db"))
        if os.path.exists(db_path):
            return send_file(
                db_path,
                as_attachment=True,
                download_name=f"Relay_DB_Backup_{today_str}.db",
                mimetype="application/x-sqlite3"
            )

    # General JSON backup snapshot for cloud or PostgreSQL
    backup_data = {
        "timestamp": today_str,
        "users": [{"id": u.id, "employee_id": u.employee_id, "name": u.full_name, "email": u.email, "role": u.role, "section": u.section, "active": u.active, "joining_date": str(u.joining_date)} for u in User.query.all()],
        "attendance": [{"id": a.id, "user_id": a.user_id, "date": str(a.date), "status": a.status, "check_in": str(a.check_in), "check_out": str(a.check_out), "ip_address": a.ip_address} for a in Attendance.query.all()],
        "worksheets": [{"id": w.id, "user_id": w.user_id, "date": str(w.date), "content": w.content, "is_locked": w.is_locked} for w in Worksheet.query.all()],
        "holidays": [{"id": h.id, "date": str(h.date), "name": h.name, "day_type": h.day_type} for h in Holiday.query.all()]
    }

    mem = io.BytesIO(json.dumps(backup_data, indent=2).encode('utf-8'))
    return send_file(
        mem,
        as_attachment=True,
        download_name=f"Relay_DB_Backup_{today_str}.json",
        mimetype="application/json"
    )



# ─── Settings ─────────────────────────────────────────────────────────────────

@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    from app.models.setting import DEFAULT_SETTINGS

    if request.method == "POST":
        keys = ["office_ip", "checkin_time", "late_threshold", "worksheet_lock_time", "last_entry_time", "disable_timing_lock", "weekend_policy", "sat_checkin_time", "sat_last_entry_time", "sat_checkout_time", "maintenance_mode"]
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
    employees = User.query.filter_by(role="user", active=True).order_by(User.employee_id.asc()).all()


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

            check_in = ""
            check_out = ""

            if d_info["is_weekend"]:
                status = "OFF"
                emp_row["weekend_count"] += 1
            elif holiday and holiday.day_type == "Holiday":
                status = "Holiday"
                emp_row["holiday_count"] += 1
            elif is_before_joining:
                status = "--"
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

    sec1_matrix = [r for r in matrix if r["user"].section == "Section 1"]
    sec2_matrix = [r for r in matrix if r["user"].section != "Section 1"]

    months_list = [(i, calendar.month_name[i]) for i in range(1, 13)]

    return render_template(
        "admin/attendance_sheet.html",
        matrix=matrix,
        sec1_matrix=sec1_matrix,
        sec2_matrix=sec2_matrix,
        days=days,
        year=year,
        month=month,
        month_name=calendar.month_name[month],
        months_list=months_list,
        working_days_count=working_days_count,
        today=today
    )



# ─── Monthly Data Exports ───────────────────────────────────────────────────

@admin_bp.route("/sheet/export-csv")
@login_required
@admin_required
def export_sheet_csv():
    """Export complete monthly attendance matrix to CSV."""
    import calendar
    from flask import Response
    import io, csv

    today = get_ist_today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month

    num_days = calendar.monthrange(year, month)[1]
    weekend_policy = Setting.get("weekend_policy", "sunday_only")
    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)

    employees = User.query.filter_by(role="user", active=True).order_by(User.full_name).all()
    all_attendance = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date).all()
    all_holidays = Holiday.query.filter(Holiday.date >= start_date, Holiday.date <= end_date).all()

    att_map = {(att.user_id, att.date.day): att for att in all_attendance}
    holiday_map = {h.date.day: h for h in all_holidays}

    output = io.StringIO()
    writer = csv.writer(output)

    # Header Row
    headers = ["S.No", "Employee ID", "Employee Name", "Joining Date"]
    for day_num in range(1, num_days + 1):
        d = date(year, month, day_num)
        headers.append(f"{d.strftime('%a %d')} Status")
        headers.append(f"{d.strftime('%a %d')} In")
        headers.append(f"{d.strftime('%a %d')} Out")

    headers.extend(["Present Days", "Late Days", "WFH Days", "Half Days", "Absent Days", "Attendance %"])
    writer.writerow(headers)

    for idx, emp in enumerate(employees, start=1):
        row = [idx, emp.employee_id, emp.full_name, emp.joining_date.strftime("%Y-%m-%d") if emp.joining_date else ""]
        emp_working_days = 0
        credits = 0.0
        p_cnt, l_cnt, w_cnt, h_cnt, a_cnt = 0, 0, 0, 0, 0

        for day_num in range(1, num_days + 1):
            d = date(year, month, day_num)
            is_sunday = d.weekday() == 6
            is_saturday = d.weekday() == 5
            is_weekend = is_sunday or (is_saturday and weekend_policy == "sat_sun")
            att = att_map.get((emp.id, day_num))
            h_entry = holiday_map.get(day_num)

            status, cin, cout = "", "", ""
            if is_weekend:
                status = "OFF"
            elif h_entry and h_entry.day_type == "Holiday":
                status = "Holiday"
            elif att:
                status = att.status
                cin = att.check_in_ist()
                cout = att.check_out_ist()
                emp_working_days += 1
                if status in ("Present", "On Time"):
                    p_cnt += 1; credits += 1.0
                elif status == "Late":
                    l_cnt += 1; credits += 1.0
                elif status == "WFH":
                    w_cnt += 1; credits += 1.0
                elif status in ("Half Day", "HD"):
                    h_cnt += 1
                    credits += 1.0 if (h_entry and h_entry.day_type == "Half Day") else 0.5
                elif status == "Absent":
                    a_cnt += 1
            else:
                if h_entry and h_entry.day_type == "Half Day":
                    status = "Half Day"
                    if d <= today:
                        emp_working_days += 1; h_cnt += 1; credits += 1.0
                elif d <= today:
                    status = "Absent"
                    emp_working_days += 1; a_cnt += 1
                else:
                    status = "--"

            row.extend([status, cin, cout])

        pct = round((credits / emp_working_days * 100), 1) if emp_working_days > 0 else 0.0
        row.extend([p_cnt, l_cnt, w_cnt, h_cnt, a_cnt, f"{pct}%"])
        writer.writerow(row)

    month_name = calendar.month_name[month]
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=Relay_Attendance_Sheet_{month_name}_{year}.csv"}
    )


@admin_bp.route("/sheet/export-worksheets")
@login_required
@admin_required
def export_worksheets_csv():
    """Export daily worksheets for selected month to CSV."""
    import calendar
    from flask import Response
    import io, csv

    today = get_ist_today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month

    num_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)

    worksheets = (
        Worksheet.query.filter(Worksheet.date >= start_date, Worksheet.date <= end_date)
        .order_by(Worksheet.date.desc(), Worksheet.user_id)
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Employee ID", "Employee Name", "Check-In", "Check-Out", "Status", "Worksheet Content"])

    for ws in worksheets:
        user = ws.user
        if not user or not user.active:
            continue
        att = Attendance.query.filter_by(user_id=user.id, date=ws.date).first()
        cin = att.check_in_ist() if att else ""
        cout = att.check_out_ist() if att else ""
        st = att.status if att else ""
        writer.writerow([
            ws.date.strftime("%Y-%m-%d"),
            user.employee_id,
            user.full_name,
            cin,
            cout,
            st,
            ws.content.replace("\r", "") if ws.content else ""
        ])

    month_name = calendar.month_name[month]
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=Relay_Worksheets_{month_name}_{year}.csv"}
    )


# ─── Individual Employee 360 Full History & Reports ──────────────────────────

@admin_bp.route("/users/<int:user_id>/history")
@login_required
@admin_required
def user_history(user_id):
    """360 View & Full Career History Report for an individual employee."""
    user = User.query.get_or_404(user_id)
    today = get_ist_today()

    start_date_str = request.args.get("start_date", "").strip()
    end_date_str = request.args.get("end_date", "").strip()

    default_start = user.joining_date or (user.created_at.date() if user.created_at else today)

    try:
        s_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else default_start
    except ValueError:
        s_date = default_start

    try:
        e_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else today
    except ValueError:
        e_date = today

    # Query all attendance records for user in range
    records = (
        Attendance.query.filter(
            Attendance.user_id == user.id,
            Attendance.date >= s_date,
            Attendance.date <= e_date
        )
        .order_by(Attendance.date.desc())
        .all()
    )

    # Query worksheets map
    worksheets = (
        Worksheet.query.filter(
            Worksheet.user_id == user.id,
            Worksheet.date >= s_date,
            Worksheet.date <= e_date
        ).all()
    )
    ws_map = {ws.date: ws for ws in worksheets}

    # Query Holidays map
    holidays = Holiday.query.filter(Holiday.date >= s_date, Holiday.date <= e_date).all()
    h_map = {h.date: h for h in holidays}

    total_days = len(records)
    present_cnt = sum(1 for r in records if r.status in ("Present", "On Time"))
    late_cnt    = sum(1 for r in records if r.status == "Late")
    wfh_cnt     = sum(1 for r in records if r.status == "WFH")
    hd_cnt      = sum(1 for r in records if r.status in ("HD", "Half Day"))
    absent_cnt  = sum(1 for r in records if r.status == "Absent")

    credits = present_cnt + late_cnt + wfh_cnt + (hd_cnt * 0.5)
    working_days = present_cnt + late_cnt + wfh_cnt + hd_cnt + absent_cnt
    pct = round((credits / working_days * 100), 1) if working_days > 0 else 0.0

    history_logs = []
    for r in records:
        ws = ws_map.get(r.date)
        h_entry = h_map.get(r.date)
        history_logs.append({
            "attendance": r,
            "worksheet": ws,
            "holiday": h_entry,
            "date": r.date,
            "status": r.status,
            "check_in": r.check_in_ist(),
            "check_out": r.check_out_ist(),
            "ip_address": r.ip_address or "--",
            "content": ws.content if ws else ""
        })

    return render_template(
        "admin/user_history.html",
        user=user,
        s_date=s_date,
        e_date=e_date,
        total_days=total_days,
        present_cnt=present_cnt,
        late_cnt=late_cnt,
        wfh_cnt=wfh_cnt,
        hd_cnt=hd_cnt,
        absent_cnt=absent_cnt,
        pct=pct,
        logs=history_logs,
        today=today
    )


@admin_bp.route("/users/<int:user_id>/export-csv")
@login_required
@admin_required
def export_user_csv(user_id):
    """Export individual employee history to CSV."""
    from flask import Response
    import io, csv

    user = User.query.get_or_404(user_id)
    today = get_ist_today()
    default_start = user.joining_date or today

    s_str = request.args.get("start_date", "").strip()
    e_str = request.args.get("end_date", "").strip()

    try: s_date = datetime.strptime(s_str, "%Y-%m-%d").date() if s_str else default_start
    except ValueError: s_date = default_start

    try: e_date = datetime.strptime(e_str, "%Y-%m-%d").date() if e_str else today
    except ValueError: e_date = today

    records = (
        Attendance.query.filter(Attendance.user_id == user.id, Attendance.date >= s_date, Attendance.date <= e_date)
        .order_by(Attendance.date.desc())
        .all()
    )
    ws_map = {ws.date: ws for ws in Worksheet.query.filter(Worksheet.user_id == user.id, Worksheet.date >= s_date, Worksheet.date <= e_date).all()}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f"Employee Report for {user.full_name} ({user.employee_id})"])
    writer.writerow([f"Joining Date: {user.joining_date}", f"Period: {s_date} to {e_date}"])
    writer.writerow([])
    writer.writerow(["Date", "Day", "Status", "Check-In", "Check-Out", "IP Address", "Worksheet Log"])

    for r in records:
        ws = ws_map.get(r.date)
        writer.writerow([
            r.date.strftime("%Y-%m-%d"),
            r.date.strftime("%a"),
            r.status,
            r.check_in_ist(),
            r.check_out_ist(),
            r.ip_address or "",
            ws.content.replace("\r", "") if ws and ws.content else ""
        ])

    filename = f"Relay_Report_{user.employee_id}_{s_date.strftime('%Y%m%d')}_to_{e_date.strftime('%Y%m%d')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )


@admin_bp.route("/users/<int:user_id>/export-pdf")
@login_required
@admin_required
def export_user_pdf(user_id):
    """Export individual employee history report to PDF using ReportLab."""
    from flask import Response
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.units import cm

    user = User.query.get_or_404(user_id)
    today = get_ist_today()
    default_start = user.joining_date or today

    s_str = request.args.get("start_date", "").strip()
    e_str = request.args.get("end_date", "").strip()

    try: s_date = datetime.strptime(s_str, "%Y-%m-%d").date() if s_str else default_start
    except ValueError: s_date = default_start

    try: e_date = datetime.strptime(e_str, "%Y-%m-%d").date() if e_str else today
    except ValueError: e_date = today

    records = (
        Attendance.query.filter(Attendance.user_id == user.id, Attendance.date >= s_date, Attendance.date <= e_date)
        .order_by(Attendance.date.desc())
        .all()
    )
    ws_map = {ws.date: ws for ws in Worksheet.query.filter(Worksheet.user_id == user.id, Worksheet.date >= s_date, Worksheet.date <= e_date).all()}

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#1e293b"), spaceAfter=6)
    sub_style = ParagraphStyle("sub", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#64748b"), spaceAfter=14)
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#334155"))

    story = []
    story.append(Paragraph(f"Relay Employee Report — {user.full_name}", title_style))
    story.append(Paragraph(f"Employee ID: {user.employee_id} | Email: {user.email} | Joining Date: {user.joining_date} | Period: {s_date.strftime('%d %b %Y')} to {e_date.strftime('%d %b %Y')}", sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cbd5e1"), spaceAfter=12))

    # Summary Table
    p_cnt = sum(1 for r in records if r.status in ("Present", "On Time"))
    l_cnt = sum(1 for r in records if r.status == "Late")
    w_cnt = sum(1 for r in records if r.status == "WFH")
    h_cnt = sum(1 for r in records if r.status in ("HD", "Half Day"))
    a_cnt = sum(1 for r in records if r.status == "Absent")
    w_days = p_cnt + l_cnt + w_cnt + h_cnt + a_cnt
    pct = round(((p_cnt + l_cnt + w_cnt + h_cnt * 0.5) / w_days * 100), 1) if w_days > 0 else 0.0

    summary_data = [
        ["Total Days", "Present", "Late", "WFH", "Half Day", "Absent", "Attendance %"],
        [str(len(records)), str(p_cnt), str(l_cnt), str(w_cnt), str(h_cnt), str(a_cnt), f"{pct}%"]
    ]
    t_summary = Table(summary_data, colWidths=[2.5*cm]*7)
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#1e293b")),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 0.5*cm))

    # Log Table
    table_data = [["Date", "Status", "Check-In", "Check-Out", "Worksheet Content"]]
    for r in records[:50]: # limit to top 50 rows for clean PDF size
        ws = ws_map.get(r.date)
        ws_text = (ws.content.replace('\n', ' ')[:100] + '...') if (ws and ws.content) else "--"
        table_data.append([
            r.date.strftime("%d/%m/%Y"),
            r.status,
            r.check_in_ist() or "--",
            r.check_out_ist() or "--",
            Paragraph(ws_text.replace('&', '&amp;').replace('<', '&lt;'), cell_style)
        ])

    t_logs = Table(table_data, colWidths=[2.5*cm, 2.0*cm, 2.2*cm, 2.2*cm, 9.1*cm])
    t_logs.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e293b")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
    ]))
    story.append(t_logs)

    doc.build(story)
    pdf_buffer.seek(0)

    filename = f"Relay_Report_{user.employee_id}_{s_date.strftime('%Y%m%d')}.pdf"
    return Response(
        pdf_buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-disposition": f"attachment; filename={filename}"}
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
