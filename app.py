import secrets
import sqlite3
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db, close_db, init_db


# --------------------------------------------------
# APP CONFIGURATION
# --------------------------------------------------

app = Flask(__name__)

app.config["SECRET_KEY"] = secrets.token_hex(32)

# Use the SECRET_KEY from your .env file when available.
from dotenv import load_dotenv
import os

load_dotenv()
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", app.config["SECRET_KEY"])

app.teardown_appcontext(close_db)


# --------------------------------------------------
# CSRF PROTECTION
# --------------------------------------------------

@app.before_request
def protect_forms():
    if request.method == "POST":
        submitted_token = request.form.get("csrf_token")
        session_token = session.get("csrf_token")

        if (
            not submitted_token
            or not session_token
            or submitted_token != session_token
        ):
            abort(400, description="Invalid form submission. Please refresh and try again.")


@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)

    return {"csrf_token": session["csrf_token"]}


# --------------------------------------------------
# LOGIN PROTECTION
# --------------------------------------------------

def login_required(view_function):
    @wraps(view_function)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return decorated_function


def get_owned_lead(lead_id):
    """Return a lead only if it belongs to the logged-in user."""
    db = get_db()

    lead = db.execute(
        "SELECT * FROM leads WHERE id = ? AND user_id = ?",
        (lead_id, session["user_id"])
    ).fetchone()

    if lead is None:
        abort(404)

    return lead


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return render_template("home.html")


# --------------------------------------------------
# USER REGISTRATION
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password or not confirm_password:
            flash("Please fill in all fields.", "error")
            return redirect(url_for("register"))

        if len(username) < 3:
            flash("Username must contain at least 3 characters.", "error")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)

        db = get_db()

        try:
            cursor = db.execute(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES (?, ?, ?)
                """,
                (username, email, password_hash)
            )
            db.commit()

            session.clear()
            session["user_id"] = cursor.lastrowid
            session["username"] = username
            session["csrf_token"] = secrets.token_urlsafe(32)

            flash("Your account has been created successfully!", "success")
            return redirect(url_for("dashboard"))

        except sqlite3.IntegrityError:
            db.rollback()
            flash("That username or email is already registered.", "error")
            return redirect(url_for("register"))

    return render_template("register.html")


# --------------------------------------------------
# USER LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()

        user = db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["csrf_token"] = secrets.token_urlsafe(32)

            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


# --------------------------------------------------
# USER DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user_id = session["user_id"]

    leads = db.execute(
        """
        SELECT * FROM leads
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,)
    ).fetchall()

    total_leads = db.execute(
        "SELECT COUNT(*) FROM leads WHERE user_id = ?",
        (user_id,)
    ).fetchone()[0]

    new_leads = db.execute(
        "SELECT COUNT(*) FROM leads WHERE user_id = ? AND status = 'New'",
        (user_id,)
    ).fetchone()[0]

    contacted_leads = db.execute(
        "SELECT COUNT(*) FROM leads WHERE user_id = ? AND status = 'Contacted'",
        (user_id,)
    ).fetchone()[0]

    converted_leads = db.execute(
        "SELECT COUNT(*) FROM leads WHERE user_id = ? AND status = 'Converted'",
        (user_id,)
    ).fetchone()[0]

    upcoming_followups = db.execute(
        """
        SELECT follow_ups.*, leads.name AS lead_name
        FROM follow_ups
        JOIN leads ON follow_ups.lead_id = leads.id
        WHERE leads.user_id = ?
          AND follow_ups.completed = 0
        ORDER BY follow_ups.follow_up_date ASC
        """,
        (user_id,)
    ).fetchall()

    return render_template(
        "dashboard.html",
        leads=leads,
        total_leads=total_leads,
        new_leads=new_leads,
        contacted_leads=contacted_leads,
        converted_leads=converted_leads,
        upcoming_followups=upcoming_followups,
        username=session.get("username")
    )


# --------------------------------------------------
# ADD A LEAD
# --------------------------------------------------

