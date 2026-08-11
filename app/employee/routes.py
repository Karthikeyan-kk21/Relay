from flask import render_template, redirect, url_for, jsonify, request
from flask_login import login_required, current_user
import pytz
from datetime import datetime

from app.employee import employee_bp
from app.extensions import db
from app.models import Attendance, Worksheet, Setting, Holiday

IST = pytz.timezone("Asia/Kolkata")


def get_ist_now():
    """Return current datetime in IST (naive, suitable for DB storage)."""
    return datetime.now(IST).replace(tzinfo=None)


def get_ist_today():
    """Return today's date in IST."""
    return datetime.now(IST).date()


def parse_time_parts(time_str, default_h=11, default_m=0):
    """Safely parse HH:MM string without throwing ValueError."""
    if not time_str or ":" not in str(time_str):
        return default_h, default_m
    try:
        parts = str(time_str).strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return default_h, default_m


def is_worksheet_locked(worksheet):
    """Return True if worksheet is locked and not admin-unlocked."""
    if Setting.get("disable_timing_lock", "false") == "true":
        return False
    if worksheet and worksheet.admin_unlocked:
        return False
    now = get_ist_now()
    weekend_policy = Setting.get("weekend_policy", "sunday_only")
    is_saturday = now.weekday() == 5
    if is_saturday and weekend_policy == "sat_half_sun_off":
        lock_time_str = Setting.get("sat_checkout_time", "13:00")
        lock_h, lock_m = parse_time_parts(lock_time_str, 13, 0)
    else:
        lock_time_str = Setting.get("worksheet_lock_time", "18:30")
        lock_h, lock_m = parse_time_parts(lock_time_str, 18, 30)

    time_passed = now.hour > lock_h or (now.hour == lock_h and now.minute >= lock_m)
    if time_passed:
        # Persist lock in DB if worksheet exists
        if worksheet and not worksheet.is_locked:
            worksheet.is_locked = True
            db.session.commit()
        return True
    return False


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# ─── Employee Dashboard ───────────────────────────────────────────────────────

@employee_bp.route("/dashboard")
@login_required
def dashboard():
    today = get_ist_today()
    attendance = Attendance.query.filter_by(user_id=current_user.id, date=today).first()
    worksheet = Worksheet.query.filter_by(user_id=current_user.id, date=today).first()
    today_holiday = Holiday.query.filter_by(date=today).first()
    locked = is_worksheet_locked(worksheet)
    
    weekend_policy = Setting.get("weekend_policy", "sunday_only")
    is_saturday = today.weekday() == 5
    if is_saturday and weekend_policy == "sat_half_sun_off":
        lock_time = Setting.get("sat_checkout_time", "13:00")
        last_entry_time = Setting.get("sat_last_entry_time", "10:30")
    else:
        lock_time = Setting.get("worksheet_lock_time", "18:30")
        last_entry_time = Setting.get("last_entry_time", "11:00")

    # Check-in cut-off validation
    is_checkin_locked = False
    if Setting.get("disable_timing_lock", "false") != "true" and (not attendance or not attendance.check_in):
        now = get_ist_now()
        last_h, last_m = parse_time_parts(last_entry_time, 11, 0)
        is_past_cut_off = now.hour > last_h or (now.hour == last_h and now.minute >= last_m)
        if is_past_cut_off:
            is_checkin_locked = not (attendance and attendance.admin_unlocked)



    return render_template(
        "employee/dashboard.html",
        attendance=attendance,
        worksheet=worksheet,
        is_locked=locked,
        today=today,
        lock_time=lock_time,
        now=get_ist_now(),
        is_checkin_locked=is_checkin_locked,
        last_entry_time=last_entry_time,
        today_holiday=today_holiday,
    )


# ─── Check In ─────────────────────────────────────────────────────────────────

