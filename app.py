
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


# Four diary modules
CATEGORIES = {
    "health": "Health Diary",
    "expense": "Expense Diary",
    "personal": "Personal Diary",
    "study": "Study Planner",
}


# Accept short keys and full module names in URLs
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
            "DATABASE_URL is missing. "
            "Configure it in your environment."
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
                category TEXT NOT NULL
                    DEFAULT 'Personal Diary',
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

        for column, definition in [
            (
                "user_id",
                "INTEGER REFERENCES users(id) ON DELETE CASCADE"
            ),
            ("category", "TEXT DEFAULT 'Personal Diary'"),
            ("destination", "TEXT"),
            ("expenses", "DOUBLE PRECISION"),
            ("status", "TEXT DEFAULT 'Pending'"),
            ("photo", "TEXT"),
        ]:
            conn.execute(
                f"ALTER TABLE entries ADD COLUMN IF NOT EXISTS "
                f"{column} {definition}"
            )

        # Keep existing records and normalize unknown categories.
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
    """Convert a module key or display name into its short key."""
    return CATEGORY_ALIASES.get(category)


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
    # Supports /module/personal and /module/Personal%20Diary
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
                  )
                ORDER BY entry_date DESC, id DESC
            """, (
                session["user_id"],
                category_name,
                wildcard,
                wildcard
            )).fetchall()
        else:
            entries = conn.execute("""
                SELECT * FROM entries
                WHERE user_id = %s
                  AND category = %s
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
    entry_date = request.form.get("entry_date", "").strip()
    expenses_text = request.form.get("expenses", "").strip()
    status = request.form.get("status", "Pending").strip()

    if not title or not content or not entry_date:
        flash("Please complete the required fields.")
        return redirect(
            url_for("module", category=category_key)
        )

    expenses = None

    if category_key == "expense":
        try:
            expenses = float(expenses_text)
            if expenses < 0:
                raise ValueError
        except (ValueError, TypeError):
            flash("Please enter a valid non-negative expense.")
            return redirect(
                url_for("module", category=category_key)
            )

    if category_key != "study":
        status = (
            "Completed" if status == "Completed" else "Pending"
        )

    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO entries
                    (title, content, entry_date, user_id,
                     category, expenses, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                title,
                content,
                entry_date,
                session["user_id"],
                CATEGORIES[category_key],
                expenses,
                status
            ))
    except (ValueError, TypeError):
        flash("Please enter a valid date and entry details.")
        return redirect(
            url_for("module", category=category_key)
        )

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
            category_key = "personal"

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            entry_date = request.form.get("entry_date", "").strip()
            expenses_text = request.form.get("expenses", "").strip()
            status = request.form.get("status", "Pending").strip()

            if not title or not content or not entry_date:
                flash("Please complete the required fields.")
                return redirect(
                    url_for("edit", entry_id=entry_id)
                )

            expenses = None

            if category_key == "expense":
                try:
                    expenses = float(expenses_text)
                    if expenses < 0:
                        raise ValueError
                except (ValueError, TypeError):
                    flash("Enter a valid non-negative expense.")
                    return redirect(
                        url_for("edit", entry_id=entry_id)
                    )

            if category_key != "study":
                status = (
                    "Completed" if status == "Completed" else "Pending"
                )

            conn.execute("""
                UPDATE entries
                SET title = %s,
                    content = %s,
                    entry_date = %s,
                    expenses = %s,
                    status = %s
                WHERE id = %s AND user_id = %s
            """, (
                title,
                content,
                entry_date,
                expenses,
                status,
                entry_id,
                user_id
            ))

            flash("Entry updated successfully!")
            return redirect(
                url_for("module", category=category_key)
            )

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

        if category_key is None:
            category_key = "personal"

        return redirect(
            url_for("module", category=category_key)
        )

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

        result = conn.execute("""
            SELECT COALESCE(SUM(expenses), 0) AS total
            FROM entries
            WHERE user_id = %s
              AND category = 'Expense Diary'
        """, (user_id,)).fetchone()

    return render_template(
        "reports.html",
        totals=totals,
        expense_total=result["total"]
    )


# Initialize the Neon database when the application starts.
init_db()


if __name__ == "__main__":
    app.run(debug=True)
