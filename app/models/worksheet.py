from app.extensions import db
from datetime import datetime


class Worksheet(db.Model):
    __tablename__ = "worksheets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    content = db.Column(db.Text, nullable=True)
    is_locked = db.Column(db.Boolean, default=False)
    admin_unlocked = db.Column(db.Boolean, default=False)
    unlock_requested = db.Column(db.Boolean, default=False)
    unlock_requested_at = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)


    user = db.relationship("User", backref="worksheets")

    __table_args__ = (
        db.UniqueConstraint("user_id", "date", name="uq_worksheet_user_date"),
    )

    def is_submitted(self):
        return bool(self.content and self.content.strip())

    def status_label(self):
        if self.is_submitted():
            return "Updated"
        return "Pending"

    def status_color(self):
        return "success" if self.is_submitted() else "danger"
