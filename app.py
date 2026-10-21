from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
import sqlite3
from functools import wraps
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
import os

app.secret_key = os.environ.get("SECRET_KEY", "digital-diary-local-key")
DATABASE = "diary.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            entry_date TEXT NOT NULL
        )
    """)

    # Add columns safely to the existing database
    user_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(users)")
    }
    if "name" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN name TEXT")

    entry_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(entries)")
    }

    for column, definition in [
        ("user_id", "INTEGER"),
        ("category", "TEXT DEFAULT 'Personal Diary'"),
        ("destination", "TEXT"),
        ("expenses", "REAL"),
        ("status", "TEXT DEFAULT 'Pending'"),
        ("photo", "TEXT"),
    ]:
        if column not in entry_columns:
            conn.execute(
                f"ALTER TABLE entries ADD COLUMN {column} {definition}"
            )

    conn.commit()
    conn.close()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


CATEGORIES = {
    "personal": "Personal Diary",
    "travel": "Travel Diary",
    "expense": "Expense Diary",
    "study": "Study Planner",
    "health": "Health Diary",
    "activity": "Daily Activity Diary",
}


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

        conn = get_db()

        try:
            cursor = conn.execute("""
                INSERT INTO users (name, email, password_hash)
                VALUES (?, ?, ?)
            """, (name, email, generate_password_hash(password)))

            user_id = cursor.lastrowid

            count = conn.execute(
                "SELECT COUNT(*) AS total FROM users"
            ).fetchone()["total"]

            if count == 1:
                conn.execute(
                    "UPDATE entries SET user_id = ? WHERE user_id IS NULL",
                    (user_id,)
                )

            conn.commit()
            conn.close()

            session.clear()
            session["user_id"] = user_id
            session["name"] = name
            session["email"] = email

            return redirect(url_for("dashboard"))

        except sqlite3.IntegrityError:
            conn.close()
            flash("This email is already registered. Please log in.")
            return render_template("register.html")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
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
    # Keep the existing home route for older links.
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    user_id = session["user_id"]

    total_entries = conn.execute("""
        SELECT COUNT(*) AS total
        FROM entries
        WHERE user_id = ?
    """, (user_id,)).fetchone()["total"]

    conn.close()

    return render_template(
        "dashboard.html",
        name=session.get("name", "Friend"),
        total_entries=total_entries
    )


@app.route("/module/<category>")
@login_required
def module(category):
    if category not in CATEGORIES:
        return "Module not found", 404

    search = request.args.get("search", "").strip()
    category_name = CATEGORIES[category]

    conn = get_db()

    if search:
        wildcard = f"%{search}%"
        entries = conn.execute("""
            SELECT * FROM entries
            WHERE user_id = ?
              AND category = ?
              AND (title LIKE ? OR content LIKE ? OR destination LIKE ?)
            ORDER BY entry_date DESC, id DESC
        """, (
            session["user_id"], category_name,
            wildcard, wildcard, wildcard
        )).fetchall()
    else:
        entries = conn.execute("""
            SELECT * FROM entries
            WHERE user_id = ? AND category = ?
            ORDER BY entry_date DESC, id DESC
        """, (session["user_id"], category_name)).fetchall()

    conn.close()

    return render_template(
        "module.html",
        category=category,
        category_name=category_name,
        entries=entries,
        search=search,
        today=date.today().isoformat()
    )


@app.route("/add/<category>", methods=["POST"])
@login_required
def add(category):
    if category not in CATEGORIES:
        return "Module not found", 404

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    entry_date = request.form.get("entry_date", "").strip()
    destination = request.form.get("destination", "").strip()
    expenses_text = request.form.get("expenses", "").strip()
    status = request.form.get("status", "Pending").strip()

    if not title or not content or not entry_date:
        flash("Please complete the required fields.")
        return redirect(url_for("module", category=category))

    expenses = None

    if category == "expense" or (category == "travel" and expenses_text):
        try:
            expenses = float(expenses_text)
            if expenses < 0:
                raise ValueError
        except ValueError:
            flash("Please enter a valid non-negative expense.")
            return redirect(url_for("module", category=category))

    if category == "travel" and not destination:
        flash("Please enter your destination.")
        return redirect(url_for("module", category=category))

    conn = get_db()
    conn.execute("""
        INSERT INTO entries
        (title, content, entry_date, user_id, category,
         destination, expenses, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        title,
        content,
        entry_date,
        session["user_id"],
        CATEGORIES[category],
        destination or None,
        expenses,
        status
    ))
    conn.commit()
    conn.close()

    flash("Entry saved successfully!")
    return redirect(url_for("module", category=category))


@app.route("/edit/<int:entry_id>", methods=["GET", "POST"])
@login_required
def edit(entry_id):
    conn = get_db()
    user_id = session["user_id"]

    entry = conn.execute("""
        SELECT * FROM entries
        WHERE id = ? AND user_id = ?
    """, (entry_id, user_id)).fetchone()

    if entry is None:
        conn.close()
        return "Entry not found", 404

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        entry_date = request.form.get("entry_date", "").strip()
        destination = request.form.get("destination", "").strip()
        expenses_text = request.form.get("expenses", "").strip()
        status = request.form.get("status", "Pending").strip()

        if not title or not content or not entry_date:
            conn.close()
            flash("Please complete the required fields.")
            return redirect(url_for("edit", entry_id=entry_id))

        expenses = None
        if expenses_text:
            try:
                expenses = float(expenses_text)
                if expenses < 0:
                    raise ValueError
            except ValueError:
                conn.close()
                flash("Enter a valid non-negative expense.")
                return redirect(url_for("edit", entry_id=entry_id))

        conn.execute("""
            UPDATE entries
            SET title = ?, content = ?, entry_date = ?,
                destination = ?, expenses = ?, status = ?
            WHERE id = ? AND user_id = ?
        """, (
            title, content, entry_date,
            destination or None, expenses, status,
            entry_id, user_id
        ))

        conn.commit()
        conn.close()

        flash("Entry updated successfully!")
        return redirect(url_for(
            "module",
            category=next(
                key for key, value in CATEGORIES.items()
                if value == entry["category"]
            )
        ))

    conn.close()
    return render_template("edit.html", entry=entry)


@app.route("/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete(entry_id):
    conn = get_db()

    entry = conn.execute("""
        SELECT category FROM entries
        WHERE id = ? AND user_id = ?
    """, (entry_id, session["user_id"])).fetchone()

    if entry:
        conn.execute(
            "DELETE FROM entries WHERE id = ? AND user_id = ?",
            (entry_id, session["user_id"])
        )
        conn.commit()

    conn.close()

    if entry:
        category = next(
            (key for key, value in CATEGORIES.items()
             if value == entry["category"]),
            "personal"
        )
        return redirect(url_for("module", category=category))

    return redirect(url_for("dashboard"))


@app.route("/reports")
@login_required
def reports():
    conn = get_db()
    user_id = session["user_id"]

    totals = conn.execute("""
        SELECT category, COUNT(*) AS total
        FROM entries
        WHERE user_id = ?
        GROUP BY category
    """, (user_id,)).fetchall()

    expense_total = conn.execute("""
        SELECT COALESCE(SUM(expenses), 0) AS total
        FROM entries
        WHERE user_id = ?
          AND category IN ('Expense Diary', 'Travel Diary')
    """, (user_id,)).fetchone()["total"]

    conn.close()

    return render_template(
        "reports.html",
        totals=totals,
        expense_total=expense_total
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)