import click
from flask import Flask, redirect, url_for
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from config import Config
from app.extensions import db, migrate, login_manager


# ─── CLI Commands ─────────────────────────────────────────────────────────────

@click.command("create-admin")
@click.argument("employee_id")
@click.argument("full_name")
@click.argument("email")
@click.argument("password")
@with_appcontext
def create_admin_cmd(employee_id, full_name, email, password):
    """Create an admin user. Usage: flask create-admin EMP001 'Your Name' email@example.com password"""
    from app.models import User

    if User.query.filter_by(employee_id=employee_id).first():
        click.echo(f"ERROR: Employee ID '{employee_id}' already exists.")
        return

    user = User(
        employee_id=employee_id,
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
        role="admin",
        active=True,
    )
    db.session.add(user)
    db.session.commit()
    click.echo(f"[OK] Admin '{full_name}' created successfully. Login with ID: {employee_id}")


@click.command("change-password")
@click.argument("employee_id")
@click.argument("new_password")
@with_appcontext
def change_password_cmd(employee_id, new_password):
    """Change password for any account. Usage: flask change-password ADMIN001 newpassword123"""
    from app.models import User
    user = User.query.filter_by(employee_id=employee_id).first()
    if not user:
        click.echo(f"ERROR: User with Employee ID '{employee_id}' not found.")
        return
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    click.echo(f"[OK] Password for '{user.full_name}' ({employee_id}) updated successfully.")



@click.command("seed-settings")
@with_appcontext
def seed_settings_cmd():
    """Seed default application settings into the database."""
    from app.models import Setting
    from app.models.setting import DEFAULT_SETTINGS

    count = 0
    for s in DEFAULT_SETTINGS:
        existing = Setting.query.filter_by(key=s["key"]).first()
        if not existing:
            db.session.add(Setting(
                key=s["key"],
                value=s["value"],
                description=s["description"],
            ))
            count += 1

    db.session.commit()
    click.echo(f"[OK] Seeded {count} default settings.")


@click.command("init-local-db")
@with_appcontext
def init_local_db_cmd():
    """Initialize local database schema and default admin/employee accounts."""
    from app.models import User, Setting
    from app.models.setting import DEFAULT_SETTINGS

    db.create_all()
    click.echo("[OK] Database tables created/verified.")

    count = 0
    for s in DEFAULT_SETTINGS:
        if not Setting.query.filter_by(key=s["key"]).first():
            db.session.add(Setting(key=s["key"], value=s["value"], description=s["description"]))
            count += 1
    db.session.commit()
    click.echo(f"[OK] Seeded {count} default settings.")

    if not User.query.filter_by(employee_id="ADMIN001").first():
        admin = User(
            employee_id="ADMIN001",
            full_name="Admin",
            email="admin@relay.com",
            password_hash=generate_password_hash("admin123"),
            role="admin",
            active=True
        )
        db.session.add(admin)
        click.echo("[OK] Admin account created (ADMIN001 / admin123).")

    if not User.query.filter_by(employee_id="EMP001").first():
        emp = User(
            employee_id="EMP001",
            full_name="Karthikeyan",
            email="karthikeyan@test.com",
            password_hash=generate_password_hash("emp123"),
            role="user",
            active=True
        )
        db.session.add(emp)
        click.echo("[OK] Employee account created (EMP001 / emp123).")

    db.session.commit()
    click.echo("[OK] Local DB setup complete.")


# ─── Application Factory ──────────────────────────────────────────────────────

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    
    from app.extensions import mail
    mail.init_app(app)

    # Import all models so Flask-Migrate can detect them
    from app.models import User, Attendance, Worksheet, Setting, Holiday  # noqa: F401

    # Start background scheduler (prevent double run in debug reload mode)
    import os
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from app.extensions import scheduler
        from app.services.scheduler import compile_daily_report_job
        
        if not scheduler.running:
            # Schedule report compilation daily at 19:00 (7:00 PM) IST
            scheduler.add_job(
                id="daily_report_compilation",
                func=compile_daily_report_job,
                args=[app],
                trigger="cron",
                hour=19,
                minute=0,
                replace_existing=True
            )
            # Schedule daily database backup at 00:00 (12:00 AM Midnight) IST
            from app.services.scheduler import daily_db_backup_job
            scheduler.add_job(
                id="daily_db_backup",
                func=daily_db_backup_job,
                args=[app],
                trigger="cron",
                hour=0,
                minute=0,
                replace_existing=True
            )
            scheduler.start()


    # Register blueprints
    from app.auth import auth_bp
    from app.employee import employee_bp
    from app.admin import admin_bp
    from app.ai import ai_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(employee_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(ai_bp)

    # Load user for Flask-Login
    from app.auth.utils import load_user  # noqa: F401

    # Maintenance Mode check
    @app.before_request
    def check_maintenance_mode():
        from flask import request, render_template
        from flask_login import current_user
        from app.models import Setting

        # Allow static files and auth routes (so admins can log in)
        if request.endpoint and (request.endpoint == 'static' or request.endpoint.startswith('auth.')):
            return None

        # Check maintenance mode setting
        maint_on = Setting.get("maintenance_mode", "false").lower() == "true"
        if maint_on:
            # Allow admins to bypass maintenance mode
            if current_user.is_authenticated and current_user.role == "admin":
                return None
            return render_template("maintenance.html"), 503

        return None

    # Simulated Global System Outage (Manual Bug)
    @app.before_request
    def trigger_global_system_outage():
        from flask import request
        if request.endpoint and request.endpoint == 'static':
            return None
        raise RuntimeError("CRITICAL SYSTEM FAILURE: Core service unavailable. Website is down (Simulated Bug).")

    # Root redirect
    @app.route("/")
    def index():
        return redirect(url_for("auth.login"))


    # Register CLI commands
    app.cli.add_command(create_admin_cmd)
    app.cli.add_command(change_password_cmd)
    app.cli.add_command(seed_settings_cmd)
    app.cli.add_command(init_local_db_cmd)

    return app