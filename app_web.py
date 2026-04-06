"""
consc.app  --  Full-stack Flask app
======================================
Features:
  * User auth  (signup / login / logout)
  * Password hashing via werkzeug
  * Flask sessions for login state
  * Protected routes  (login required)
  * System generation with new OpenAI prompt
  * Systems linked to logged-in user
  * Personal dashboard with streak counters
  * PDF download from dashboard
  * Feedback wall
  * Dark premium UI

Run locally:
  pip install flask openai fpdf2 werkzeug
  export OPENAI_API_KEY="sk-..."
  python app_web.py
"""

import io
import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, request, jsonify,
    send_file, redirect, url_for, session
)
from openai import OpenAI
from fpdf import FPDF
from werkzeug.security import generate_password_hash, check_password_hash

# =======================================================
#  App setup
# =======================================================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# =======================================================
#  Database helpers
# =======================================================
def get_db():
    """Open a DB connection where columns are accessible by name."""
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't already exist."""
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS systems (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            goal        TEXT,
            book        TEXT,
            output_text TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT,
            message TEXT,
            reply   TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_progress (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            system_id   INTEGER NOT NULL,
            date        TEXT    NOT NULL,
            completed   INTEGER NOT NULL DEFAULT 1,
            UNIQUE (user_id, system_id, date),
            FOREIGN KEY (user_id)   REFERENCES users(id),
            FOREIGN KEY (system_id) REFERENCES systems(id)
        )
    """)

    conn.commit()
    conn.close()


init_db()


# =======================================================
#  Daily progress helpers
# =======================================================
def get_today() -> str:
    """Return today's date as a YYYY-MM-DD string (used as the DB key)."""
    return datetime.utcnow().strftime("%Y-%m-%d")


def get_today_completion(user_id: int, system_id: int) -> bool:
    """Return True if the user has marked this system as completed today."""
    conn = get_db()
    row = conn.execute(
        """SELECT completed
           FROM daily_progress
           WHERE user_id = ? AND system_id = ? AND date = ?""",
        (user_id, system_id, get_today())
    ).fetchone()
    conn.close()
    return bool(row and row["completed"])


def get_streak(user_id: int, system_id: int) -> int:
    """
    Return the current consecutive-day streak for a system.

    Algorithm:
      - Fetch all dates where completed = 1 into a set for O(1) lookup.
      - If today is already marked done, start counting from today.
        If today is NOT yet done, start from yesterday so a prior streak
        is still visible before the user marks today done.
      - Walk backwards one day at a time and stop at the first gap.

    Returns 0 if no streak exists.
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT date FROM daily_progress
           WHERE user_id = ? AND system_id = ? AND completed = 1
           ORDER BY date DESC""",
        (user_id, system_id)
    ).fetchall()
    conn.close()

    if not rows:
        return 0

    completed_dates = {row["date"] for row in rows}   # O(1) membership check

    today = datetime.utcnow().date()

    # Start from today if today is done, yesterday otherwise
    if today.strftime("%Y-%m-%d") in completed_dates:
        check = today
    else:
        check = today - timedelta(days=1)

    streak = 0
    while check.strftime("%Y-%m-%d") in completed_dates:
        streak += 1
        check  -= timedelta(days=1)

    return streak


# =======================================================
#  Auth decorator
# =======================================================
def login_required(f):
    """Redirect to /login if the user is not logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# =======================================================
#  Shared CSS
# =======================================================
BASE_STYLE = """
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:      #080e1a;
  --surface: #0f1c2e;
  --card:    #162032;
  --border:  #1e3a5f;
  --accent:  #38bdf8;
  --accent2: #818cf8;
  --green:   #34d399;
  --red:     #f87171;
  --text:    #e2e8f0;
  --muted:   #64748b;
  --radius:  12px;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 16px;
  line-height: 1.6;
  min-height: 100vh;
}

