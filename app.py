
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
import os
from functools import wraps
from datetime import date
import psycopg
from psycopg.rows import dict_row
from psycopg import IntegrityError
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY", "digital-diary-local-key"
)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://", "postgresql://", 1
    )

CATEGORIES = {
    "health": "Health Diary",
    "expense": "Expense Diary",
    "personal": "Personal Diary",
    "study": "Study Planner",
}

CATEGORY_ALIASES = {
    "health": "health",
    "Health Diary": "health",
    "expense": "expense",
    "Expense Diary": "expense",
    "personal": "personal",
    "Personal Diary": "personal",
    "study": "study",
    "Study Planner": "study",
}


def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Configure it in your environment."
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=15
    )


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                entry_date DATE NOT NULL,
                user_id INTEGER REFERENCES users(id)
                    ON DELETE CASCADE,
                category TEXT NOT NULL DEFAULT 'Personal Diary',
                destination TEXT,
                expenses DOUBLE PRECISION,
                status TEXT DEFAULT 'Pending',
                photo TEXT
            )
        """)

        conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS name TEXT
        """)

        # Existing columns: retain old data and add only missing columns.
        columns = [
            ("user_id",
             "INTEGER REFERENCES users(id) ON DELETE CASCADE"),
            ("category", "TEXT DEFAULT 'Personal Diary'"),
            ("destination", "TEXT"),
            ("expenses", "DOUBLE PRECISION"),
            ("status", "TEXT DEFAULT 'Pending'"),
            ("photo", "TEXT"),

            # Personal Diary
            ("mood", "TEXT"),
            ("gratitude", "TEXT"),

            # Health Diary
            ("water_intake", "DOUBLE PRECISION"),
            ("sleep_hours", "DOUBLE PRECISION"),
            ("exercise_minutes", "INTEGER"),
            ("meditation_minutes", "INTEGER"),
            ("meals", "TEXT"),
            ("period_start", "DATE"),
            ("period_end", "DATE"),
            ("flow_level", "TEXT"),
            ("symptoms", "TEXT"),

            # Study Planner
            ("subject", "TEXT"),
            ("deadline", "DATE"),
            ("priority", "TEXT DEFAULT 'Medium'"),
            ("planned_hours", "DOUBLE PRECISION"),
            ("actual_hours", "DOUBLE PRECISION"),

            # Expense Diary
            ("expense_category", "TEXT"),
            ("monthly_budget", "DOUBLE PRECISION"),
        ]

        for column, definition in columns:
            conn.execute(
                f"ALTER TABLE entries ADD COLUMN IF NOT EXISTS "
                f"{column} {definition}"
            )

        # Keep existing records; normalize unknown categories.
        conn.execute("""
            UPDATE entries
            SET category = 'Personal Diary'
            WHERE category IS NULL
               OR category NOT IN (
                   'Health Diary',
                   'Expense Diary',
                   'Personal Diary',
                   'Study Planner'
               )
        """)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def get_category_key(category):
    return CATEGORY_ALIASES.get(category)


def optional_text(field):
    return request.form.get(field, "").strip() or None


def optional_number(field, minimum=0, maximum=None):
    """Return a validated optional number, or raise ValueError."""
    raw = request.form.get(field, "").strip()

    if not raw:
        return None

    value = float(raw)

    if value < minimum:
        raise ValueError(f"{field} cannot be negative.")

    if maximum is not None and value > maximum:
        raise ValueError(f"{field} exceeds the allowed maximum.")

    return value


def optional_integer(field, minimum=0, maximum=None):
    value = optional_number(field, minimum, maximum)

    if value is None:
        return None

    if not value.is_integer():
        raise ValueError(f"{field} must be a whole number.")

    return int(value)


def optional_date(field):
    raw = request.form.get(field, "").strip()

    if not raw:
        return None

    return date.fromisoformat(raw)


