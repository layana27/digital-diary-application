
import os
from functools import wraps
from datetime import date

import psycopg
from psycopg.rows import dict_row
from psycopg import IntegrityError

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from werkzeug.security import (
    generate_password_hash, check_password_hash
)

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "digital-diary-local-development-key"
)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Four active diary modules
CATEGORIES = {
    "expense": "Expense Diary",
    "study": "Study Plan",
    "health": "Health Diary",
    "personal": "Personal Diary",
}

CATEGORY_ALIASES = {
    "expense": "expense",
    "Expense Diary": "expense",
    "study": "study",
    "Study Plan": "study",
    "Study Planner": "study",
    "health": "health",
    "Health Diary": "health",
    "personal": "personal",
    "Personal Diary": "personal",
}


def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Set it in Render Environment."
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10
    )


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name VARCHAR(150) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id)
                    ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                content TEXT DEFAULT '',
                entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
                category VARCHAR(100) NOT NULL DEFAULT 'Personal Diary',
                amount NUMERIC(12, 2),
                location VARCHAR(255),
                status VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expense_category VARCHAR(100),
                study_subject VARCHAR(255),
                activity VARCHAR(255),
                exercise_minutes INTEGER,
                water_glasses NUMERIC(5, 2),
                water_goal NUMERIC(5, 2),
                sleep_hours NUMERIC(5, 2),
                meditation_minutes INTEGER,
                meals TEXT,
                health_status VARCHAR(100),
                period_start DATE,
                period_end DATE,
                flow VARCHAR(100),
                symptoms TEXT
            )
        """)

        # Safely add missing columns to an existing database.
        migrations = {
            "title": "VARCHAR(255)",
            "content": "TEXT DEFAULT ''",
            "entry_date": "DATE DEFAULT CURRENT_DATE",
            "category": "VARCHAR(100) DEFAULT 'Personal Diary'",
            "amount": "NUMERIC(12, 2)",
            "location": "VARCHAR(255)",
            "status": "VARCHAR(100)",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "expense_category": "VARCHAR(100)",
            "study_subject": "VARCHAR(255)",
            "activity": "VARCHAR(255)",
            "exercise_minutes": "INTEGER",
            "water_glasses": "NUMERIC(5, 2)",
            "water_goal": "NUMERIC(5, 2)",
            "sleep_hours": "NUMERIC(5, 2)",
            "meditation_minutes": "INTEGER",
            "meals": "TEXT",
            "health_status": "VARCHAR(100)",
            "period_start": "DATE",
            "period_end": "DATE",
            "flow": "VARCHAR(100)",
            "symptoms": "TEXT",
        }

        for column, data_type in migrations.items():
            conn.execute(
                f"ALTER TABLE entries ADD COLUMN IF NOT EXISTS "
                f"{column} {data_type}"
            )

        conn.execute("""
            UPDATE entries
            SET category = 'Personal Diary'
            WHERE category IS NULL OR TRIM(category) = ''
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_user_date
            ON entries(user_id, entry_date DESC)
        """)


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapper


def get_category_key(category):
    if not category:
        return None
    return CATEGORY_ALIASES.get(category.strip())


def get_entry(entry_id, user_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT *
            FROM entries
            WHERE id = %s AND user_id = %s
        """, (entry_id, user_id)).fetchone()


