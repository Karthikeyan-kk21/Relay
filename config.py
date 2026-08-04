import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "relay-fallback-secret-2026")
    
    # Environment mode: 'development' (Local DB) vs 'production' (Live Supabase DB)
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    DEV_DATABASE_URL = os.getenv("DEV_DATABASE_URL", "sqlite:///dev_relay.db")
    PROD_DATABASE_URL = os.getenv("PROD_DATABASE_URL") or os.getenv("DATABASE_URL", "")

    if FLASK_ENV == "production" and PROD_DATABASE_URL:
        SQLALCHEMY_DATABASE_URI = PROD_DATABASE_URL
    else:
        SQLALCHEMY_DATABASE_URI = DEV_DATABASE_URL or "sqlite:///dev_relay.db"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None


    # Email Settings
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER")