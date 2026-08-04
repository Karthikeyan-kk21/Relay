from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature

from app.auth import auth_bp
from app.models import User
from app.extensions import db


def get_serializer():
    secret = current_app.config.get("SECRET_KEY", "relay-secret-key-2026")
    return URLSafeTimedSerializer(secret)


def generate_reset_token(user_id):
    serializer = get_serializer()
    return serializer.dumps(user_id, salt="reset-password-salt")


def verify_reset_token(token, max_age=3600):
    serializer = get_serializer()
    try:
        user_id = serializer.loads(token, salt="reset-password-salt", max_age=max_age)
        return user_id
    except (SignatureExpired, BadTimeSignature):
        return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.role == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("employee.dashboard"))

    if request.method == "POST":
        employee_id = request.form.get("employee_id", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter(
            db.func.lower(User.employee_id) == employee_id.lower(),
            User.active == True
        ).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=False)
            if user.role == "admin":
                return redirect(url_for("admin.dashboard"))
            return redirect(url_for("employee.dashboard"))

        flash("Invalid Employee ID or password.", "error")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# ─── Forgot Password ──────────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    identifier = request.form.get("identifier", "").strip()

    if not identifier:
        return jsonify({"success": False, "message": "Please enter your Employee ID or Email."}), 400

    identifier_lower = identifier.lower()
    user = User.query.filter(
        (db.func.lower(User.employee_id) == identifier_lower) | (db.func.lower(User.email) == identifier_lower)
    ).filter_by(active=True).first()


    if not user:
        return jsonify({"success": False, "message": f"No active account found for '{identifier}'."}), 404

    token = generate_reset_token(user.id)
    reset_url = url_for("auth.reset_password", token=token, _external=True)

    # Try sending email via Flask-Mail
    email_sent = False
    mail_username = current_app.config.get("MAIL_USERNAME")
    if mail_username:
        try:
            from flask_mail import Message
            from app.extensions import mail
            msg = Message(
                subject="Reset Your Password — Relay",
                recipients=[user.email],
                body=f"Hello {user.full_name},\n\nYou requested a password reset for your Relay account.\nClick the link below to reset your password:\n\n{reset_url}\n\nThis link is valid for 1 hour.\n\nIf you did not request this, please ignore this email."
            )
            mail.send(msg)
            email_sent = True
        except Exception as e:
            current_app.logger.error(f"Failed to send reset email: {e}")

    if email_sent:
        return jsonify({
            "success": True,
            "message": f"A password reset link has been sent to {user.email}.",
            "reset_url": reset_url
        })
    else:
        return jsonify({
            "success": True,
            "message": f"Password reset link generated for {user.full_name} ({user.employee_id}).",
            "reset_url": reset_url
        })


# ─── Reset Password ───────────────────────────────────────────────────────────

@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user_id = verify_reset_token(token)

    if not user_id:
        flash("The password reset link is invalid or has expired. Please request a new one.", "error")
        return redirect(url_for("auth.login"))

    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        new_password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not new_password or len(new_password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("auth/reset_password.html", token=token, user=user)

        if new_password != confirm_password:
            flash("Passwords do not match. Please try again.", "error")
            return render_template("auth/reset_password.html", token=token, user=user)

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()

        flash("Your password has been updated successfully. Please sign in with your new password.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token, user=user)
