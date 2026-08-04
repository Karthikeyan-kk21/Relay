from app.extensions import db


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), unique=True, nullable=False)
    value = db.Column(db.String(300), nullable=False, default="")
    description = db.Column(db.String(200), nullable=True)

    @classmethod
    def get(cls, key, default=None):
        """Get setting value by key."""
        setting = cls.query.filter_by(key=key).first()
        return setting.value if setting else default

    @classmethod
    def set_value(cls, key, value):
        """Set setting value by key, creating if not exists."""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = cls(key=key, value=str(value))
            db.session.add(setting)
        db.session.commit()

    def __repr__(self):
        return f"<Setting {self.key}={self.value}>"


# Default settings seed data
DEFAULT_SETTINGS = [
    {
        "key": "office_ip",
        "value": "",
        "description": "Office IP address for attendance validation (leave empty to disable)",
    },
    {
        "key": "checkin_time",
        "value": "09:30",
        "description": "On-time check-in deadline (HH:MM, 24h format)",
    },
    {
        "key": "late_threshold",
        "value": "09:35",
        "description": "Late check-in threshold — after this time, marked Late (HH:MM)",
    },
    {
        "key": "worksheet_lock_time",
        "value": "18:30",
        "description": "Worksheet locks at this time every day (HH:MM)",
    },
    {
        "key": "last_entry_time",
        "value": "11:00",
        "description": "Last allowed self-check-in time for employees (HH:MM)",
    },
    {
        "key": "disable_timing_lock",
        "value": "false",
        "description": "Disable all timing locks for testing (true / false)",
    },
    {
        "key": "weekend_policy",
        "value": "sunday_only",
        "description": "Week off policy: 'sunday_only' or 'sat_sun'",
    },
    {
        "key": "maintenance_mode",
        "value": "false",
        "description": "System maintenance mode — blocks employee access when true",
    },
]


