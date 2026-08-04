from app.extensions import db
import pytz
from datetime import datetime

IST = pytz.timezone("Asia/Kolkata")


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.DateTime, nullable=True)
    check_out = db.Column(db.DateTime, nullable=True)
    # Status: Present, Late, Absent, WFH, HD, Leave
    status = db.Column(db.String(20), default="Absent")
    ip_address = db.Column(db.String(50), nullable=True)
    admin_unlocked = db.Column(db.Boolean, default=False)

    user = db.relationship("User", backref="attendances")

    __table_args__ = (
        db.UniqueConstraint("user_id", "date", name="uq_attendance_user_date"),
    )

    def check_in_ist(self):
        if self.check_in:
            return self.check_in.strftime("%I:%M %p")
        return "--"

    def check_out_ist(self):
        if self.check_out:
            return self.check_out.strftime("%I:%M %p")
        return "--"

    def duration(self):
        if self.check_in and self.check_out:
            delta = self.check_out - self.check_in
            total_minutes = int(delta.total_seconds() // 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            return f"{hours}h {minutes}m"
        return "--"

    def status_color(self):
        colors = {
            "Present": "success",
            "Late": "warning",
            "Absent": "danger",
            "WFH": "info",
            "HD": "purple",
            "Leave": "muted",
        }
        return colors.get(self.status, "muted")