@employee_bp.route("/checkin", methods=["POST"])
@login_required
def checkin():
    # IP Validation — skipped if it's a WFH day
    office_ip = Setting.get("office_ip", "").strip()
    if office_ip:
        today_for_ip = get_ist_today()

        # Bypass 1: Company calendar has today tagged as WFH
        calendar_day = Holiday.query.filter_by(date=today_for_ip).first()
        is_wfh_calendar = calendar_day and calendar_day.day_type == "WFH"

        # Bypass 2: Admin has already marked this employee as WFH today
        existing_att = Attendance.query.filter_by(
            user_id=current_user.id, date=today_for_ip
        ).first()
        is_wfh_admin = existing_att and existing_att.status == "WFH"

        if not is_wfh_calendar and not is_wfh_admin:
            client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
            if client_ip:
                client_ip = client_ip.split(",")[0].strip()
            
            allowed_ips = [ip.strip() for ip in office_ip.split(",") if ip.strip()]
            ip_match = any(
                client_ip == allowed or (allowed.endswith(".") and client_ip.startswith(allowed))
                for allowed in allowed_ips
            )

            if not ip_match:
                return jsonify({
                    "success": False,
                    "message": f"Check-in is only allowed from the office network. Your IP: {client_ip}"
                }), 403


    today = get_ist_today()
    existing = Attendance.query.filter_by(user_id=current_user.id, date=today).first()

    if existing and existing.check_in:
        return jsonify({"success": False, "message": "You have already checked in today."}), 400

    now = get_ist_now()

    weekend_policy = Setting.get("weekend_policy", "sunday_only")
    is_saturday = today.weekday() == 5

    # Check-in cut-off validation
    if Setting.get("disable_timing_lock", "false") != "true":
        if is_saturday and weekend_policy == "sat_half_sun_off":
            last_entry_time = Setting.get("sat_last_entry_time", "10:30")
        else:
            last_entry_time = Setting.get("last_entry_time", "11:00")

        last_h, last_m = parse_time_parts(last_entry_time, 11, 0)
        is_past_cut_off = now.hour > last_h or (now.hour == last_h and now.minute >= last_m)
        if is_past_cut_off:
            is_unlocked = existing and existing.admin_unlocked
            if not is_unlocked:
                return jsonify({
                    "success": False,
                    "message": f"Check-in is disabled after {last_entry_time}. Please contact your administrator."
                }), 403

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()

    # Determine attendance status
    # If today is a WFH day (calendar or admin-marked), keep WFH status
    today_cal = Holiday.query.filter_by(date=today).first()
    is_wfh_day = (today_cal and today_cal.day_type == "WFH") or \
                 (existing and existing.status == "WFH")

    if is_wfh_day:
        status = "WFH"
    else:
        if is_saturday and weekend_policy == "sat_half_sun_off":
            checkin_deadline = Setting.get("sat_checkin_time", "10:00")
        else:
            checkin_deadline = Setting.get("checkin_time", "09:30")

        ch, cm = parse_time_parts(checkin_deadline, 9, 30)
        on_time_limit = now.replace(hour=ch, minute=cm, second=0, microsecond=0)
        status = "Present" if now <= on_time_limit else "Late"


    if existing:
        existing.check_in = now
        existing.status = status
        existing.ip_address = client_ip
    else:
        record = Attendance(
            user_id=current_user.id,
            date=today,
            check_in=now,
            status=status,
            ip_address=client_ip,
        )
        db.session.add(record)

    db.session.commit()
    return jsonify({
        "success": True,
        "message": f"Checked in at {now.strftime('%H:%M')}",
        "status": status,
        "checkin_time": now.strftime("%H:%M"),
    })


# ─── Check Out ────────────────────────────────────────────────────────────────

@employee_bp.route("/checkout", methods=["POST"])
@login_required
def checkout():
    # IP Validation — skipped if it's a WFH day
    office_ip = Setting.get("office_ip", "").strip()
    if office_ip:
        today_for_ip = get_ist_today()
        calendar_day = Holiday.query.filter_by(date=today_for_ip).first()
        is_wfh_calendar = calendar_day and calendar_day.day_type == "WFH"
        existing_att = Attendance.query.filter_by(
            user_id=current_user.id, date=today_for_ip
        ).first()
        is_wfh_admin = existing_att and existing_att.status == "WFH"

        if not is_wfh_calendar and not is_wfh_admin:
            client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
            if client_ip:
                client_ip = client_ip.split(",")[0].strip()

            allowed_ips = [ip.strip() for ip in office_ip.split(",") if ip.strip()]
            ip_match = any(
                client_ip == allowed or (allowed.endswith(".") and client_ip.startswith(allowed))
                for allowed in allowed_ips
            )

            if not ip_match:
                return jsonify({
                    "success": False,
                    "message": f"Check-out is only allowed from the office network. Your IP: {client_ip}"
                }), 403


    today = get_ist_today()
    attendance = Attendance.query.filter_by(user_id=current_user.id, date=today).first()

    if not attendance or not attendance.check_in:
        return jsonify({"success": False, "message": "You haven't checked in today."}), 400

    if attendance.check_out:
        return jsonify({"success": False, "message": "You have already checked out."}), 400

    now = get_ist_now()
    attendance.check_out = now

    db.session.commit()
    return jsonify({
        "success": True,
        "message": f"Checked out at {now.strftime('%H:%M')}",
        "checkout_time": now.strftime("%H:%M"),
        "status": attendance.status,
    })


# ─── Worksheet ────────────────────────────────────────────────────────────────

# ─── Worksheet ────────────────────────────────────────────────────────────────