body::before {
  content: '';
  position: fixed; inset: 0;
  background:
    radial-gradient(ellipse 60% 40% at 20% 10%, #0c1f3d 0%, transparent 60%),
    radial-gradient(ellipse 50% 40% at 80% 90%, #0e1a35 0%, transparent 60%);
  pointer-events: none; z-index: 0;
}

.wrapper {
  position: relative; z-index: 1;
  max-width: 880px; margin: 0 auto;
  padding: 40px 24px 80px;
}

nav {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 56px;
}
.logo {
  font-family: 'Syne', sans-serif; font-weight: 800;
  font-size: 22px; color: var(--accent); text-decoration: none;
}
.nav-links { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }
.nav-links a {
  color: var(--muted); text-decoration: none; font-size: 14px;
  transition: color .2s;
}
.nav-links a:hover, .nav-links a.active { color: var(--accent); }
.nav-user {
  font-size: 13px; color: var(--muted);
  border: 1px solid var(--border); border-radius: 100px;
  padding: 4px 14px;
}

.hero h1 {
  font-family: 'Syne', sans-serif; font-weight: 800;
  font-size: clamp(30px, 5vw, 50px);
  line-height: 1.15; letter-spacing: -1px; margin-bottom: 14px;
}
.hero h1 span { color: var(--accent); }
.hero p { color: var(--muted); font-size: 17px; max-width: 520px; }
.trust {
  display: inline-block; margin-top: 12px; font-size: 13px;
  color: var(--muted); border: 1px solid var(--border);
  border-radius: 100px; padding: 4px 14px;
}

.card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 28px; margin-bottom: 22px;
}
.card-title {
  font-family: 'Syne', sans-serif; font-size: 12px; font-weight: 700;
  letter-spacing: 1.4px; text-transform: uppercase;
  color: var(--accent); margin-bottom: 18px;
}

label {
  display: block; font-size: 13px; color: var(--muted);
  margin-bottom: 5px; margin-top: 2px;
}
input, select, textarea {
  width: 100%; padding: 12px 16px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; color: var(--text);
  font-family: 'DM Sans', sans-serif; font-size: 15px;
  margin-bottom: 14px;
  transition: border-color .2s, box-shadow .2s; outline: none;
}
input::placeholder, textarea::placeholder { color: var(--muted); }
input:focus, select:focus, textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(56,189,248,.12);
}
select option { background: var(--surface); }
textarea { resize: vertical; min-height: 90px; }

