from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail
from apscheduler.schedulers.background import BackgroundScheduler

db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please login first."