@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all required fields.", "danger")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "danger")
            return render_template("register.html")

        password_hash = generate_password_hash(password)

        try:
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO users (name, email, password_hash)
                    VALUES (%s, %s, %s)
                """, (name, email, password_hash))

            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))

        except IntegrityError:
            flash("This email is already registered.", "danger")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute("""
                SELECT id, name, email, password_hash
                FROM users
                WHERE LOWER(email) = %s
            """, (email,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    with get_db() as conn:
        result = conn.execute("""
            SELECT COUNT(*) AS total
            FROM entries
            WHERE user_id = %s
              AND category = ANY(%s)
        """, (
            session["user_id"], list(CATEGORIES.values())
        )).fetchone()

    return render_template(
        "dashboard.html",
        name=session.get("name", "Friend"),
        total_entries=result["total"],
        categories=CATEGORIES
    )


@app.route("/module/<category>")
@login_required
def module(category):
    category_key = get_category_key(category)

    if category_key not in CATEGORIES:
        flash("Module not found.", "danger")
        return redirect(url_for("dashboard"))

    category_name = CATEGORIES[category_key]
    search = request.args.get("search", "").strip()
    user_id = session["user_id"]

    with get_db() as conn:
        if search:
            entries = conn.execute("""
                SELECT *
                FROM entries
                WHERE user_id = %s
                  AND category = %s
                  AND (
                      title ILIKE %s OR content ILIKE %s
                      OR COALESCE(location, '') ILIKE %s
                      OR COALESCE(expense_category, '') ILIKE %s
                      OR COALESCE(study_subject, '') ILIKE %s
                      OR COALESCE(activity, '') ILIKE %s
                  )
                ORDER BY entry_date DESC, id DESC
            """, (
                user_id, category_name,
                f"%{search}%", f"%{search}%", f"%{search}%",
                f"%{search}%", f"%{search}%", f"%{search}%"
            )).fetchall()
        else:
            entries = conn.execute("""
                SELECT *
                FROM entries
                WHERE user_id = %s AND category = %s
                ORDER BY entry_date DESC, id DESC
            """, (user_id, category_name)).fetchall()

        expense_summary = conn.execute("""
            SELECT
                COALESCE(SUM(amount), 0) AS total,
                COALESCE(SUM(amount), 0) AS total_amount,
                0::NUMERIC AS budget
            FROM entries
            WHERE user_id = %s
              AND category = 'Expense Diary'
        """, (user_id,)).fetchone()

        health_summary = conn.execute("""
            SELECT
                COALESCE(AVG(water_glasses), 0) AS average_water,
                COALESCE(AVG(sleep_hours), 0) AS average_sleep,
                COALESCE(SUM(exercise_minutes), 0) AS total_exercise
            FROM entries
            WHERE user_id = %s
              AND category = 'Health Diary'
        """, (user_id,)).fetchone()

    return render_template(
        "module.html",
        category=category_key,
        category_name=category_name,
        entries=entries,
        search=search,
        today=date.today().isoformat(),
        expense_summary=expense_summary,
        health_summary=health_summary
    )


@app.route("/add/<category>", methods=["POST"])
@login_required
def add(category):
    category_key = get_category_key(category)

    if category_key not in CATEGORIES:
        flash("Invalid diary module.", "danger")
        return redirect(url_for("dashboard"))

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    entry_date = request.form.get("entry_date") or date.today().isoformat()
    location = request.form.get("location", "").strip() or None
    status = request.form.get("status", "").strip() or None

    amount_text = request.form.get("amount", "").strip()
    expense_category = request.form.get("expense_category", "").strip() or None
    study_subject = request.form.get("study_subject", "").strip() or None

    activity = request.form.get("activity", "").strip() or None
    exercise_text = request.form.get("exercise_minutes", "").strip()
    water_text = request.form.get("water_glasses", "").strip()
    goal_text = request.form.get("water_goal", "").strip()
    sleep_text = request.form.get("sleep_hours", "").strip()
    meditation_text = request.form.get("meditation_minutes", "").strip()
    meals = request.form.get("meals", "").strip() or None
    health_status = request.form.get("health_status", "").strip() or None
    period_start = request.form.get("period_start", "").strip() or None
    period_end = request.form.get("period_end", "").strip() or None
    flow = request.form.get("flow", "").strip() or None
    symptoms = request.form.get("symptoms", "").strip() or None

    if not title:
        flash("Please enter a title.", "danger")
        return redirect(url_for("module", category=category_key))

    try:
        amount = float(amount_text) if amount_text else None
        exercise_minutes = int(exercise_text) if exercise_text else None
        water_glasses = float(water_text) if water_text else None
        water_goal = float(goal_text) if goal_text else None
        sleep_hours = float(sleep_text) if sleep_text else None
        meditation_minutes = int(meditation_text) if meditation_text else None

        if amount is not None and amount < 0:
            raise ValueError
        if exercise_minutes is not None and exercise_minutes < 0:
            raise ValueError
        if water_glasses is not None and water_glasses < 0:
            raise ValueError
        if water_goal is not None and water_goal < 0:
            raise ValueError
        if sleep_hours is not None and sleep_hours < 0:
            raise ValueError
        if meditation_minutes is not None and meditation_minutes < 0:
            raise ValueError

    except (ValueError, TypeError):
        flash("Please enter valid non-negative numbers.", "danger")
        return redirect(url_for("module", category=category_key))

    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO entries (
                    user_id, title, content, entry_date, category,
                    amount, location, status, expense_category,
                    study_subject, activity, exercise_minutes,
                    water_glasses, water_goal, sleep_hours,
                    meditation_minutes, meals, health_status,
                    period_start, period_end, flow, symptoms
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                session["user_id"], title, content, entry_date,
                CATEGORIES[category_key], amount, location, status,
                expense_category, study_subject, activity,
                exercise_minutes, water_glasses, water_goal,
                sleep_hours, meditation_minutes, meals, health_status,
                period_start, period_end, flow, symptoms
            ))

        flash("Diary entry saved successfully.", "success")

    except Exception:
        app.logger.exception("Could not save diary entry.")
        flash("Could not save the entry. Please check the Render logs.", "danger")

    return redirect(url_for("module", category=category_key))


@app.route("/edit/<int:entry_id>", methods=["GET", "POST"])
@login_required
def edit(entry_id):
    entry = get_entry(entry_id, session["user_id"])

    if not entry:
        flash("Entry not found.", "danger")
        return redirect(url_for("dashboard"))

    category_key = get_category_key(entry["category"]) or "personal"

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        entry_date = request.form.get("entry_date") or date.today().isoformat()
        location = request.form.get("location", "").strip() or None
        status = request.form.get("status", "").strip() or None
        amount_text = request.form.get("amount", "").strip()

        if not title:
            flash("Title cannot be empty.", "danger")
            return redirect(url_for("edit", entry_id=entry_id))

        try:
            amount = float(amount_text) if amount_text else None
            if amount is not None and amount < 0:
                raise ValueError
        except ValueError:
            flash("Please enter a valid non-negative amount.", "danger")
            return redirect(url_for("edit", entry_id=entry_id))

        with get_db() as conn:
            conn.execute("""
                UPDATE entries
                SET title = %s, content = %s, entry_date = %s,
                    location = %s, status = %s, amount = %s,
                    expense_category = %s, study_subject = %s
                WHERE id = %s AND user_id = %s
            """, (
                title, content, entry_date, location, status, amount,
                request.form.get("expense_category", "").strip() or None,
                request.form.get("study_subject", "").strip() or None,
                entry_id, session["user_id"]
            ))

        flash("Entry updated successfully.", "success")
        return redirect(url_for("module", category=category_key))

    return render_template(
        "edit.html",
        entry=entry,
        category=category_key,
        category_name=CATEGORIES.get(category_key, "Personal Diary")
    )


@app.route("/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete(entry_id):
    entry = get_entry(entry_id, session["user_id"])

    if not entry:
        flash("Entry not found.", "danger")
        return redirect(url_for("dashboard"))

    category_key = get_category_key(entry["category"]) or "personal"

    with get_db() as conn:
        conn.execute("""
            DELETE FROM entries
            WHERE id = %s AND user_id = %s
        """, (entry_id, session["user_id"]))

    flash("Entry deleted successfully.", "success")
    return redirect(url_for("module", category=category_key))


@app.route("/reports")
@login_required
def reports():
    with get_db() as conn:
        total = conn.execute("""
            SELECT COUNT(*) AS total
            FROM entries
            WHERE user_id = %s
        """, (session["user_id"],)).fetchone()["total"]

        category_counts = conn.execute("""
            SELECT category, COUNT(*) AS total
            FROM entries
            WHERE user_id = %s
            GROUP BY category
            ORDER BY category
        """, (session["user_id"],)).fetchall()

        expense_summary = conn.execute("""
            SELECT
                COALESCE(SUM(amount), 0) AS total,
                COALESCE(SUM(amount), 0) AS total_amount,
                0::NUMERIC AS budget
            FROM entries
            WHERE user_id = %s
              AND category = 'Expense Diary'
        """, (session["user_id"],)).fetchone()

    return render_template(
        "reports.html",
        name=session.get("name", "Friend"),
        total_entries=total,
        category_counts=category_counts,
        expense_summary=expense_summary
    )


# Initialise database tables and migrations.
init_db()


if __name__ == "__main__":
    app.run(debug=True)
