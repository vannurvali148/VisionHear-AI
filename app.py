
import os
import sys
import sqlite3
from io import BytesIO
from pathlib import Path
from functools import wraps
from datetime import datetime
from xml.sax.saxutils import escape

from flask import (
    Flask, request, jsonify, session, redirect,
    url_for, render_template, send_from_directory,
    send_file, abort
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)

from database import get_connection, init_db


# =====================================================
# 1. APPLICATION CONFIGURATION
# =====================================================

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
TEMPLATE_DIR = BASE_DIR / "templates"

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(FRONTEND_DIR),
    static_url_path="/static"
)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "visionhear-ai-change-this-secret-key"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

init_db()


# =====================================================
# 2. DATABASE MIGRATIONS
# =====================================================

def ensure_column(table, column, definition):

    with get_connection() as conn:

        columns = {
            row["name"]
            for row in conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }

        if column not in columns:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )


def ensure_database():

    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            )
        """)

    ensure_column("eye_tests", "test_mode", "TEXT")
    ensure_column(
        "hearing_responses",
        "intensity_level",
        "TEXT"
    )
    ensure_column(
        "hearing_responses",
        "intensity_percent",
        "INTEGER"
    )


ensure_database()


# =====================================================
# 3. COMMON HELPERS
# =====================================================

def get_owner_email():

    with get_connection() as conn:

        row = conn.execute("""
            SELECT setting_value
            FROM system_settings
            WHERE setting_key = 'owner_email'
        """).fetchone()

    return row["setting_value"] if row else None


def record_activity(user_id, activity, details=""):

    with get_connection() as conn:

        conn.execute("""
            INSERT INTO activity_logs (
                user_id,
                activity,
                details
            )
            VALUES (?, ?, ?)
        """, (user_id, activity, details))


# =====================================================
# 4. ACCESS CONTROL
# =====================================================

def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


def student_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return jsonify({
                "success": False,
                "error": "Please login first"
            }), 401

        if session.get("role") != "student":
            return jsonify({
                "success": False,
                "error": "Student access only"
            }), 403

        return func(*args, **kwargs)

    return wrapper


def admin_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        owner_email = get_owner_email()

        if (
            "user_id" not in session
            or session.get("role") != "admin"
            or not owner_email
            or session.get("email", "").lower()
            != owner_email.lower()
        ):
            return jsonify({
                "success": False,
                "error": "Owner access only"
            }), 403

        return func(*args, **kwargs)

    return wrapper


# =====================================================
# 5. HOME AND STATIC FILES
# =====================================================

@app.route("/")
def home():

    if (FRONTEND_DIR / "index.html").exists():
        return send_from_directory(FRONTEND_DIR, "index.html")

    return "VisionHear AI server is running."


@app.route("/static/<path:filename>")
def static_files(filename):

    return send_from_directory(FRONTEND_DIR, filename)


# =====================================================
# 6. REGISTRATION
# =====================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "GET":
        return render_template("register.html")

    data = request.get_json(silent=True) or request.form

    full_name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not full_name or not email or len(password) < 8:
        return jsonify({
            "success": False,
            "error": "Enter name, email and password of at least 8 characters"
        }), 400

    try:

        with get_connection() as conn:

            conn.execute("""
                INSERT INTO users (
                    full_name,
                    email,
                    password_hash,
                    role
                )
                VALUES (?, ?, ?, 'student')
            """, (
                full_name,
                email,
                generate_password_hash(password)
            ))

        return jsonify({
            "success": True,
            "message": "Registration successful"
        }), 201

    except sqlite3.IntegrityError:

        return jsonify({
            "success": False,
            "error": "Email already registered"
        }), 409


# =====================================================
# 7. LOGIN
# =====================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "GET":
        return render_template("login.html")

    data = request.get_json(silent=True) or request.form

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    with get_connection() as conn:

        user = conn.execute("""
            SELECT *
            FROM users
            WHERE email = ?
        """, (email,)).fetchone()

    if (
        not user
        or not check_password_hash(
            user["password_hash"],
            password
        )
    ):
        return jsonify({
            "success": False,
            "error": "Incorrect email or password"
        }), 401

    session.clear()

    session["user_id"] = user["id"]
    session["full_name"] = user["full_name"]
    session["email"] = user["email"]
    session["role"] = user["role"]

    record_activity(
        user["id"],
        "Login",
        "User logged in"
    )

    owner_email = get_owner_email()

    if (
        user["role"] == "admin"
        and owner_email
        and email == owner_email.lower()
    ):
        destination = "/admin-dashboard"
    else:
        destination = "/dashboard"

    if not request.is_json:
        return redirect(destination)

    return jsonify({
        "success": True,
        "message": "Login successful",
        "redirect": destination,
        "role": user["role"]
    })


# =====================================================
# 8. LOGOUT AND USER INFORMATION
# =====================================================

@app.route("/logout")
def logout():

    user_id = session.get("user_id")

    if user_id:
        record_activity(
            user_id,
            "Logout",
            "User logged out"
        )

    session.clear()

    return redirect("/")


@app.route("/api/me")
def api_me():

    if "user_id" not in session:
        return jsonify({"logged_in": False}), 401

    return jsonify({
        "logged_in": True,
        "user_id": session["user_id"],
        "full_name": session.get("full_name"),
        "email": session.get("email"),
        "role": session.get("role")
    })


# =====================================================
# 9. STUDENT DASHBOARD AND STATISTICS
# =====================================================

@app.route("/dashboard")
@login_required
def dashboard():

    if session.get("role") != "student":
        return redirect("/admin-dashboard")

    if (FRONTEND_DIR / "dashboard.html").exists():
        return send_from_directory(
            FRONTEND_DIR,
            "dashboard.html"
        )

    return "Student dashboard not found", 404


@app.route("/api/student/stats")
@student_required
def student_stats():

    user_id = session["user_id"]

    with get_connection() as conn:

        eye_count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM eye_tests
            WHERE user_id = ?
              AND status = 'completed'
        """, (user_id,)).fetchone()["total"]

        hearing_count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM hearing_tests
            WHERE user_id = ?
              AND status = 'completed'
        """, (user_id,)).fetchone()["total"]

        average = conn.execute("""
            SELECT AVG(accuracy) AS average
            FROM eye_tests
            WHERE user_id = ?
              AND status = 'completed'
        """, (user_id,)).fetchone()["average"]

    return jsonify({
        "eye_tests": eye_count,
        "hearing_tests": hearing_count,
        "completed_tests": eye_count + hearing_count,
        "average_eye_accuracy": round(average or 0, 2)
    })

# ============================================================
# PART 2: HEARING SCREENING + EYE SCREENING APIs
# ============================================================

# ---------------- HEARING SCREENING PAGE ----------------

@app.route("/hearing-screening")
@login_required
def hearing_screening():
    return render_template("hearing.html")


# ---------------- START HEARING TEST ----------------

@app.route("/api/hearing/start", methods=["POST"])
@login_required
def start_hearing_test():
    user_id = session["user_id"]

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO hearing_tests (user_id, status, started_at)
            VALUES (?, 'in_progress', CURRENT_TIMESTAMP)
        """, (user_id,))
        test_id = cursor.lastrowid

    record_activity(user_id, "Hearing Test Started",
                    f"Hearing test ID: {test_id}")

    return jsonify({
        "success": True,
        "test_id": test_id,
        "message": "Hearing test started successfully"
    })


