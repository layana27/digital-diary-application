            total_row = conn.execute("""
                SELECT COALESCE(SUM(amount),0) AS total FROM entries
                WHERE user_id=%s AND category='expense' AND TO_CHAR(entry_date,'YYYY-MM')=%s
            """, (session["user_id"], selected_month)).fetchone() or {}
            budget_row = conn.execute("SELECT amount FROM monthly_budgets WHERE user_id=%s AND month=%s",
                                      (session["user_id"], selected_month)).fetchone()
            expense_summary["total"] = float(total_row.get("total") or 0)
            expense_summary["budget"] = float((budget_row or {}).get("amount") or 0)
            expense_summary["remaining"] = expense_summary["budget"] - expense_summary["total"]
            expense_summary["categories"] = conn.execute("""
                SELECT COALESCE(expense_category,'Other') AS label, SUM(COALESCE(amount,0)) AS total
                FROM entries WHERE user_id=%s AND category='expense' AND TO_CHAR(entry_date,'YYYY-MM')=%s
                GROUP BY expense_category ORDER BY total DESC
            """, (session["user_id"], selected_month)).fetchall()
    return render_template("module.html", category=key, category_name=CATEGORIES[key], entries=entries,
                           search=search, today=date.today().isoformat(), expense_summary=expense_summary,
                           health_summary=health_summary, selected_month=selected_month)


@app.route("/add/<category>", methods=["POST"])
@login_required
def add_entry(category):
    key = category.lower()
    if key not in CATEGORIES:
        return redirect(url_for("dashboard"))
    f = request.form
    title = f.get("title", "").strip()
    if not title:
        flash("Please enter a title.", "error")
        return redirect(url_for("module", category=key))
    entry_date = f.get("entry_date") or date.today().isoformat()
    data = (
        session["user_id"], key, title, f.get("content", "").strip(), entry_date,
        number_or_none(f.get("amount")), f.get("expense_category") or None,
        f.get("study_subject") or None, f.get("study_status") or None,
        f.get("activity") or None, number_or_none(f.get("exercise_minutes"), int),
        number_or_none(f.get("water_glasses")), number_or_none(f.get("water_goal")),
        number_or_none(f.get("sleep_hours")), number_or_none(f.get("meditation_minutes"), int),
        f.get("meals") or None, f.get("period_start") or None, f.get("period_end") or None,
        f.get("flow") or None, f.get("symptoms") or None, f.get("health_status") or None
    )
    with get_db() as conn:
        conn.execute("""
            INSERT INTO entries (user_id,category,title,content,entry_date,amount,expense_category,
              study_subject,study_status,activity,exercise_minutes,water_glasses,water_goal,sleep_hours,
              meditation_minutes,meals,period_start,period_end,flow,symptoms,health_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, data)
    flash("Entry saved successfully.", "success")
    return redirect(url_for("module", category=key))


@app.route("/edit/<int:entry_id>", methods=["GET", "POST"])
@login_required
def edit_entry(entry_id):
    with get_db() as conn:
        entry = conn.execute("SELECT * FROM entries WHERE id=%s AND user_id=%s",
                             (entry_id, session["user_id"])).fetchone()
        if not entry:
            flash("Entry not found.", "error")
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            f = request.form
            conn.execute("""UPDATE entries SET title=%s,content=%s,entry_date=%s,amount=%s,
                expense_category=%s,study_subject=%s,study_status=%s,activity=%s,exercise_minutes=%s,
                water_glasses=%s,water_goal=%s,sleep_hours=%s,meditation_minutes=%s,meals=%s,
                period_start=%s,period_end=%s,flow=%s,symptoms=%s,health_status=%s
                WHERE id=%s AND user_id=%s""", (
                f.get("title", "").strip(), f.get("content", "").strip(), f.get("entry_date") or date.today().isoformat(),
                number_or_none(f.get("amount")), f.get("expense_category") or None,
                f.get("study_subject") or None, f.get("study_status") or None, f.get("activity") or None,
                number_or_none(f.get("exercise_minutes"), int), number_or_none(f.get("water_glasses")),
                number_or_none(f.get("water_goal")), number_or_none(f.get("sleep_hours")),
                number_or_none(f.get("meditation_minutes"), int), f.get("meals") or None,
                f.get("period_start") or None, f.get("period_end") or None, f.get("flow") or None,
                f.get("symptoms") or None, f.get("health_status") or None, entry_id, session["user_id"]))
            flash("Entry updated.", "success")
            return redirect(url_for("module", category=entry["category"]))
    return render_template("edit_entry.html", entry=entry, category_name=CATEGORIES.get(entry["category"], "Diary"))


@app.route("/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete_entry(entry_id):
    with get_db() as conn:
        entry = conn.execute("SELECT category FROM entries WHERE id=%s AND user_id=%s",
                             (entry_id, session["user_id"])).fetchone()
        if entry:
            conn.execute("DELETE FROM entries WHERE id=%s AND user_id=%s", (entry_id, session["user_id"]))
            flash("Entry deleted.", "success")
            return redirect(url_for("module", category=entry["category"]))
    flash("Entry not found.", "error")
    return redirect(url_for("dashboard"))


@app.route("/reports")
@login_required
def reports():
    with get_db() as conn:
        report_rows = conn.execute("""
            SELECT category, COUNT(*) AS total FROM entries WHERE user_id=%s GROUP BY category ORDER BY category
        """, (session["user_id"],)).fetchall()
    return render_template("reports.html", report_rows=report_rows, categories=CATEGORIES)


if __name__ == "__main__":
    if DATABASE_URL:
        init_db()
    app.run(debug=True)