def collect_extra_fields(category_key):
    """Collect module-specific fields from a form."""
    data = {
        "destination": None,
        "expenses": None,
        "mood": None,
        "gratitude": None,
        "water_intake": None,
        "sleep_hours": None,
        "exercise_minutes": None,
        "meditation_minutes": None,
        "meals": None,
        "period_start": None,
        "period_end": None,
        "flow_level": None,
        "symptoms": None,
        "subject": None,
        "deadline": None,
        "priority": "Medium",
        "planned_hours": None,
        "actual_hours": None,
        "expense_category": None,
        "monthly_budget": None,
    }

    if category_key == "personal":
        data["mood"] = optional_text("mood")
        data["gratitude"] = optional_text("gratitude")

    elif category_key == "health":
        data["water_intake"] = optional_number(
            "water_intake", 0, 20
        )
        data["sleep_hours"] = optional_number(
            "sleep_hours", 0, 24
        )
        data["exercise_minutes"] = optional_integer(
            "exercise_minutes", 0, 1440
        )
        data["meditation_minutes"] = optional_integer(
            "meditation_minutes", 0, 1440
        )
        data["meals"] = optional_text("meals")
        data["period_start"] = optional_date("period_start")
        data["period_end"] = optional_date("period_end")
        data["flow_level"] = optional_text("flow_level")
        data["symptoms"] = optional_text("symptoms")

        allowed_flow = {"Light", "Medium", "Heavy"}
        if data["flow_level"] and data["flow_level"] not in allowed_flow:
            raise ValueError("Please select a valid period flow level.")

        if (
            data["period_start"]
            and data["period_end"]
            and data["period_end"] < data["period_start"]
        ):
            raise ValueError("Period end date cannot be before start date.")

    elif category_key == "study":
        data["subject"] = optional_text("subject")
        data["deadline"] = optional_date("deadline")
        data["priority"] = request.form.get(
            "priority", "Medium"
        ).strip() or "Medium"

        if data["priority"] not in {"Low", "Medium", "High"}:
            raise ValueError("Please select a valid task priority.")

        data["planned_hours"] = optional_number(
            "planned_hours", 0, 24
        )
        data["actual_hours"] = optional_number(
            "actual_hours", 0, 24
        )

    elif category_key == "expense":
        data["expenses"] = optional_number("expenses", 0)
        data["expense_category"] = optional_text("expense_category")
        data["monthly_budget"] = optional_number("monthly_budget", 0)

        allowed_categories = {
            "House Rent",
            "Food & Groceries",
            "Transportation",
            "Electricity/Phone/Internet",
            "Health & Personal Care",
            "Shopping & Entertainment",
            "Other Expenses",
            "Savings",
        }

        if data["expense_category"] and (
            data["expense_category"] not in allowed_categories
        ):
            raise ValueError("Please select a valid expense category.")

        if data["expenses"] is None:
            raise ValueError("Please enter the expense amount.")

    return data


EXTRA_COLUMNS = [
    "destination",
    "expenses",
    "mood",
    "gratitude",
    "water_intake",
    "sleep_hours",
    "exercise_minutes",
    "meditation_minutes",
    "meals",
    "period_start",
    "period_end",
    "flow_level",
    "symptoms",
    "subject",
    "deadline",
    "priority",
    "planned_hours",
    "actual_hours",
    "expense_category",
    "monthly_budget",
]


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters.")
            return render_template("register.html")

        try:
            with get_db() as conn:
                user = conn.execute("""
                    INSERT INTO users (name, email, password_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id
                """, (
                    name,
                    email,
                    generate_password_hash(password)
                )).fetchone()

                user_id = user["id"]

        except IntegrityError:
            flash("This email is already registered. Please log in.")
            return render_template("register.html")

        session.clear()
        session["user_id"] = user_id
        session["name"] = name
        session["email"] = email

        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE email = %s",
                (email,)
            ).fetchone()

        if user and check_password_hash(
            user["password_hash"], password
        ):
            session.clear()
            session["user_id"] = user["id"]
            session["email"] = user["email"]
            session["name"] = user["name"] or email.split("@")[0]

            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    with get_db() as conn:
        result = conn.execute("""
            SELECT COUNT(*) AS total
            FROM entries
            WHERE user_id = %s
        """, (session["user_id"],)).fetchone()

    return render_template(
        "dashboard.html",
        name=session.get("name", "Friend"),
        total_entries=result["total"]
    )


@app.route("/module/<path:category>")
@login_required
def module(category):
    category_key = get_category_key(category)

    if category_key is None:
        return "Module not found", 404

    category_name = CATEGORIES[category_key]
    search = request.args.get("search", "").strip()

    with get_db() as conn:
        if search:
            wildcard = f"%{search}%"

            entries = conn.execute("""
                SELECT * FROM entries
                WHERE user_id = %s
                  AND category = %s
                  AND (
                      title ILIKE %s
                      OR content ILIKE %s
                      OR COALESCE(subject, '') ILIKE %s
                      OR COALESCE(expense_category, '') ILIKE %s
                      OR COALESCE(mood, '') ILIKE %s
                  )
                ORDER BY entry_date DESC, id DESC
            """, (
                session["user_id"],
                category_name,
                wildcard,
                wildcard,
                wildcard,
                wildcard,
                wildcard
            )).fetchall()
        else:
            entries = conn.execute("""
                SELECT * FROM entries
                WHERE user_id = %s AND category = %s
                ORDER BY entry_date DESC, id DESC
            """, (
                session["user_id"],
                category_name
            )).fetchall()

    return render_template(
        "module.html",
        category=category_key,
        category_name=category_name,
        entries=entries,
        search=search,
        today=date.today().isoformat()
    )


@app.route("/add/<path:category>", methods=["POST"])
@login_required
def add(category):
    category_key = get_category_key(category)

    if category_key is None:
        return "Module not found", 404

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    entry_date_text = request.form.get("entry_date", "").strip()
    status = request.form.get("status", "Pending").strip()

    if not title or not content or not entry_date_text:
        flash("Please complete the required fields.")
        return redirect(url_for("module", category=category_key))

    if category_key == "study":
        if status not in {"Pending", "In Progress", "Completed"}:
            status = "Pending"
    elif category_key == "health":
        status = (
            "Completed" if status == "Completed" else "Pending"
        )
    else:
        status = "Pending"

    try:
        entry_date = date.fromisoformat(entry_date_text)
        extra = collect_extra_fields(category_key)

        columns = [
            "title", "content", "entry_date", "user_id",
            "category", "status"
        ] + EXTRA_COLUMNS

        values = [
            title, content, entry_date, session["user_id"],
            CATEGORIES[category_key], status
        ] + [extra[column] for column in EXTRA_COLUMNS]

        placeholders = ", ".join(["%s"] * len(columns))
        column_sql = ", ".join(columns)

        with get_db() as conn:
            conn.execute(
                f"INSERT INTO entries ({column_sql}) "
                f"VALUES ({placeholders})",
                values
            )

    except (ValueError, TypeError) as error:
        flash(f"Please check the information entered. {error}")
        return redirect(url_for("module", category=category_key))

    flash("Entry saved successfully!")
    return redirect(url_for("module", category=category_key))