# ---------------- SAVE HEARING RESPONSE ----------------

@app.route("/api/hearing/response", methods=["POST"])
@login_required
def save_hearing_response():
    data = request.get_json(silent=True) or {}

    test_id = data.get("test_id")
    ear = str(data.get("ear", "")).lower()
    frequency_hz = data.get("frequency_hz")
    response = str(data.get("response", "")).lower()
    response_time = data.get("response_time", 0)

    if not test_id or ear not in ("left", "right"):
        return jsonify({
            "success": False,
            "message": "Invalid test ID or ear"
        }), 400

    if response not in ("heard", "not_heard"):
        return jsonify({
            "success": False,
            "message": "Invalid hearing response"
        }), 400

    try:
        frequency_hz = int(frequency_hz)
        response_time = max(0, float(response_time or 0))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Invalid frequency or response time"
        }), 400

    allowed_frequencies = [125, 250, 500, 1000, 2000, 4000, 6000, 8000]

    if frequency_hz not in allowed_frequencies:
        return jsonify({
            "success": False,
            "message": "Unsupported frequency"
        }), 400

    intensity_level = str(data.get("intensity_level", "Medium"))
    intensity_percent = data.get("intensity_percent", 65)

    try:
        intensity_percent = max(0, min(100, int(intensity_percent)))
    except (TypeError, ValueError):
        intensity_percent = 65

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id FROM hearing_tests
            WHERE id = ? AND user_id = ? AND status = 'in_progress'
        """, (test_id, session["user_id"]))

        if not cursor.fetchone():
            return jsonify({
                "success": False,
                "message": "Active hearing test not found"
            }), 404

        cursor.execute("""
            INSERT INTO hearing_responses
            (test_id, ear, frequency_hz, response, response_time,
             intensity_level, intensity_percent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            test_id,
            ear,
            frequency_hz,
            response,
            response_time,
            intensity_level,
            intensity_percent
        ))

    return jsonify({
        "success": True,
        "message": "Hearing response saved"
    })