.btn {
  display: inline-block; padding: 13px 28px; border-radius: 8px;
  border: none; font-family: 'Syne', sans-serif; font-size: 15px;
  font-weight: 700; cursor: pointer; text-decoration: none;
  transition: opacity .2s, transform .15s;
}
.btn:hover  { opacity: .85; transform: translateY(-1px); }
.btn:active { transform: translateY(0); }
.btn-primary { background: var(--accent);  color: #060e1b; width: 100%; text-align: center; }
.btn-green   { background: var(--green);   color: #060e1b; }
.btn-red     { background: var(--red);     color: #060e1b; }
.btn-purple  { background: var(--accent2); color: #060e1b; }
.btn-outline {
  background: transparent; border: 1px solid var(--border); color: var(--text);
}
.btn-outline:hover { border-color: var(--accent); color: var(--accent); }
.btn-sm { padding: 8px 16px; font-size: 13px; }

.alert {
  padding: 14px 18px; border-radius: 8px;
  margin-bottom: 22px; font-size: 14px;
}
.alert-success { background: rgba(52,211,153,.1);  border: 1px solid var(--green); color: var(--green); }
.alert-error   { background: rgba(248,113,113,.1); border: 1px solid var(--red);   color: var(--red);   }
.alert-info    { background: rgba(56,189,248,.08); border: 1px solid var(--accent); color: var(--accent); }

.row { display: flex; gap: 14px; }
.row > * { flex: 1; }
@media (max-width: 540px) { .row { flex-direction: column; } }

.samples { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 30px; }
.chip {
  padding: 8px 16px; background: var(--card);
  border: 1px solid var(--border); border-radius: 100px;
  font-size: 13px; color: var(--muted);
}
.chip strong { color: var(--text); }

.result-body {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 24px; line-height: 1.8;
  font-size: 15px; white-space: pre-wrap;
}

/* Streak badge -- sits inline after the toggle button */
.streak-badge {
  display: inline-block;
  margin-left: 8px;
  font-size: 12px;
  color: var(--green);
  font-weight: 700;
  vertical-align: middle;
  min-width: 28px;   /* keeps layout stable when the number changes */
}

/* Dashboard table */
.dash-table { width: 100%; border-collapse: collapse; }
.dash-table th {
  text-align: left; font-size: 12px; font-weight: 700;
  letter-spacing: 1px; text-transform: uppercase;
  color: var(--muted); padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}
.dash-table td {
  padding: 14px; border-bottom: 1px solid var(--border);
  font-size: 14px; vertical-align: middle;
}
.dash-table tr:last-child td { border-bottom: none; }
.dash-table tr:hover td { background: rgba(56,189,248,.04); }

.auth-wrap {
  max-width: 420px; margin: 60px auto;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 16px; padding: 36px;
}
.auth-wrap h2 {
  font-family: 'Syne', sans-serif; font-size: 24px;
  font-weight: 800; margin-bottom: 6px;
}
.auth-wrap p { color: var(--muted); font-size: 14px; margin-bottom: 24px; }
.auth-switch { text-align: center; font-size: 14px; margin-top: 20px; color: var(--muted); }
.auth-switch a { color: var(--accent); text-decoration: none; }

.feedback-item {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 20px; margin-bottom: 14px;
}
.feedback-author {
  font-family: 'Syne', sans-serif; font-size: 14px;
  font-weight: 700; color: var(--accent); margin-bottom: 6px;
}
.feedback-reply {
  margin-top: 12px; padding: 10px 14px;
  background: var(--surface); border-left: 3px solid var(--accent2);
  border-radius: 6px; font-size: 14px; color: var(--muted);
}

h2 {
  font-family: 'Syne', sans-serif; font-size: 26px;
  font-weight: 800; margin-bottom: 20px; letter-spacing: -.5px;
}
h3 {
  font-family: 'Syne', sans-serif; font-size: 18px;
  font-weight: 700; margin-bottom: 14px;
}
"""


# =======================================================
#  Page wrapper
# =======================================================
def page(title, body, active="home"):
    username = session.get("username")

    if username:
        nav_right = (
            f'<a href="/" {"class=\'active\'" if active == "home" else ""}>Generator</a>'
            f'<a href="/dashboard" {"class=\'active\'" if active == "dashboard" else ""}>Dashboard</a>'
            f'<a href="/feedback" {"class=\'active\'" if active == "feedback" else ""}>Feedback</a>'
            f'<span class="nav-user">&#128100; {username}</span>'
            f'<a href="/logout" class="btn btn-outline btn-sm">Logout</a>'
        )
    else:
        nav_right = (
            '<a href="/feedback">Feedback</a>'
            '<a href="/login" class="btn btn-outline btn-sm">Login</a>'
            '<a href="/signup" class="btn btn-primary btn-sm" style="width:auto;">Sign up</a>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} &#8212; consc.app</title>
  <style>{BASE_STYLE}</style>
</head>
<body>
<div class="wrapper">
  <nav>
    <a href="/" class="logo">&#9889; consc.app</a>
    <div class="nav-links">{nav_right}</div>
  </nav>
  {body}
</div>
</body>
</html>"""


# =======================================================
#  SIGNUP
# =======================================================
@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email",    "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            error = "All fields are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            hashed = generate_password_hash(password)
            try:
                conn = get_db()
                cur = conn.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, hashed)
                )
                conn.commit()
                session["user_id"]  = cur.lastrowid
                session["username"] = username
                conn.close()
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "That username or email is already taken."

    err_html = f'<div class="alert alert-error">{error}</div>' if error else ""

    body = f"""
<div class="auth-wrap">
  <h2>Create account</h2>
  <p>Join consc.app and start building systems that stick.</p>
  {err_html}
  <form method="POST">
    <label>Username</label>
    <input name="username" placeholder="e.g. alex123" required>
    <label>Email</label>
    <input name="email" type="email" placeholder="you@email.com" required>
    <label>Password <span style="color:var(--muted); font-weight:400;">(min 6 characters)</span></label>
    <input name="password" type="password" placeholder="Choose a password" required>
    <button class="btn btn-primary">Create Account &#128640;</button>
  </form>
  <p class="auth-switch">Already have an account? <a href="/login">Login &rarr;</a></p>
</div>
"""
    return page("Sign Up", body)


# =======================================================
#  LOGIN
# =======================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        email    = request.form.get("email",    "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            error = "Incorrect email or password."
        else:
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))

    err_html = f'<div class="alert alert-error">{error}</div>' if error else ""

    body = f"""
<div class="auth-wrap">
  <h2>Welcome back</h2>
  <p>Login to access your systems and dashboard.</p>
  {err_html}
  <form method="POST">
    <label>Email</label>
    <input name="email" type="email" placeholder="you@email.com" required>
    <label>Password</label>
    <input name="password" type="password" placeholder="Your password" required>
    <button class="btn btn-primary">Login &rarr;</button>
  </form>
  <p class="auth-switch">No account yet? <a href="/signup">Sign up free &rarr;</a></p>
</div>
"""
    return page("Login", body)