@employee_bp.route("/worksheet/fetch", methods=["GET"])
@login_required
def fetch_worksheet():
    date_str = request.args.get("date", "").strip()
    today = get_ist_today()
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = today
    else:
        target_date = today

    ws = Worksheet.query.filter_by(user_id=current_user.id, date=target_date).first()
    
    if target_date == today:
        locked = is_worksheet_locked(ws)
    else:
        # Past dates are locked unless admin_unlocked is True
        locked = True if not (ws and ws.admin_unlocked) else False

    return jsonify({
        "success": True,
        "date": target_date.strftime("%Y-%m-%d"),
        "content": ws.content if ws else "",
        "is_locked": locked,
        "admin_unlocked": bool(ws and ws.admin_unlocked),
        "unlock_requested": bool(ws and ws.unlock_requested),
    })


@employee_bp.route("/worksheet/request-unlock", methods=["POST"])
@login_required
def request_worksheet_unlock():
    date_str = request.form.get("date", "").strip()
    today = get_ist_today()
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = today
    else:
        target_date = today

    ws = Worksheet.query.filter_by(user_id=current_user.id, date=target_date).first()
    now = get_ist_now()

    if not ws:
        ws = Worksheet(
            user_id=current_user.id,
            date=target_date,
            content="",
            is_locked=True,
            unlock_requested=True,
            unlock_requested_at=now,
        )
        db.session.add(ws)
    else:
        ws.unlock_requested = True
        ws.unlock_requested_at = now

    db.session.commit()
    return jsonify({
        "success": True,
        "message": f"Unlock request sent to Admin for {target_date.strftime('%d %b %Y')}."
    })


@employee_bp.route("/worksheet", methods=["POST"])
@login_required
def save_worksheet():
    date_str = request.form.get("date", "").strip()
    today = get_ist_today()
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = today
    else:
        target_date = today

    ws = Worksheet.query.filter_by(user_id=current_user.id, date=target_date).first()

    if target_date == today:
        locked = is_worksheet_locked(ws)
    else:
        locked = True if not (ws and ws.admin_unlocked) else False

    if locked:
        return jsonify({"success": False, "message": "Worksheet is locked for this date. Request Admin unlock to edit."}), 403

    content = request.form.get("content", "").strip()
    now = get_ist_now()

    if ws:
        ws.content = content
        ws.updated_at = now
        if not ws.submitted_at:
            ws.submitted_at = now
    else:
        ws = Worksheet(
            user_id=current_user.id,
            date=target_date,
            content=content,
            submitted_at=now,
            updated_at=now,
        )
        db.session.add(ws)

    db.session.commit()
    return jsonify({"success": True, "message": f"Worksheet for {target_date.strftime('%d %b %Y')} saved successfully."})



# ─── Attendance History ───────────────────────────────────────────────────────

@employee_bp.route("/history")
@login_required
def history():
    from datetime import date
    today = get_ist_today()
    month_start = date(today.year, today.month, 1)

    records = (
        Attendance.query.filter_by(user_id=current_user.id)
        .filter(Attendance.date >= month_start, Attendance.date <= today)
        .order_by(Attendance.date.desc())
        .all()
    )

    total   = len(records)
    present = sum(1 for r in records if r.status in ("Present", "On Time"))
    late    = sum(1 for r in records if r.status == "Late")
    absent  = sum(1 for r in records if r.status == "Absent")
    wfh     = sum(1 for r in records if r.status == "WFH")
    hd      = sum(1 for r in records if r.status in ("HD", "Half Day"))

    return render_template(
        "employee/history.html",
        records=records,
        total=total,
        present=present,
        late=late,
        absent=absent,
        wfh=wfh,
        hd=hd,
        month_label=today.strftime("%B %Y"),
    )



# ─── Employee Read-Only Company Calendar ─────────────────────────────────────

@employee_bp.route("/calendar")
@login_required
def calendar():
    import calendar as cal_mod
    from app.models.holiday import DAY_TYPE_COLORS

    today = get_ist_today()
    try:
        year  = int(request.args.get("year",  today.year))
        month = int(request.args.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month

    # clamp
    if month < 1:  month = 12; year -= 1
    if month > 12: month = 1;  year += 1

    cal = cal_mod.Calendar(firstweekday=0)
    month_weeks = cal.monthdatescalendar(year, month)

    grid_dates = [d for week in month_weeks for d in week]
    start, end = grid_dates[0], grid_dates[-1]
    tagged = Holiday.query.filter(Holiday.date >= start, Holiday.date <= end).all()
    tagged_map = {h.date: h for h in tagged}

    # Upcoming events — next 60 days from today
    from datetime import timedelta
    from app.models import Holiday as H
    upcoming = H.query.filter(H.date >= today).order_by(H.date).limit(5).all()

    prev_month = month - 1 or 12
    prev_year  = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year  = year + 1 if month == 12 else year

    return render_template(
        "employee/calendar.html",
        year=year, month=month,
        month_name=cal_mod.month_name[month],
        month_weeks=month_weeks,
        tagged_map=tagged_map,
        today=today,
        upcoming=upcoming,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
        day_type_colors=DAY_TYPE_COLORS,
    )