# ---------------- COMPLETE HEARING TEST ----------------

@app.route("/api/hearing/complete", methods=["POST"])
@login_required
def complete_hearing_test():
    data = request.get_json(silent=True) or {}
    test_id = data.get("test_id")

    if not test_id:
        return jsonify({
            "success": False,
            "message": "Test ID is required"
        }), 400

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id FROM hearing_tests
            WHERE id = ? AND user_id = ? AND status = 'in_progress'
        """, (test_id, session["user_id"]))

        if not cursor.fetchone():
            return jsonify({
                "success": False,
                "message": "Active hearing test not found"
            }), 404

        cursor.execute("""
            UPDATE hearing_tests
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
        """, (test_id, session["user_id"]))

        cursor.execute("""
            SELECT ear, COUNT(*) AS total
            FROM hearing_responses
            WHERE test_id = ?
            GROUP BY ear
        """, (test_id,))

        ear_counts = {
            row["ear"]: row["total"]
            for row in cursor.fetchall()
        }

    record_activity(
        session["user_id"],
        "Hearing Test Completed",
        f"Hearing test ID: {test_id}"
    )

    return jsonify({
        "success": True,
        "message": "Hearing test completed",
        "left_responses": ear_counts.get("left", 0),
        "right_responses": ear_counts.get("right", 0)
    })


# ============================================================
# EYE SCREENING
# ============================================================

@app.route("/eye-screening")
@login_required
def eye_screening():
    return render_template("eye.html")


# ---------------- START EYE TEST ----------------

@app.route("/api/eye/start", methods=["POST"])
@login_required
def start_eye_test():
    data = request.get_json(silent=True) or {}

    test_mode = str(data.get("test_mode", "without")).lower()

    if test_mode not in ("with", "without"):
        return jsonify({
            "success": False,
            "message": "Invalid test mode"
        }), 400

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO eye_tests (user_id, status, test_mode, started_at)
            VALUES (?, 'in_progress', ?, CURRENT_TIMESTAMP)
        """, (session["user_id"], test_mode))

        test_id = cursor.lastrowid

    record_activity(
        session["user_id"],
        "Eye Test Started",
        f"Mode: {test_mode}, Test ID: {test_id}"
    )

    return jsonify({
        "success": True,
        "test_id": test_id,
        "test_mode": test_mode,
        "message": "Eye test started successfully"
    })


