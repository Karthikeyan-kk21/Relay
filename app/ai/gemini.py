"""
Gemini AI integration for generating CEO daily reports.
"""

from flask import current_app
from app.models import Attendance, Worksheet, User
import pytz
from datetime import datetime

IST = pytz.timezone("Asia/Kolkata")


def generate_ceo_report(report_date):
    """
    Generate a formatted CEO daily report for the given date.
    Returns a dict: { success, report, raw_data }
    """
    # Gather all active employees
    employees = User.query.filter_by(role="user", active=True).all()

    if not employees:
        return {"success": False, "message": "No active employees found."}

    # Collect attendance and worksheet data
    attendance_records = {}
    worksheet_records = {}

    present_names = []
    late_names = []
    halfday_names = []
    absent_names = []
    wfh_names = []

    for emp in employees:
        att = Attendance.query.filter_by(user_id=emp.id, date=report_date).first()
        ws = Worksheet.query.filter_by(user_id=emp.id, date=report_date).first()
        attendance_records[emp.id] = att
        worksheet_records[emp.id] = ws

        st = att.status if att else "Absent"
        if st in ("Present", "On Time"):
            present_names.append(emp.full_name)
        elif st == "Late":
            late_names.append(emp.full_name)
        elif st in ("Half Day", "HD"):
            halfday_names.append(emp.full_name)
        elif st == "WFH":
            wfh_names.append(emp.full_name)
        else:
            absent_names.append(emp.full_name)

    # Build worksheet data for Gemini
    worksheet_data = []
    for emp in employees:
        ws = worksheet_records[emp.id]
        if ws and ws.is_submitted():
            worksheet_data.append({
                "name": emp.full_name,
                "content": ws.content.strip(),
            })

    # Check Gemini API key
    gemini_key = current_app.config.get("GEMINI_API_KEY", "").strip()

    if not gemini_key or gemini_key == "your_gemini_api_key_here":
        # Generate report without AI (manual format)
        report = _build_manual_report(
            report_date, employees, worksheet_records,
            present_names, late_names, absent_names, wfh_names, halfday_names
        )
        return {
            "success": True,
            "report": report,
            "ai_used": False,
            "message": "Report generated without AI (Gemini API key not configured).",
        }

    # Use Gemini to summarize worksheet content
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)

        work_entries = "\n\n".join([
            f"{i+1}. {d['name']}:\n{d['content']}"
            for i, d in enumerate(worksheet_data)
        ])

        prompt = f"""Summarize the following daily work logs into a clean, executive summary for a CEO.

CRITICAL INSTRUCTIONS:
- Output ONLY the final summary list.
- Do NOT include any introduction, conclusion, role descriptions, constraint checks, draft steps, or reasoning thoughts.
- Start directly with item "1. ".

Employee Work Logs:
{work_entries}

Required Output Format:
1. [Employee Name]
   • [Work item 1]
   • [Work item 2]

2. [Employee Name]
   • [Work item 1]

Preserve names exactly as given. Make bullet points professional, clear, and concise."""

        candidate_models = [
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-flash-latest",
            "models/gemini-1.5-flash",
        ]

        response = None
        last_err = None


        for model_name in candidate_models:
            try:
                model = genai.GenerativeModel(model_name)
                res = model.generate_content(prompt)
                if res and res.text:
                    response = res
                    break
            except Exception as ex:
                last_err = ex
                continue

        if not response or not response.text:
            raise last_err or Exception("All available Gemini models failed to generate content.")

        ai_summary = response.text.strip()

        # Clean out any accidental internal reasoning or preamble
        import re
        match = re.search(r'(?:^|\n)(1\.\s+.*)', ai_summary, re.DOTALL)
        if match:
            ai_summary = match.group(1).strip()

        report = _build_ai_report(
            report_date, present_names, late_names, absent_names, wfh_names, halfday_names,
            ai_summary, len(employees)
        )
        return {"success": True, "report": report, "ai_used": True}

    except Exception as e:
        # Fallback to manual report on error
        report = _build_manual_report(
            report_date, employees, worksheet_records,
            present_names, late_names, absent_names, wfh_names, halfday_names
        )
        return {
            "success": True,
            "report": report,
            "ai_used": False,
            "message": f"AI failed ({str(e)}). Generated without AI.",
        }


def _format_status_line(label, names):
    count = len(names)
    if names:
        return f"  {label:<9}: {count} ({', '.join(names)})"
    return f"  {label:<9}: 0"


def _build_ai_report(report_date, present_names, late_names, absent_names, wfh_names, halfday_names, ai_summary, total):
    date_str = report_date.strftime("%d/%m/%Y")
    lines = [
        f"Daily Report — {date_str}",
        "=" * 40,
        "",
        "ATTENDANCE",
        "-" * 20,
        _format_status_line("Present", present_names),
        _format_status_line("Late", late_names),
        _format_status_line("Half Day", halfday_names),
        _format_status_line("Absent", absent_names),
        _format_status_line("WFH", wfh_names),
        f"  Total    : {total}",
        "",
        "WORK SUMMARY",
        "-" * 20,
        "",
        ai_summary,
        "",
        "=" * 40,
    ]
    return "\n".join(lines)


def _build_manual_report(report_date, employees, worksheet_records,
                         present_names, late_names, absent_names, wfh_names, halfday_names):
    date_str = report_date.strftime("%d/%m/%Y")
    lines = [
        f"Daily Report — {date_str}",
        "=" * 40,
        "",
        "ATTENDANCE",
        "-" * 20,
        _format_status_line("Present", present_names),
        _format_status_line("Late", late_names),
        _format_status_line("Half Day", halfday_names),
        _format_status_line("Absent", absent_names),
        _format_status_line("WFH", wfh_names),
        f"  Total    : {len(employees)}",
        "",
        "WORK SUMMARY",
        "-" * 20,
        "",
    ]
    for i, emp in enumerate(employees, 1):
        ws = worksheet_records[emp.id]
        lines.append(f"{i}. {emp.full_name}")
        if ws and ws.is_submitted():
            for part in ws.content.strip().split("\n"):
                if part.strip():
                    lines.append(f"   • {part.strip()}")
        else:
            lines.append("   • (No worksheet submitted)")
        lines.append("")
    lines.append("=" * 40)
    return "\n".join(lines)