@app.route("/edit/<int:entry_id>", methods=["GET", "POST"])
@login_required
def edit(entry_id):
    user_id = session["user_id"]

    with get_db() as conn:
        entry = conn.execute("""
            SELECT * FROM entries
            WHERE id = %s AND user_id = %s
        """, (entry_id, user_id)).fetchone()

        if entry is None:
            return "Entry not found", 404

        category_key = get_category_key(entry["category"])

        if category_key is None:
            return "Module not found", 404

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            entry_date_text = request.form.get("entry_date", "").strip()
            status = request.form.get("status", "Pending").strip()

            if not title or not content or not entry_date_text:
                flash("Please complete the required fields.")
                return redirect(url_for("edit", entry_id=entry_id))

            if category_key == "study":
                if status not in {"Pending", "In Progress", "Completed"}:
                    status = "Pending"
            elif category_key == "health":
                status = (
                    "Completed" if status == "Completed" else "Pending"
                )
            else:
                status = "Pending"

            try:
                entry_date = date.fromisoformat(entry_date_text)
                extra = collect_extra_fields(category_key)

                assignments = [
                    "title = %s",
                    "content = %s",
                    "entry_date = %s",
                    "status = %s",
                ] + [f"{column} = %s" for column in EXTRA_COLUMNS]

                values = [
                    title, content, entry_date, status
                ] + [extra[column] for column in EXTRA_COLUMNS]

                values.extend([entry_id, user_id])

                with get_db() as update_conn:
                    update_conn.execute(
                        "UPDATE entries SET "
                        + ", ".join(assignments)
                        + " WHERE id = %s AND user_id = %s",
                        values
                    )

            except (ValueError, TypeError) as error:
                flash(f"Please check the information entered. {error}")
                return redirect(url_for("edit", entry_id=entry_id))

            flash("Entry updated successfully!")
            return redirect(url_for("module", category=category_key))

    return render_template("edit.html", entry=entry)


@app.route("/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete(entry_id):
    user_id = session["user_id"]

    with get_db() as conn:
        entry = conn.execute("""
            SELECT category FROM entries
            WHERE id = %s AND user_id = %s
        """, (entry_id, user_id)).fetchone()

        if entry:
            conn.execute("""
                DELETE FROM entries
                WHERE id = %s AND user_id = %s
            """, (entry_id, user_id))

    if entry:
        category_key = get_category_key(entry["category"])

        if category_key:
            return redirect(url_for("module", category=category_key))

    return redirect(url_for("dashboard"))


@app.route("/reports")
@login_required
def reports():
    user_id = session["user_id"]

    with get_db() as conn:
        totals = conn.execute("""
            SELECT category, COUNT(*) AS total
            FROM entries
            WHERE user_id = %s
            GROUP BY category
            ORDER BY category
        """, (user_id,)).fetchall()

        expense_result = conn.execute("""
            SELECT COALESCE(SUM(expenses), 0) AS total
            FROM entries
            WHERE user_id = %s
              AND category = 'Expense Diary'
        """, (user_id,)).fetchone()

        study_result = conn.execute("""
            SELECT
                COALESCE(SUM(actual_hours), 0) AS actual_hours,
                COALESCE(SUM(planned_hours), 0) AS planned_hours,
                COUNT(*) FILTER (
                    WHERE status = 'Completed'
                ) AS completed_tasks,
                COUNT(*) AS total_tasks
            FROM entries
            WHERE user_id = %s
              AND category = 'Study Planner'
        """, (user_id,)).fetchone()

        monthly_expenses = conn.execute("""
            SELECT
                TO_CHAR(entry_date, 'YYYY-MM') AS month,
                COALESCE(SUM(expenses), 0) AS total
            FROM entries
            WHERE user_id = %s
              AND category = 'Expense Diary'
            GROUP BY TO_CHAR(entry_date, 'YYYY-MM')
            ORDER BY month
        """, (user_id,)).fetchall()

        subject_hours = conn.execute("""
            SELECT
                COALESCE(subject, 'Unspecified') AS subject,
                COALESCE(SUM(actual_hours), 0) AS hours
            FROM entries
            WHERE user_id = %s
              AND category = 'Study Planner'
            GROUP BY subject
            ORDER BY subject
        """, (user_id,)).fetchall()

    return render_template(
        "reports.html",
        totals=totals,
        expense_total=expense_result["total"],
        study_actual_hours=study_result["actual_hours"],
        study_planned_hours=study_result["planned_hours"],
        completed_tasks=study_result["completed_tasks"],
        total_tasks=study_result["total_tasks"],
        monthly_expenses=monthly_expenses,
        subject_hours=subject_hours
    )


# Initialize the Neon database when the application starts.
init_db()


if __name__ == "__main__":
    app.run(debug=True)