# ---------------- SAVE EYE RESPONSE ----------------

@app.route("/api/eye/response", methods=["POST"])
@login_required
def save_eye_response():
    data = request.get_json(silent=True) or {}

    test_id = data.get("test_id")
    question_number = data.get("question_number")
    response = str(data.get("response", ""))
    is_correct = data.get("is_correct", False)
    response_time = data.get("response_time", 0)

    if not test_id or question_number is None:
        return jsonify({
            "success": False,
            "message": "Test ID and question number are required"
        }), 400

    try:
        question_number = int(question_number)
        response_time = max(0, float(response_time or 0))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Invalid question number or response time"
        }), 400

    if question_number < 1:
        return jsonify({
            "success": False,
            "message": "Invalid question number"
        }), 400

    if isinstance(is_correct, str):
        is_correct = is_correct.lower() in ("true", "1", "yes")

    is_correct = 1 if is_correct else 0

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id FROM eye_tests
            WHERE id = ? AND user_id = ? AND status = 'in_progress'
        """, (test_id, session["user_id"]))

        if not cursor.fetchone():
            return jsonify({
                "success": False,
                "message": "Active eye test not found"
            }), 404

        cursor.execute("""
            INSERT INTO eye_responses
            (test_id, question_number, response, is_correct, response_time)
            VALUES (?, ?, ?, ?, ?)
        """, (
            test_id,
            question_number,
            response,
            is_correct,
            response_time
        ))

    return jsonify({
        "success": True,
        "message": "Eye response saved"
    })


# ---------------- COMPLETE EYE TEST ----------------

@app.route("/api/eye/complete", methods=["POST"])
@login_required
def complete_eye_test():
    data = request.get_json(silent=True) or {}

    test_id = data.get("test_id")
    test_mode = str(data.get("test_mode", "without")).lower()

    if not test_id:
        return jsonify({
            "success": False,
            "message": "Test ID is required"
        }), 400

    if test_mode not in ("with", "without"):
        test_mode = "without"

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, test_mode
            FROM eye_tests
            WHERE id = ? AND user_id = ? AND status = 'in_progress'
        """, (test_id, session["user_id"]))

        test = cursor.fetchone()

        if not test:
            return jsonify({
                "success": False,
                "message": "Active eye test not found"
            }), 404

        # Use the mode saved when the test started.
        saved_mode = test["test_mode"] or test_mode

        cursor.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(is_correct) AS correct,
                AVG(response_time) AS average_time
            FROM eye_responses
            WHERE test_id = ?
        """, (test_id,))

        result = cursor.fetchone()

        total = result["total"] or 0
        correct = result["correct"] or 0
        average_time = result["average_time"] or 0

        accuracy = round((correct / total) * 100, 2) if total else 0
        average_time = round(float(average_time), 2)

        cursor.execute("""
            UPDATE eye_tests
            SET status = 'completed',
                accuracy = ?,
                average_response_time = ?,
                test_mode = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
        """, (
            accuracy,
            average_time,
            saved_mode,
            test_id,
            session["user_id"]
        ))

    record_activity(
        session["user_id"],
        "Eye Test Completed",
        f"Mode: {saved_mode}, Accuracy: {accuracy}%, Test ID: {test_id}"
    )

    return jsonify({
        "success": True,
        "message": "Eye test completed successfully",
        "test_id": test_id,
        "test_mode": saved_mode,
        "total_questions": total,
        "correct_answers": correct,
        "accuracy": accuracy,
        "average_response_time": average_time
    })


# ============================================================
# END OF PART 2
# PART 3 WILL CONTAIN ADMIN APIs AND PDF REPORT GENERATION
# ============================================================