@app.route("/add-lead", methods=["POST"])
@login_required
def add_lead():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    source = request.form.get("source", "").strip()

    if not name or not email:
        flash("Lead name and email are required.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()

    db.execute(
        """
        INSERT INTO leads (user_id, name, email, phone, source)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session["user_id"], name, email, phone, source)
    )

    db.commit()

    flash("Lead added successfully!", "success")
    return redirect(url_for("dashboard"))


# --------------------------------------------------
# UPDATE LEAD STATUS
# --------------------------------------------------

@app.route("/update-status/<int:lead_id>", methods=["POST"])
@login_required
def update_status(lead_id):
    get_owned_lead(lead_id)

    status = request.form.get("status", "")

    allowed_statuses = ["New", "Contacted", "Converted"]

    if status not in allowed_statuses:
        flash("Invalid lead status.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()

    db.execute(
        "UPDATE leads SET status = ? WHERE id = ? AND user_id = ?",
        (status, lead_id, session["user_id"])
    )

    db.commit()

    flash("Lead status updated.", "success")
    return redirect(url_for("dashboard"))


# --------------------------------------------------
# DELETE A LEAD
# --------------------------------------------------

@app.route("/delete-lead/<int:lead_id>", methods=["POST"])
@login_required
def delete_lead(lead_id):
    get_owned_lead(lead_id)

    db = get_db()

    db.execute(
        "DELETE FROM leads WHERE id = ? AND user_id = ?",
        (lead_id, session["user_id"])
    )

    db.commit()

    flash("Lead deleted successfully.", "success")
    return redirect(url_for("dashboard"))


# --------------------------------------------------
# VIEW LEAD DETAILS
# --------------------------------------------------

@app.route("/lead/<int:lead_id>")
@login_required
def lead_details(lead_id):
    lead = get_owned_lead(lead_id)
    db = get_db()

    notes = db.execute(
        """
        SELECT * FROM lead_notes
        WHERE lead_id = ?
        ORDER BY created_at DESC
        """,
        (lead_id,)
    ).fetchall()

    follow_ups = db.execute(
        """
        SELECT * FROM follow_ups
        WHERE lead_id = ?
        ORDER BY follow_up_date ASC
        """,
        (lead_id,)
    ).fetchall()

    return render_template(
        "lead.html",
        lead=lead,
        notes=notes,
        follow_ups=follow_ups
    )


# --------------------------------------------------
# ADD A NOTE TO A LEAD
# --------------------------------------------------

@app.route("/add-note/<int:lead_id>", methods=["POST"])
@login_required
def add_note(lead_id):
    get_owned_lead(lead_id)

    note = request.form.get("note", "").strip()

    if not note:
        flash("Please enter a note.", "error")
        return redirect(url_for("lead_details", lead_id=lead_id))

    db = get_db()

    db.execute(
        "INSERT INTO lead_notes (lead_id, note) VALUES (?, ?)",
        (lead_id, note)
    )

    db.commit()

    flash("Note added successfully.", "success")
    return redirect(url_for("lead_details", lead_id=lead_id))


# --------------------------------------------------
# ADD A FOLLOW-UP
# --------------------------------------------------

@app.route("/add-follow-up/<int:lead_id>", methods=["POST"])
@login_required
def add_follow_up(lead_id):
    get_owned_lead(lead_id)

    follow_up_date = request.form.get("follow_up_date", "").strip()
    description = request.form.get("description", "").strip()

    if not follow_up_date or not description:
        flash("Please enter the follow-up date and description.", "error")
        return redirect(url_for("lead_details", lead_id=lead_id))

    db = get_db()

    db.execute(
        """
        INSERT INTO follow_ups (lead_id, follow_up_date, description)
        VALUES (?, ?, ?)
        """,
        (lead_id, follow_up_date, description)
    )

    db.commit()

    flash("Follow-up added successfully.", "success")
    return redirect(url_for("lead_details", lead_id=lead_id))


# --------------------------------------------------
# MARK FOLLOW-UP AS COMPLETED
# --------------------------------------------------

@app.route("/complete-follow-up/<int:follow_up_id>", methods=["POST"])
@login_required
def complete_follow_up(follow_up_id):
    db = get_db()

    db.execute(
        """
        UPDATE follow_ups
        SET completed = 1
        WHERE id = ?
          AND lead_id IN (
              SELECT id FROM leads WHERE user_id = ?
          )
        """,
        (follow_up_id, session["user_id"])
    )

    db.commit()

    flash("Follow-up marked as completed.", "success")
    return redirect(url_for("dashboard"))


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True)