# =======================================================
#  LOGOUT
# =======================================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =======================================================
#  GENERATOR   /
# =======================================================
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    result   = None
    error    = None
    saved_id = None

    if request.method == "POST":
        goal       = request.form.get("goal",       "").strip()
        book       = request.form.get("book",       "").strip()
        why        = request.form.get("why",        "").strip()
        daily_time = request.form.get("daily_time", "30").strip()
        difficulty = request.form.get("difficulty", "Medium")
        struggle   = request.form.get("struggle",   "").strip()
        custom     = request.form.get("custom",     "").strip()

        prompt = f"""You are a world-class habit coach. Build a detailed, practical action system.

User profile:
- Goal: {goal}
- Source book/method: {book}
- Daily time available: {daily_time} minutes
- Difficulty preference: {difficulty}
- Why they want this: {why}
- Biggest struggle: {struggle}
- Constraints: {custom if custom else 'None'}

Respond with exactly these 6 sections. Be specific, not generic:

1. Identity Shift
   The new identity this person must adopt. One clear statement + 2-3 supporting beliefs.

2. Daily Plan ({daily_time}-minute version)
   A concrete step-by-step routine that fits in {daily_time} minutes per day.

3. Weekly Plan
   Mon-Sun: one concrete action per day, building the habit progressively.

4. Habit Triggers
   3 specific "when X, then Y" trigger-action pairs to make the habit automatic.

5. Failure Recovery Plan
   What to do when the user skips a day or gives up. A clear 3-step reset protocol.

6. Tracking Method
   One simple way to track daily progress (no apps required).
"""

        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1400,
            )
            result = response.choices[0].message.content

            conn = get_db()
            try:
                cur = conn.execute(
                    "INSERT INTO systems (user_id, goal, book, output_text) VALUES (?, ?, ?, ?)",
                    (session["user_id"], goal, book, result)
                )
                saved_id = cur.lastrowid
                conn.commit()
            finally:
                conn.close()

        except Exception as e:
            error = f"AI error: {str(e)}"

    result_html = ""
    if error:
        result_html = f'<div class="alert alert-error">{error}</div>'
    elif result:
        escaped = (result
                   .replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;"))
        result_html = f"""
<div class="card" style="margin-top:40px;">
  <div class="card-title">Your Generated System</div>
  <div class="result-body">{escaped}</div>
</div>
<div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:16px;">
  <a href="/dashboard" class="btn btn-green btn-sm">&#128203; View in Dashboard</a>
  <form method="POST" action="/pdf_by_id" style="margin:0;">
    <input type="hidden" name="system_id" value="{saved_id}">
    <button class="btn btn-outline btn-sm">&#128196; Download PDF</button>
  </form>
</div>
<p style="margin-top:10px; font-size:13px; color:var(--muted);">
  &#10003; Automatically saved to your Dashboard.
</p>
"""

    body = f"""
<div class="hero" style="margin-bottom:36px;">
  <h1>Turn <span>Knowledge</span><br>into Action</h1>
  <p>Enter your goal and a book &#8212; we'll build a daily system around your life.</p>
  <span class="trust">Designed to close the gap between knowing and doing</span>
</div>

<div class="card-title" style="margin-bottom:10px;">&#10024; Example prompts</div>
<div class="samples">
  <span class="chip"><strong>Goal:</strong> Wake up at 6am &nbsp;&middot;&nbsp; <strong>Book:</strong> Atomic Habits</span>
  <span class="chip"><strong>Goal:</strong> Build side income &nbsp;&middot;&nbsp; <strong>Book:</strong> Rich Dad Poor Dad</span>
  <span class="chip"><strong>Goal:</strong> Read 20 books/year &nbsp;&middot;&nbsp; <strong>Book:</strong> Deep Work</span>
</div>

<div class="card">
  <div class="card-title">Build your system</div>
  <p style="color:var(--muted); font-size:14px; margin-bottom:20px;">
    The more honest you are, the more specific your system will be.
  </p>
  <form method="POST">
    <div class="row">
      <div>
        <label>Your Goal</label>
        <input name="goal" placeholder="e.g. wake up at 6am every day" required>
      </div>
      <div>
        <label>Book or Method</label>
        <input name="book" placeholder="e.g. Atomic Habits" required>
      </div>
    </div>
    <div class="row">
      <div>
        <label>Daily Time Available (minutes)</label>
        <input name="daily_time" type="number" min="5" max="240" placeholder="e.g. 30" value="30">
      </div>
      <div>
        <label>Difficulty Level</label>
        <select name="difficulty">
          <option>Easy</option>
          <option selected>Medium</option>
          <option>Hard</option>
        </select>
      </div>
    </div>
    <label>Why do you want this?</label>
    <input name="why" placeholder="Be honest &#8212; it makes the system stronger" required>
    <label>Biggest Struggle</label>
    <input name="struggle" placeholder="What always makes you quit?" required>
    <label>Constraints <span style="color:var(--muted); font-weight:400;">(optional)</span></label>
    <input name="custom" placeholder="e.g. work until 11pm, no gym, two kids">
    <button class="btn btn-primary">Generate My System &#128640;</button>
  </form>
</div>

{result_html}
"""
    return page("Generator", body, active="home")


# =======================================================
#  DASHBOARD   /dashboard
# =======================================================
@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    conn = get_db()
    rows = conn.execute(
        """SELECT id, goal, book, created_at
           FROM systems
           WHERE user_id = ?
           ORDER BY id DESC""",
        (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        table_html = """
<div class="alert alert-info">
  You haven't generated any systems yet.
  <a href="/" style="color:inherit; font-weight:700; margin-left:6px;">
    Create your first one &rarr;
  </a>
</div>"""
    else:
        rows_html = ""
        for row in rows:
            try:
                dt = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
                date_str = dt.strftime("%b %d, %Y")
            except Exception:
                date_str = row["created_at"] or "&#8212;"

            goal_safe = (row["goal"] or "&#8212;").replace("<","&lt;").replace(">","&gt;")
            book_safe = (row["book"] or "&#8212;").replace("<","&lt;").replace(">","&gt;")

            # Check today's completion and current streak
            done   = get_today_completion(user_id, row["id"])
            streak = get_streak(user_id, row["id"])

            btn_label = "&#10003; Done"     if done else "&#9634; Mark done"
            btn_class = "btn-green"          if done else "btn-outline"
            btn_title = "Click to undo"      if done else "Mark as done for today"

            # Streak badge: fire emoji + count when streak > 0.
            # data-sid lets the JS find the exact badge for this row.
            if streak > 0:
                streak_badge = (
                    f'<span class="streak-badge" data-sid="{row["id"]}"'
                    f' title="{streak}-day streak">'
                    f'&#128293; {streak}</span>'
                )
            else:
                streak_badge = (
                    f'<span class="streak-badge" data-sid="{row["id"]}"'
                    f' title="No streak yet"></span>'
                )

            rows_html += f"""
<tr>
  <td style="font-weight:500; max-width:180px;">{goal_safe}</td>
  <td style="color:var(--muted);">{book_safe}</td>
  <td style="color:var(--muted); white-space:nowrap;">{date_str}</td>
  <td style="white-space:nowrap;">
    <button
      class="btn {btn_class} btn-sm today-btn"
      data-id="{row['id']}"
      title="{btn_title}"
      onclick="toggleToday(this, {row['id']})">
      {btn_label}
    </button>
    {streak_badge}
  </td>
  <td>
    <div style="display:flex; gap:8px;">
      <a href="/system/{row['id']}" class="btn btn-outline btn-sm"
         title="Read the full system">View</a>
      <form method="POST" action="/pdf_by_id" style="margin:0;">
        <input type="hidden" name="system_id" value="{row['id']}">
        <button class="btn btn-purple btn-sm" title="Download as PDF">PDF</button>
      </form>
    </div>
  </td>
</tr>"""

        table_html = f"""
<div class="card" style="padding:0; overflow:hidden;">
  <table class="dash-table">
    <thead>
      <tr>
        <th>Goal</th>
        <th>Book / Method</th>
        <th>Created</th>
        <th>Today</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""

    body = f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; flex-wrap:wrap; gap:12px;">
  <h2 style="margin:0;">My Systems</h2>
  <a href="/" class="btn btn-primary btn-sm" style="width:auto;">+ New System</a>
</div>
<p style="color:var(--muted); font-size:14px; margin-bottom:28px;">
  All systems generated by
  <strong style="color:var(--text);">{session.get("username")}</strong>.
  Mark a system done each day to build your streak.
</p>
{table_html}

<script>
// POST to /complete_today/<id>, then update BOTH the toggle button and the
// streak badge without a page reload.
// Server now returns: {{ "completed": bool, "system_id": int, "streak": int }}
function toggleToday(btn, systemId) {{
  btn.disabled = true;  // prevent double-clicks while in flight

  fetch('/complete_today/' + systemId, {{ method: 'POST' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{

      // --- Update the toggle button ---
      if (data.completed) {{
        btn.textContent = '&#10003; Done';
        btn.title       = 'Click to undo';
        btn.className   = 'btn btn-green btn-sm today-btn';
      }} else {{
        btn.textContent = '&#9634; Mark done';
        btn.title       = 'Mark as done for today';
        btn.className   = 'btn btn-outline btn-sm today-btn';
      }}

      // --- Update the streak badge in the same <td> ---
      // querySelector scopes to btn.parentElement so rows never
      // interfere with each other even when IDs look similar.
      var badge = btn.parentElement
                    .querySelector('.streak-badge[data-sid="' + systemId + '"]');
      if (badge) {{
        if (data.streak > 0) {{
          badge.innerHTML = '&#128293; ' + data.streak;
          badge.title     = data.streak + '-day streak';
        }} else {{
          badge.innerHTML = '';
          badge.title     = 'No streak yet';
        }}
      }}
    }})
    .catch(function() {{
      btn.textContent = '&#9888; Retry';
    }})
    .finally(function() {{
      btn.disabled = false;
    }});
}}
</script>
"""
    return page("Dashboard", body, active="dashboard")


# =======================================================
#  VIEW SINGLE SYSTEM   /system/<id>
# =======================================================
@app.route("/system/<int:system_id>")
@login_required
def view_system(system_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM systems WHERE id = ? AND user_id = ?",
        (system_id, session["user_id"])
    ).fetchone()
    conn.close()

    if not row:
        body = '<div class="alert alert-error">System not found or access denied.</div>'
        body += '<a href="/dashboard" class="btn btn-outline">&larr; Dashboard</a>'
        return page("Not Found", body)

    escaped   = (row["output_text"] or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    goal_safe = (row["goal"] or "").replace("<","&lt;").replace(">","&gt;")
    book_safe = (row["book"] or "").replace("<","&lt;").replace(">","&gt;")

    try:
        dt = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        date_str = dt.strftime("%B %d, %Y")
    except Exception:
        date_str = row["created_at"] or ""

    body = f"""
<div style="margin-bottom:24px;">
  <a href="/dashboard" class="btn btn-outline btn-sm">&larr; Dashboard</a>
</div>

<div class="card" style="margin-bottom:16px;">
  <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:12px;">
    <div>
      <div class="card-title">System #{row['id']}</div>
      <h2 style="margin-bottom:4px;">{goal_safe}</h2>
      <p style="color:var(--muted); font-size:14px;">
        &#128218; {book_safe} &nbsp;&middot;&nbsp; &#128197; {date_str}
      </p>
    </div>
    <form method="POST" action="/pdf_by_id" style="align-self:flex-start;">
      <input type="hidden" name="system_id" value="{row['id']}">
      <button class="btn btn-purple btn-sm" title="Download as PDF">
        &#128196; Download PDF
      </button>
    </form>
  </div>
</div>

<div class="result-body">{escaped}</div>
"""
    return page(f"System &#8212; {goal_safe}", body)


# =======================================================
#  PDF DOWNLOAD   /pdf_by_id
# =======================================================
@app.route("/pdf_by_id", methods=["POST"])
@login_required
def pdf_by_id():
    system_id = request.form.get("system_id", "")

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM systems WHERE id = ? AND user_id = ?",
        (system_id, session["user_id"])
    ).fetchone()
    conn.close()

    if not row:
        return redirect(url_for("dashboard"))

    return _build_pdf(row["output_text"], row["goal"])


def _sanitise_for_pdf(text: str) -> str:
    """Replace Unicode characters Helvetica cannot encode with ASCII equivalents."""
    REPLACEMENTS = {
        "\u2014": "--",  "\u2013": "-",   "\u2012": "-",   "\u2015": "--",
        "\u2018": "'",   "\u2019": "'",   "\u201c": '"',   "\u201d": '"',
        "\u201e": '"',   "\u201a": ",",   "\u2026": "...", "\u2022": "*",
        "\u2023": ">",   "\u25cf": "*",   "\u2713": "OK",  "\u2714": "OK",
        "\u2717": "X",   "\u2718": "X",   "\u2192": "->",  "\u2190": "<-",
        "\u2191": "^",   "\u2193": "v",   "\u00a0": " ",   "\u200b": "",
    }
    for char, replacement in REPLACEMENTS.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", errors="ignore").decode("latin-1")


def _build_pdf(content, title=""):
    """Build and return a PDF file from text content."""
    MARGIN = 15
    LINE_H = 7

    pdf_doc = FPDF()
    pdf_doc.set_margins(left=MARGIN, top=MARGIN, right=MARGIN)
    pdf_doc.set_auto_page_break(auto=True, margin=MARGIN)
    pdf_doc.add_page()

    usable_w = max(pdf_doc.w - 2 * MARGIN, 50)

    def write_line(text, style, size, line_h):
        pdf_doc.set_font("Helvetica", style=style, size=size)
        pdf_doc.set_x(MARGIN)
        clean = _sanitise_for_pdf(text)
        if not clean.strip():
            pdf_doc.ln(line_h)
            return
        try:
            pdf_doc.multi_cell(usable_w, line_h, clean)
        except Exception:
            pdf_doc.ln(line_h)

    write_line("consc.app -- Action System", "B", 16, 10)
    if title:
        write_line(title, "I", 12, 8)
    pdf_doc.ln(4)
    for line in (content or "").split("\n"):
        write_line(line, "", 11, LINE_H)

    buffer = io.BytesIO(pdf_doc.output())
    return send_file(
        buffer,
        as_attachment=True,
        download_name="consc_system.pdf",
        mimetype="application/pdf"
    )


# =======================================================
#  COMPLETE TODAY   /complete_today/<system_id>
# =======================================================
@app.route("/complete_today/<int:system_id>", methods=["POST"])
@login_required
def complete_today(system_id):
    """
    Toggle today's completion for a system.

    Returns JSON with the new state AND the updated streak so the dashboard
    can refresh both the button and the badge without a page reload.

    Response: { "completed": bool, "system_id": int, "streak": int }
    """
    user_id = session["user_id"]
    today   = get_today()

    conn = get_db()

    existing = conn.execute(
        """SELECT id, completed
           FROM daily_progress
           WHERE user_id = ? AND system_id = ? AND date = ?""",
        (user_id, system_id, today)
    ).fetchone()

    if existing is None:
        conn.execute(
            """INSERT INTO daily_progress (user_id, system_id, date, completed)
               VALUES (?, ?, ?, 1)""",
            (user_id, system_id, today)
        )
        new_status = True
    else:
        new_status = not bool(existing["completed"])
        conn.execute(
            "UPDATE daily_progress SET completed = ? WHERE id = ?",
            (int(new_status), existing["id"])
        )

    conn.commit()
    conn.close()

    # Compute streak AFTER the DB write so it reflects the toggled state
    streak = get_streak(user_id, system_id)

    return jsonify({"completed": new_status, "system_id": system_id, "streak": streak})


# =======================================================
#  FEEDBACK   /feedback
# =======================================================
@app.route("/feedback")
def feedback():
    conn = get_db()
    rows = conn.execute(
        "SELECT name, message, reply FROM feedback ORDER BY id DESC"
    ).fetchall()
    conn.close()

    items_html = ""
    for row in rows:
        reply_html = ""
        if row["reply"]:
            reply_html = (
                f'<div class="feedback-reply">'
                f'&#128172; <strong>Reply:</strong> {row["reply"]}'
                f'</div>'
            )
        msg = (row["message"]
               .replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"))
        items_html += f"""
<div class="feedback-item">
  <div class="feedback-author">{row['name']}</div>
  <div>{msg}</div>
  {reply_html}
</div>"""

    if not items_html:
        items_html = '<p style="color:var(--muted);">No feedback yet &#8212; be the first!</p>'

    body = f"""
<h2>Feedback Wall</h2>

<div class="card" style="margin-bottom:36px;">
  <div class="card-title">Share your thoughts</div>
  <p style="color:var(--muted); font-size:14px; margin-bottom:18px;">
    Feature requests, bugs, praise &#8212; all welcome.
  </p>
  <form method="POST" action="/feedback_submit">
    <label>Your name</label>
    <input name="name" placeholder="e.g. Alex" required>
    <label>Message</label>
    <textarea name="message" placeholder="What's on your mind?" required></textarea>
    <button class="btn btn-primary">Send Feedback &#128588;</button>
  </form>
</div>

<h3>What people are saying</h3>
{items_html}

<br>
<a href="/" class="btn btn-outline">&larr; Back to Generator</a>
"""
    return page("Feedback", body, active="feedback")


@app.route("/feedback_submit", methods=["POST"])
def feedback_submit():
    name    = request.form.get("name",    "").strip()
    message = request.form.get("message", "").strip()

    if name and message:
        conn = get_db()
        conn.execute(
            "INSERT INTO feedback (name, message) VALUES (?, ?)", (name, message)
        )
        conn.commit()
        conn.close()

    body = """
<div class="alert alert-success">&#128588; Thanks! We read every message.</div>
<a href="/feedback" class="btn btn-outline">&larr; Back to Feedback</a>
&nbsp;
<a href="/"         class="btn btn-outline">Go to Generator &rarr;</a>
"""
    return page("Feedback Received", body)


# =======================================================
#  Run
# =======================================================
if __name__ == "__main__":
    debug_mode = os.getenv("DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode)