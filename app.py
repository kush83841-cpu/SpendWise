"""
SpendWise - Expense Tracker v3 (fresh build)
Features:
  1. Catchy design
  2. Login (name / username / password, hashed, per-user data)
  3. Add expense: date, time, category dropdown + "Other" dialogue box
  4. History with filters (date, category)
  5. Daily spend totals in history
  6. Spending chart
"""

import os
import sqlite3
from datetime import date, timedelta
from functools import wraps

from flask import (
    Flask, flash, g, jsonify, redirect, render_template,
    request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

DATABASE = os.path.join(app.instance_path, "expenses.db")

CATEGORIES = ["Food", "Travel", "Shopping", "Bills", "Entertainment", "Health", "Other"]


# ---------- database ----------

def get_db():
    """One database connection per request, cached on Flask's `g`."""
    if "db" not in g:
        os.makedirs(app.instance_path, exist_ok=True)
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables if they don't exist yet."""
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    db.commit()


# ---------- auth helpers ----------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        error = None
        if not name or not username or not password:
            error = "Please fill in all fields."
        elif len(password) < 4:
            error = "Password must be at least 4 characters."
        elif db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            error = "That username is already taken."
        if error:
            flash(error)
        else:
            db.execute(
                "INSERT INTO users (name, username, password_hash) VALUES (?, ?, ?)",
                (name, username, generate_password_hash(password)),
            )
            db.commit()
            flash("Account created! Now log in. 🎉")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        flash("Wrong username or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- dashboard ----------

@app.route("/")
@login_required
def index():
    db = get_db()
    uid = session["user_id"]
    user = current_user()
    month = date.today().strftime("%Y-%m")

    month_total = db.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE user_id = ? AND date LIKE ?",
        (uid, month + "%"),
    ).fetchone()[0]

    today_total = db.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE user_id = ? AND date = ?",
        (uid, date.today().isoformat()),
    ).fetchone()[0]

    by_category = db.execute(
        """
        SELECT category, COALESCE(SUM(amount), 0) AS total
        FROM expenses WHERE user_id = ? AND date LIKE ?
        GROUP BY category ORDER BY total DESC
        """,
        (uid, month + "%"),
    ).fetchall()

    recent = db.execute(
        "SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 8",
        (uid,),
    ).fetchall()

    return render_template(
        "index.html",
        user=user,
        month=date.today().strftime("%B %Y"),
        month_total=month_total,
        today_total=today_total,
        by_category=by_category,
        recent=recent,
        categories=CATEGORIES,
        today=date.today().isoformat(),
    )


@app.route("/add", methods=["POST"])
@login_required
def add_expense():
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "Other").strip()[:50]
    expense_date = request.form.get("date") or date.today().isoformat()
    expense_time = request.form.get("time", "").strip()
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0

    if amount > 0 and category:
        db = get_db()
        db.execute(
            "INSERT INTO expenses (user_id, title, amount, category, date, time)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (session["user_id"], title or category, amount, category, expense_date, expense_time),
        )
        db.commit()
    return redirect(url_for("index"))


@app.route("/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    db = get_db()
    db.execute(
        "DELETE FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, session["user_id"]),
    )
    db.commit()
    return redirect(request.referrer or url_for("index"))


# ---------- history with filters + daily totals ----------

@app.route("/history")
@login_required
def history():
    db = get_db()
    uid = session["user_id"]
    f_date = request.args.get("date", "").strip()
    f_cat = request.args.get("category", "").strip()

    query = "SELECT * FROM expenses WHERE user_id = ?"
    params = [uid]
    if f_date:
        query += " AND date = ?"
        params.append(f_date)
    if f_cat:
        query += " AND category = ?"
        params.append(f_cat)
    query += " ORDER BY date DESC, time DESC, id DESC"
    rows = db.execute(query, params).fetchall()

    # Group by date, with a total per day
    days = []
    for r in rows:
        if not days or days[-1]["date"] != r["date"]:
            days.append({"date": r["date"], "total": 0.0, "items": []})
        days[-1]["items"].append(r)
        days[-1]["total"] += r["amount"]

    grand_total = sum(d["total"] for d in days)

    return render_template(
        "history.html",
        user=current_user(),
        days=days,
        grand_total=grand_total,
        f_date=f_date,
        f_cat=f_cat,
        categories=CATEGORIES,
    )


# ---------- chart data ----------

@app.route("/api/summary")
@login_required
def api_summary():
    month = date.today().strftime("%Y-%m")
    db = get_db()
    rows = db.execute(
        """
        SELECT category, COALESCE(SUM(amount), 0) AS total
        FROM expenses WHERE user_id = ? AND date LIKE ?
        GROUP BY category ORDER BY total DESC
        """,
        (session["user_id"], month + "%"),
    ).fetchall()
    return jsonify(
        {
            "month": date.today().strftime("%B %Y"),
            "labels": [r["category"] for r in rows],
            "totals": [r["total"] for r in rows],
        }
    )

def subtract_months(d, n):
    """First day of the month, n months before date d."""
    month = d.month - n
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


@app.route("/insights")
@login_required
def insights():
    return render_template("insights.html", user=current_user())


@app.route("/api/spending")
@login_required
def api_spending():
    """Bar-chart data: totals per day (weekly), per month, or per year."""
    period = request.args.get("period", "weekly")
    uid = session["user_id"]
    db = get_db()
    labels, totals = [], []
    today = date.today()

    if period == "monthly":
        for i in range(11, -1, -1):
            m = subtract_months(today, i)
            key = m.strftime("%Y-%m")
            labels.append(m.strftime("%b %y"))
            totals.append(db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE user_id = ? AND date LIKE ?",
                (uid, key + "%"),
            ).fetchone()[0])
    elif period == "yearly":
        for y in range(today.year - 4, today.year + 1):
            labels.append(str(y))
            totals.append(db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE user_id = ? AND date LIKE ?",
                (uid, str(y) + "%"),
            ).fetchone()[0])
    else:  # weekly: last 7 days
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            labels.append(d.strftime("%a %d"))
            totals.append(db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE user_id = ? AND date = ?",
                (uid, d.isoformat()),
            ).fetchone()[0])

    return jsonify({"labels": labels, "totals": totals})

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
    