
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
import os
import math
from functools import wraps
from datetime import date
import psycopg
from psycopg.rows import dict_row
from psycopg import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

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

EXPENSE_CATEGORIES = {
    "House Rent",
    "Food & Groceries",
    "Transportation",
    "Electricity/Phone/Internet",
    "Health & Personal Care",
    "Shopping & Entertainment",
    "Education",
    "Other Expenses",
    "Savings",
}

HEALTH_ACTIVITIES = {
    "Yoga",
    "Walking",
    "Running",
    "Cycling",
    "Dance",
    "Strength Training",
    "Stretching",
    "Meditation",
    "Sports",
    "Other Exercise",
}

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
    "activity_type",
    "daily_water_goal",
    "energy_level",
]


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

        conn.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT"
        )

        columns = [
            ("user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE"),
            ("category", "TEXT DEFAULT 'Personal Diary'"),
            ("destination", "TEXT"),
            ("expenses", "DOUBLE PRECISION"),
            ("status", "TEXT DEFAULT 'Pending'"),
            ("photo", "TEXT"),
            ("mood", "TEXT"),
            ("gratitude", "TEXT"),
            ("water_intake", "DOUBLE PRECISION"),
            ("sleep_hours", "DOUBLE PRECISION"),
            ("exercise_minutes", "INTEGER"),
            ("meditation_minutes", "INTEGER"),
            ("meals", "TEXT"),
            ("period_start", "DATE"),
            ("period_end", "DATE"),
            ("flow_level", "TEXT"),
            ("symptoms", "TEXT"),
            ("subject", "TEXT"),
            ("deadline", "DATE"),
            ("priority", "TEXT DEFAULT 'Medium'"),
            ("planned_hours", "DOUBLE PRECISION"),
            ("actual_hours", "DOUBLE PRECISION"),
            ("expense_category", "TEXT"),
            ("monthly_budget", "DOUBLE PRECISION"),
            ("activity_type", "TEXT"),
            ("daily_water_goal", "DOUBLE PRECISION"),
            ("energy_level", "TEXT"),
        ]

        for column, definition in columns:
            conn.execute(
                f"ALTER TABLE entries ADD COLUMN IF NOT EXISTS "
                f"{column} {definition}"
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS monthly_budgets (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id)
                    ON DELETE CASCADE,
                month_start DATE NOT NULL,
                amount DOUBLE PRECISION NOT NULL DEFAULT 0,
                UNIQUE(user_id, month_start)
            )
        """)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def get_category_key(category):
    return CATEGORY_ALIASES.get(category)


def optional_text(field):
    return request.form.get(field, "").strip() or None


def optional_number(field, minimum=0, maximum=None):
    raw = request.form.get(field, "").strip()

    if not raw:
        return None

    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{field} must be a valid number.")

    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{field} must be at least {minimum}.")

    if maximum is not None and value > maximum:
        raise ValueError(f"{field} must not exceed {maximum}.")

    return value


def optional_integer(field, minimum=0, maximum=None):
    value = optional_number(field, minimum, maximum)

    if value is not None and not value.is_integer():
        raise ValueError(f"{field} must be a whole number.")

    return int(value) if value is not None else None


def optional_date(field):
    raw = request.form.get(field, "").strip()
    return date.fromisoformat(raw) if raw else None


def save_monthly_budget(conn, user_id, entry_day, amount):
    if amount is None:
        return

    conn.execute("""
        INSERT INTO monthly_budgets (user_id, month_start, amount)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, month_start)
        DO UPDATE SET amount = EXCLUDED.amount
    """, (
        user_id,
        entry_day.replace(day=1),
        amount
    ))


def collect_extra_fields(key):
    data = {column: None for column in EXTRA_COLUMNS}
    data["priority"] = "Medium"

    if key == "personal":
        data["mood"] = optional_text("mood")
        data["gratitude"] = optional_text("gratitude")

    elif key == "health":
        data["water_intake"] = optional_number(
            "water_intake", 0, 20
        )
        data["daily_water_goal"] = optional_number(
            "daily_water_goal", 0.1, 20
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
        data["activity_type"] = optional_text("activity_type")

        if (
            data["activity_type"]
            and data["activity_type"] not in HEALTH_ACTIVITIES
        ):
            raise ValueError("Please select a valid activity.")

        if (
            data["flow_level"]
            and data["flow_level"] not in {"Light", "Medium", "Heavy"}
        ):
            raise ValueError("Please select a valid period flow.")

        if (
            data["period_start"]
            and data["period_end"]
            and data["period_end"] < data["period_start"]
        ):
            raise ValueError(
                "Period end cannot be before period start."
            )

    elif key == "study":
        data["subject"] = optional_text("subject")
        data["deadline"] = optional_date("deadline")
        data["priority"] = (
            request.form.get("priority", "Medium").strip() or "Medium"
        )

        if data["priority"] not in {"Low", "Medium", "High"}:
            raise ValueError("Invalid task priority.")

        data["planned_hours"] = optional_number(
            "planned_hours", 0, 24
        )
        data["actual_hours"] = optional_number(
            "actual_hours", 0, 24
        )

    elif key == "expense":
        data["expenses"] = optional_number("expenses", 0.01)
        data["expense_category"] = optional_text("expense_category")
        data["monthly_budget"] = optional_number(
            "monthly_budget", 0
        )

        if data["expenses"] is None:
            raise ValueError("Please enter the expense amount.")

        if data["expense_category"] not in EXPENSE_CATEGORIES:
            raise ValueError("Please select a valid expense category.")

    return data


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

        except IntegrityError:
            flash("This email is already registered. Please log in.")
            return render_template("register.html")

        session.clear()
        session.update(
            user_id=user["id"],
            name=name,
            email=email
        )
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
            session.update(
                user_id=user["id"],
                email=user["email"],
                name=user["name"] or email.split("@")[0]
            )
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
    key = get_category_key(category)

    if key is None:
        return "Module not found", 404

    category_name = CATEGORIES[key]
    search = request.args.get("search", "").strip()
    selected_month = request.args.get(
        "month", date.today().strftime("%Y-%m")
    )

    try:
        month_start = date.fromisoformat(selected_month + "-01")
    except ValueError:
        month_start = date.today().replace(day=1)
        selected_month = month_start.strftime("%Y-%m")

    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(
            month_start.year, month_start.month + 1, 1
        )

    user_id = session["user_id"]

    # Always define both summaries before rendering the template.
    # This ensures module.html can safely access them for every module.
    expense_summary = {
        "spent": 0.0,
        "budget": 0.0,
        "remaining": 0.0,
        "categories": []
    }

    health_summary = {
        "average_water": 0.0,
        "average_sleep": 0.0,
        "exercise_total": 0,
        "meditation_total": 0,
        "period_records": 0,
        "activity_records": 0,
        "activities": [],
        "water_days": []
    }

    wildcard = f"%{search}%"

    with get_db() as conn:
        if key in {"expense", "health"}:
            entries = conn.execute("""
                SELECT *
                FROM entries
                WHERE user_id = %s
                  AND category = %s
                  AND entry_date >= %s
                  AND entry_date < %s
                  AND (
                    %s = ''
                    OR title ILIKE %s
                    OR content ILIKE %s
                    OR COALESCE(activity_type, '') ILIKE %s
                    OR COALESCE(symptoms, '') ILIKE %s
                    OR COALESCE(expense_category, '') ILIKE %s
                  )
                ORDER BY entry_date DESC, id DESC
            """, (
                user_id, category_name,
                month_start, next_month,
                search, wildcard, wildcard,
                wildcard, wildcard, wildcard
            )).fetchall()
        else:
            entries = conn.execute("""
                SELECT *
                FROM entries
                WHERE user_id = %s
                  AND category = %s
                  AND (
                    %s = ''
                    OR title ILIKE %s
                    OR content ILIKE %s
                    OR COALESCE(subject, '') ILIKE %s
                    OR COALESCE(mood, '') ILIKE %s
                  )
                ORDER BY entry_date DESC, id DESC
            """, (
                user_id, category_name,
                search, wildcard, wildcard,
                wildcard, wildcard
            )).fetchall()

        if key == "expense":
            spent_row = conn.execute("""
                SELECT COALESCE(SUM(expenses), 0) AS spent
                FROM entries
                WHERE user_id = %s
                  AND category = %s
                  AND entry_date >= %s
                  AND entry_date < %s
            """, (
                user_id, category_name,
                month_start, next_month
            )).fetchone()

            budget_row = conn.execute("""
                SELECT amount
                FROM monthly_budgets
                WHERE user_id = %s AND month_start = %s
            """, (user_id, month_start)).fetchone()

            if budget_row:
                budget = float(budget_row["amount"] or 0)
            else:
                old_budget = conn.execute("""
                    SELECT COALESCE(MAX(monthly_budget), 0) AS budget
                    FROM entries
                    WHERE user_id = %s
                      AND category = %s
                      AND entry_date >= %s
                      AND entry_date < %s
                """, (
                    user_id, category_name,
                    month_start, next_month
                )).fetchone()
                budget = float(old_budget["budget"] or 0)

            rows = conn.execute("""
                SELECT
                    COALESCE(
                        expense_category, 'Other Expenses'
                    ) AS expense_category,
                    COALESCE(SUM(expenses), 0) AS total
                FROM entries
                WHERE user_id = %s
                  AND category = %s
                  AND entry_date >= %s
                  AND entry_date < %s
                GROUP BY COALESCE(
                    expense_category, 'Other Expenses'
                )
                ORDER BY total DESC
            """, (
                user_id, category_name,
                month_start, next_month
            )).fetchall()

            spent = float(spent_row["spent"] or 0)

            expense_summary = {
                "spent": spent,
                "budget": budget,
                "remaining": budget - spent,
                "categories": [
                    {
                        "expense_category": row["expense_category"],
                        "total": float(row["total"] or 0)
                    }
                    for row in rows
                ]
            }

        elif key == "health":
            health_row = conn.execute("""
                SELECT
                    COALESCE(AVG(water_intake), 0)
                        AS average_water,
                    COALESCE(AVG(sleep_hours), 0)
                        AS average_sleep,
                    COALESCE(SUM(exercise_minutes), 0)
                        AS exercise_total,
                    COALESCE(SUM(meditation_minutes), 0)
                        AS meditation_total,
                    COUNT(*) FILTER (
                        WHERE period_start IS NOT NULL
                    ) AS period_records,
                    COUNT(*) FILTER (
                        WHERE activity_type IS NOT NULL
                    ) AS activity_records
                FROM entries
                WHERE user_id = %s
                  AND category = %s
                  AND entry_date >= %s
                  AND entry_date < %s
            """, (
                user_id, category_name,
                month_start, next_month
            )).fetchone()

            activity_rows = conn.execute("""
                SELECT
                    activity_type,
                    COALESCE(SUM(exercise_minutes), 0) AS minutes
                FROM entries
                WHERE user_id = %s
                  AND category = %s
                  AND entry_date >= %s
                  AND entry_date < %s
                  AND activity_type IS NOT NULL
                GROUP BY activity_type
                ORDER BY minutes DESC
            """, (
                user_id, category_name,
                month_start, next_month
            )).fetchall()

            daily_water_rows = conn.execute("""
                SELECT
                    entry_date,
                    COALESCE(SUM(water_intake), 0) AS water
                FROM entries
                WHERE user_id = %s
                  AND category = %s
                  AND entry_date >= %s
                  AND entry_date < %s
                  AND water_intake IS NOT NULL
                GROUP BY entry_date
                ORDER BY entry_date
            """, (
                user_id, category_name,
                month_start, next_month
            )).fetchall()

            health_summary = {
                "average_water": float(
                    health_row["average_water"] or 0
                ),
                "average_sleep": float(
                    health_row["average_sleep"] or 0
                ),
                "exercise_total": int(
                    health_row["exercise_total"] or 0
                ),
                "meditation_total": int(
                    health_row["meditation_total"] or 0
                ),
                "period_records": int(
                    health_row["period_records"] or 0
                ),
                "activity_records": int(
                    health_row["activity_records"] or 0
                ),
                "activities": [
                    {
                        "activity_type": row["activity_type"],
                        "minutes": int(row["minutes"] or 0)
                    }
                    for row in activity_rows
                ],
                "water_days": [
                    {
                        "day": row["entry_date"].strftime("%d %b"),
                        "water": float(row["water"] or 0)
                    }
                    for row in daily_water_rows
                ]
            }

    # Pass health_summary on every render, even for non-health modules.
    return render_template(
        "module.html",
        category=key,
        category_name=category_name,
        entries=entries,
        search=search,
        today=date.today().isoformat(),
        expense_summary=expense_summary,
        health_summary=health_summary,
        selected_month=selected_month
    )


@app.route("/add/<path:category>", methods=["POST"])
@login_required
def add(category):
    key = get_category_key(category)

    if key is None:
        return "Module not found", 404

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    date_text = request.form.get("entry_date", "").strip()
    status = request.form.get("status", "Pending").strip()

    if key == "expense":
        title = "Expense"
        if not content:
            content = request.form.get(
                "expense_description", ""
            ).strip()
        if not content:
            content = (
                request.form.get("title", "").strip()
                or "Expense entry"
            )
    elif not title or not content:
        flash("Please complete the required fields.")
        return redirect(url_for("module", category=key))

    if not date_text:
        flash("Please select a date.")
        return redirect(url_for("module", category=key))

    if key == "study":
        if status not in {"Pending", "In Progress", "Completed"}:
            status = "Pending"
    elif key == "health":
        status = "Completed" if status == "Completed" else "Pending"
    else:
        status = "Pending"

    try:
        entry_day = date.fromisoformat(date_text)
        extra = collect_extra_fields(key)

        columns = [
            "title", "content", "entry_date",
            "user_id", "category", "status"
        ] + EXTRA_COLUMNS

        values = [
            title, content, entry_day,
            session["user_id"], CATEGORIES[key], status
        ] + [extra[column] for column in EXTRA_COLUMNS]

        placeholders = ", ".join(["%s"] * len(columns))

        with get_db() as conn:
            conn.execute(
                f"INSERT INTO entries ({', '.join(columns)}) "
                f"VALUES ({placeholders})",
                values
            )

            if key == "expense":
                save_monthly_budget(
                    conn,
                    session["user_id"],
                    entry_day,
                    extra["monthly_budget"]
                )

    except (ValueError, TypeError) as error:
        flash(f"Please check the information entered. {error}")
        return redirect(url_for("module", category=key))

    flash("Entry saved successfully!")
    return redirect(url_for("module", category=key))


@app.route("/edit/<int:entry_id>", methods=["GET", "POST"])
@login_required
def edit(entry_id):
    user_id = session["user_id"]

    with get_db() as conn:
        entry = conn.execute("""
            SELECT *
            FROM entries
            WHERE id = %s AND user_id = %s
        """, (entry_id, user_id)).fetchone()

    if not entry:
        return "Entry not found", 404

    key = get_category_key(entry["category"])

    if key is None:
        return "Module not found", 404

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        date_text = request.form.get("entry_date", "").strip()
        status = request.form.get("status", "Pending").strip()

        if key == "expense":
            title = "Expense"
        elif not title or not content:
            flash("Please complete the required fields.")
            return redirect(url_for("edit", entry_id=entry_id))

        if not date_text:
            flash("Please select a date.")
            return redirect(url_for("edit", entry_id=entry_id))

        if key == "study":
            if status not in {"Pending", "In Progress", "Completed"}:
                status = "Pending"
        elif key == "health":
            status = "Completed" if status == "Completed" else "Pending"
        else:
            status = "Pending"

        try:
            entry_day = date.fromisoformat(date_text)
            extra = collect_extra_fields(key)

            for column in EXTRA_COLUMNS:
                if (
                    column not in request.form
                    and entry.get(column) is not None
                ):
                    extra[column] = entry[column]

            assignments = [
                "title=%s",
                "content=%s",
                "entry_date=%s",
                "status=%s"
            ] + [f"{column}=%s" for column in EXTRA_COLUMNS]

            values = [
                title, content, entry_day, status
            ] + [extra[column] for column in EXTRA_COLUMNS]

            values.extend([entry_id, user_id])

            with get_db() as conn:
                conn.execute(
                    "UPDATE entries SET "
                    + ", ".join(assignments)
                    + " WHERE id=%s AND user_id=%s",
                    values
                )

                if key == "expense":
                    save_monthly_budget(
                        conn,
                        user_id,
                        entry_day,
                        extra["monthly_budget"]
                    )

        except (ValueError, TypeError) as error:
            flash(f"Please check the information entered. {error}")
            return redirect(url_for("edit", entry_id=entry_id))

        flash("Entry updated successfully!")
        return redirect(url_for("module", category=key))

    return render_template("edit.html", entry=entry)


@app.route("/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete(entry_id):
    user_id = session["user_id"]

    with get_db() as conn:
        entry = conn.execute("""
            SELECT category
            FROM entries
            WHERE id = %s AND user_id = %s
        """, (entry_id, user_id)).fetchone()

        if entry:
            conn.execute("""
                DELETE FROM entries
                WHERE id = %s AND user_id = %s
            """, (entry_id, user_id))

    if entry:
        key = get_category_key(entry["category"])
        if key:
            return redirect(url_for("module", category=key))

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

        expense = conn.execute("""
            SELECT COALESCE(SUM(expenses), 0) AS total
            FROM entries
            WHERE user_id = %s
              AND category = 'Expense Diary'
        """, (user_id,)).fetchone()

        study = conn.execute("""
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

        monthly = conn.execute("""
            SELECT
                TO_CHAR(entry_date, 'YYYY-MM') AS month,
                COALESCE(SUM(expenses), 0) AS total
            FROM entries
            WHERE user_id = %s
              AND category = 'Expense Diary'
            GROUP BY TO_CHAR(entry_date, 'YYYY-MM')
            ORDER BY month
        """, (user_id,)).fetchall()

        subjects = conn.execute("""
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
        expense_total=expense["total"],
        study_actual_hours=study["actual_hours"],
        study_planned_hours=study["planned_hours"],
        completed_tasks=study["completed_tasks"],
        total_tasks=study["total_tasks"],
        monthly_expenses=monthly,
        subject_hours=subjects
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
