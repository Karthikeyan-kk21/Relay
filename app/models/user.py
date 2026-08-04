from app.extensions import db
from flask_login import UserMixin

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(20), unique=True, nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(20), default="user")
    active = db.Column(db.Boolean, default=True)
    section = db.Column(db.String(20), default="Section 2", nullable=False)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    joining_date = db.Column(db.Date, nullable=True)