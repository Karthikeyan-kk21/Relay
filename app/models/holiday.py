from app.extensions import db


DAY_TYPES = ["Holiday", "Half Day", "WFH"]

DAY_TYPE_COLORS = {
    "Holiday":  "#ef4444",   # red
    "Half Day": "#f59e0b",   # amber
    "WFH":      "#38bdf8",   # sky blue
}

DAY_TYPE_EMOJIS = {
    "Holiday":  "🔴",
    "Half Day": "🟡",
    "WFH":      "🔵",
}


class Holiday(db.Model):
    __tablename__ = "holidays"

    id          = db.Column(db.Integer, primary_key=True)
    date        = db.Column(db.Date, unique=True, nullable=False)
    name        = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    day_type    = db.Column(db.String(30), nullable=False, default="Holiday")
    color       = db.Column(db.String(10), nullable=True)   # override hex, optional

    def display_color(self):
        return self.color or DAY_TYPE_COLORS.get(self.day_type, "#6b7280")

    def emoji(self):
        return DAY_TYPE_EMOJIS.get(self.day_type, "📅")

    def __repr__(self):
        return f"<Holiday {self.date}: {self.name} [{self.day_type}]>"
