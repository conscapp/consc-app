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
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  /* Brand */
  --green:       #16a34a;
  --green-light: #dcfce7;
  --green-mid:   #bbf7d0;
  --green-dark:  #14532d;

  /* Surface */
  --bg:          #f8fafc;
  --bg-alt:      #f1f5f9;
  --card:        #ffffff;
  --sidebar:     #ffffff;

  /* Text */
  --text:        #0f172a;
  --text-muted:  #64748b;
  --text-xs:     #94a3b8;

  /* Chrome */
  --border:      #e2e8f0;
  --border-mid:  #cbd5e1;
  --shadow-sm:   0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
  --shadow-md:   0 4px 16px rgba(0,0,0,.08), 0 2px 6px rgba(0,0,0,.05);
  --shadow-lg:   0 12px 40px rgba(0,0,0,.10), 0 4px 12px rgba(0,0,0,.06);

  /* Radius */
  --r-sm: 8px;
  --r-md: 12px;
  --r-lg: 16px;
  --r-xl: 20px;

  /* Layout */
  --sidebar-w: 240px;
}

/* ── Reset & Base ── */
html { font-size: 16px; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 15px;
  line-height: 1.6;
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}

/* ── Sidebar Layout ── */
.layout {
  display: flex;
  min-height: 100vh;
}

/* SIDEBAR */
.sidebar {
  width: var(--sidebar-w);
  background: var(--sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0; left: 0; bottom: 0;
  z-index: 100;
  transition: transform .25s ease;
}

.sidebar-logo {
  padding: 24px 20px 20px;
  border-bottom: 1px solid var(--border);
}
.sidebar-logo a {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  color: var(--text);
}
.logo-mark {
  width: 32px; height: 32px;
  background: var(--green);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: white;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
}
.logo-text {
  font-family: 'DM Serif Display', serif;
  font-size: 18px;
  letter-spacing: -0.3px;
  color: var(--text);
}
.logo-tagline {
  font-size: 10px;
  color: var(--text-muted);
  letter-spacing: .5px;
  text-transform: uppercase;
  margin-top: 1px;
}

.sidebar-nav {
  flex: 1;
  padding: 12px 12px;
  overflow-y: auto;
}

.nav-section-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--text-xs);
  padding: 8px 8px 6px;
  margin-top: 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: var(--r-sm);
  text-decoration: none;
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 500;
  transition: all .15s ease;
  margin-bottom: 2px;
}
.nav-item:hover {
  background: var(--bg-alt);
  color: var(--text);
}
.nav-item.active {
  background: var(--green-light);
  color: var(--green-dark);
  font-weight: 600;
}
.nav-item.active .nav-icon { color: var(--green); }
.nav-icon {
  width: 18px; height: 18px;
  opacity: .7;
  flex-shrink: 0;
}
.nav-item.active .nav-icon { opacity: 1; }

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid var(--border);
}
.sidebar-user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: var(--r-sm);
}
.avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  background: var(--green-light);
  display: flex; align-items: center; justify-content: center;
  font-weight: 600;
  font-size: 13px;
  color: var(--green-dark);
  flex-shrink: 0;
}
.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.2;
}
.user-role {
  font-size: 11px;
  color: var(--text-muted);
}
.sidebar-logout {
  display: block;
  text-align: center;
  margin-top: 8px;
  padding: 7px;
  border-radius: var(--r-sm);
  font-size: 13px;
  color: var(--text-muted);
  text-decoration: none;
  transition: all .15s;
  border: 1px solid var(--border);
}
.sidebar-logout:hover {
  background: #fef2f2;
  color: #dc2626;
  border-color: #fecaca;
}

/* ── Main Content ── */
.main {
  margin-left: var(--sidebar-w);
  flex: 1;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* ── Top Header ── */
.topbar {
  background: var(--card);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 50;
}
.topbar-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.topbar-breadcrumb {
  font-size: 13px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
.topbar-breadcrumb span { color: var(--text-xs); }
.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.topbar-user-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px 5px 6px;
  border: 1px solid var(--border);
  border-radius: 100px;
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
}

/* Mobile menu toggle */
.menu-toggle {
  display: none;
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 6px 10px;
  cursor: pointer;
  font-size: 18px;
  color: var(--text);
}

/* ── Page Content ── */
.content {
  flex: 1;
  padding: 36px 40px;
  max-width: 980px;
  width: 100%;
}

.page-header {
  margin-bottom: 28px;
}
.page-header h1 {
  font-family: 'DM Serif Display', serif;
  font-size: 28px;
  font-weight: 400;
  letter-spacing: -.5px;
  color: var(--text);
  line-height: 1.2;
}
.page-header p {
  margin-top: 6px;
  font-size: 14px;
  color: var(--text-muted);
}

/* ── Cards ── */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 28px;
  box-shadow: var(--shadow-sm);
  margin-bottom: 20px;
}
.card-sm {
  padding: 20px;
  border-radius: var(--r-md);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: .3px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .8px;
}
.card-label {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

/* ── Form Elements ── */
.field {
  margin-bottom: 18px;
}
.field label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 6px;
}
.field label span {
  color: var(--text-muted);
  font-weight: 400;
}
.field input,
.field select,
.field textarea {
  width: 100%;
  padding: 10px 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  transition: border-color .15s, box-shadow .15s;
  outline: none;
  appearance: none;
}
.field input::placeholder,
.field textarea::placeholder { color: var(--text-xs); }
.field input:focus,
.field select:focus,
.field textarea:focus {
  border-color: var(--green);
  box-shadow: 0 0 0 3px rgba(22,163,74,.10);
  background: #fff;
}
.field select {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 36px;
  cursor: pointer;
}
.field textarea { resize: vertical; min-height: 88px; }
.field-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 5px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

/* ── Buttons ── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 10px 20px;
  border-radius: var(--r-sm);
  border: none;
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  transition: all .15s ease;
  white-space: nowrap;
  line-height: 1;
}
.btn:hover { transform: translateY(-1px); }
.btn:active { transform: translateY(0); }
.btn:disabled { opacity: .55; cursor: not-allowed; transform: none; }

.btn-primary {
  background: var(--green);
  color: #fff;
  box-shadow: 0 1px 3px rgba(22,163,74,.3);
}
.btn-primary:hover { background: #15803d; box-shadow: 0 4px 12px rgba(22,163,74,.35); }

.btn-secondary {
  background: var(--card);
  color: var(--text);
  border: 1px solid var(--border);
}
.btn-secondary:hover { background: var(--bg-alt); border-color: var(--border-mid); }

.btn-ghost {
  background: transparent;
  color: var(--text-muted);
  border: none;
}
.btn-ghost:hover { background: var(--bg-alt); color: var(--text); }

.btn-danger {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
}
.btn-danger:hover { background: #fee2e2; }

.btn-done {
  background: var(--green-light);
  color: var(--green-dark);
  border: 1px solid var(--green-mid);
}
.btn-done:hover { background: var(--green-mid); }

.btn-mark {
  background: var(--card);
  color: var(--text-muted);
  border: 1px solid var(--border);
}
.btn-mark:hover { border-color: var(--green); color: var(--green); background: var(--green-light); }

.btn-full { width: 100%; }
.btn-lg { padding: 13px 28px; font-size: 15px; }
.btn-sm { padding: 7px 14px; font-size: 13px; }
.btn-xs { padding: 5px 10px; font-size: 12px; }

.btn-icon {
  width: 32px; height: 32px;
  padding: 0;
  border-radius: 6px;
}

/* ── Alerts ── */
.alert {
  padding: 13px 16px;
  border-radius: var(--r-sm);
  font-size: 13.5px;
  margin-bottom: 18px;
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid;
}
.alert-success { background: var(--green-light); color: var(--green-dark); border-color: var(--green-mid); }
.alert-error   { background: #fef2f2; color: #dc2626; border-color: #fecaca; }
.alert-info    { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
.alert-warn    { background: #fffbeb; color: #92400e; border-color: #fde68a; }

/* ── Dashboard Table ── */
.systems-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
.systems-table th {
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--text-muted);
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
}
.systems-table td {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.systems-table tr:last-child td { border-bottom: none; }
.systems-table tbody tr {
  transition: background .12s;
}
.systems-table tbody tr:hover td { background: var(--bg); }

.goal-cell {
  font-weight: 500;
  color: var(--text);
  max-width: 200px;
}
.meta-cell { color: var(--text-muted); font-size: 13px; }
.date-cell { color: var(--text-muted); font-size: 13px; white-space: nowrap; }

/* ── Streak Badge ── */
.streak-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 100px;
  font-size: 12px;
  font-weight: 600;
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
  white-space: nowrap;
  min-width: 20px;
}
.streak-pill.empty {
  background: var(--bg-alt);
  color: var(--text-xs);
  border-color: var(--border);
  font-weight: 400;
}
.streak-broken {
  display: block;
  font-size: 11px;
  color: #dc2626;
  margin-top: 3px;
}

/* ── Today Cell ── */
.today-cell {
  white-space: nowrap;
}
.today-cell-inner {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* ── Action Buttons ── */
.action-group {
  display: flex;
  gap: 6px;
  align-items: center;
}

/* ── Result Output ── */
.result-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-md);
  overflow: hidden;
  margin-top: 28px;
}
.result-header {
  padding: 18px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.result-header-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--text-muted);
}
.result-body {
  padding: 28px;
  font-size: 14.5px;
  line-height: 1.85;
  white-space: pre-wrap;
  color: var(--text);
}
.result-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--border);
  background: var(--bg);
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

/* ── Auth Pages ── */
.auth-page {
  min-height: 100vh;
  background: var(--bg);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.auth-panel {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  padding: 44px 40px;
  width: 100%;
  max-width: 420px;
  box-shadow: var(--shadow-lg);
}
.auth-logo {
  text-align: center;
  margin-bottom: 32px;
}
.auth-logo-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px; height: 48px;
  background: var(--green);
  border-radius: 14px;
  color: white;
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 12px;
}
.auth-panel h2 {
  font-family: 'DM Serif Display', serif;
  font-size: 26px;
  font-weight: 400;
  text-align: center;
  color: var(--text);
  margin-bottom: 6px;
}
.auth-panel .subtitle {
  font-size: 14px;
  color: var(--text-muted);
  text-align: center;
  margin-bottom: 28px;
}
.auth-divider {
  text-align: center;
  margin: 20px 0;
  font-size: 13px;
  color: var(--text-muted);
}
.auth-switch {
  text-align: center;
  margin-top: 20px;
  font-size: 13px;
  color: var(--text-muted);
}
.auth-switch a { color: var(--green); text-decoration: none; font-weight: 600; }
.auth-switch a:hover { text-decoration: underline; }

/* ── Feedback ── */
.feedback-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 18px 20px;
  margin-bottom: 12px;
  transition: box-shadow .15s;
}
.feedback-card:hover { box-shadow: var(--shadow-sm); }
.feedback-author {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.feedback-author-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--green);
  display: inline-block;
}
.feedback-msg { font-size: 14px; color: var(--text-muted); line-height: 1.6; }
.feedback-reply {
  margin-top: 10px;
  padding: 10px 14px;
  background: var(--bg);
  border-left: 3px solid var(--green);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  font-size: 13px;
  color: var(--text-muted);
}

/* ── Empty States ── */
.empty-state {
  text-align: center;
  padding: 60px 20px;
}
.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
  opacity: .5;
}
.empty-state h3 {
  font-family: 'DM Serif Display', serif;
  font-size: 20px;
  font-weight: 400;
  margin-bottom: 8px;
  color: var(--text);
}
.empty-state p {
  font-size: 14px;
  color: var(--text-muted);
  max-width: 300px;
  margin: 0 auto 20px;
}

/* ── Stats Row ── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 18px 20px;
  box-shadow: var(--shadow-sm);
}
.stat-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.stat-value {
  font-family: 'DM Serif Display', serif;
  font-size: 28px;
  color: var(--text);
  line-height: 1;
}
.stat-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

/* ── Chips / Tags ── */
.chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 100px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--text-muted);
}

/* ── Utility ── */
.text-muted { color: var(--text-muted); }
.text-xs    { font-size: 12px; }
.text-sm    { font-size: 13px; }
.mt-4  { margin-top: 4px; }
.mt-8  { margin-top: 8px; }
.mt-16 { margin-top: 16px; }
.mt-24 { margin-top: 24px; }
.mb-4  { margin-bottom: 4px; }
.mb-8  { margin-bottom: 8px; }
.mb-16 { margin-bottom: 16px; }
.mb-24 { margin-bottom: 24px; }
.flex  { display: flex; }
.items-center { align-items: center; }
.gap-8  { gap: 8px; }
.gap-12 { gap: 12px; }

/* ── Mobile overlay ── */
.sidebar-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.3);
  z-index: 99;
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .sidebar {
    transform: translateX(-100%);
  }
  .sidebar.open {
    transform: translateX(0);
    box-shadow: var(--shadow-lg);
  }
  .sidebar-overlay.open { display: block; }
  .main { margin-left: 0; }
  .menu-toggle { display: flex; align-items: center; }
  .content { padding: 20px 16px; }
  .form-grid { grid-template-columns: 1fr; }
  .stats-row { grid-template-columns: 1fr; }
  .topbar { padding: 0 16px; }
  .systems-table th:nth-child(2),
  .systems-table td:nth-child(2) { display: none; }
}

/* ── Loading state ── */
@keyframes spin {
  to { transform: rotate(360deg); }
}
.btn-loading {
  position: relative;
  color: transparent !important;
  pointer-events: none;
}
.btn-loading::after {
  content: "";
  position: absolute;
  width: 16px; height: 16px;
  top: 50%; left: 50%;
  margin: -8px 0 0 -8px;
  border: 2px solid rgba(255,255,255,.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin .65s linear infinite;
}
.btn-primary.btn-loading::after {
  border-color: rgba(255,255,255,.3);
  border-top-color: #fff;
}
.btn-secondary.btn-loading::after {
  border-color: rgba(15,23,42,.15);
  border-top-color: var(--text);
}

/* ── Micro-interactions ── */
.btn {
  /* already has transition — extend it */
  transition: all .15s ease;
  user-select: none;
}
.btn:active:not(:disabled) {
  transform: scale(.97) translateY(0) !important;
  opacity: .9;
}
.btn-primary:active:not(:disabled) {
  box-shadow: 0 1px 3px rgba(22,163,74,.2) !important;
}
/* Inputs — smooth focus ring */
.field input, .field select, .field textarea {
  transition: border-color .15s ease, box-shadow .15s ease, background .15s ease;
}
/* Card hover lift */
.feedback-card {
  transition: box-shadow .18s ease, transform .18s ease;
}
.feedback-card:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}
/* Table row transition already set — add subtle left accent on active */
.systems-table tbody tr:hover td:first-child {
  box-shadow: inset 3px 0 0 var(--green);
}

/* ── First-time welcome banner ── */
.welcome-banner {
  background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
  border: 1px solid var(--green-mid);
  border-radius: var(--r-lg);
  padding: 24px 28px;
  margin-bottom: 24px;
  display: flex;
  align-items: flex-start;
  gap: 16px;
}
.welcome-banner-icon {
  font-size: 28px;
  flex-shrink: 0;
  line-height: 1;
  margin-top: 2px;
}
.welcome-banner h3 {
  font-family: 'DM Serif Display', serif;
  font-size: 18px;
  font-weight: 400;
  color: var(--green-dark);
  margin-bottom: 4px;
}
.welcome-banner p {
  font-size: 13.5px;
  color: #166534;
  line-height: 1.5;
  margin-bottom: 12px;
}
.welcome-banner .btn-primary {
  font-size: 13px;
  padding: 8px 18px;
}

/* ── Enhanced empty state ── */
.empty-state {
  text-align: center;
  padding: 72px 24px 60px;
  background: var(--card);
  border: 2px dashed var(--border);
  border-radius: var(--r-xl);
}
.empty-icon { font-size: 44px; margin-bottom: 14px; opacity: .6; }
.empty-state h3 {
  font-family: 'DM Serif Display', serif;
  font-size: 22px; font-weight: 400;
  color: var(--text); margin-bottom: 8px;
}
.empty-state p {
  font-size: 14px; color: var(--text-muted);
  max-width: 320px; margin: 0 auto 8px; line-height: 1.6;
}
.empty-hint {
  font-size: 12px;
  color: var(--text-xs);
  margin-bottom: 24px;
  font-style: italic;
}

/* ── Error alert — enhanced ── */
.alert-error {
  background: #fef2f2;
  color: #dc2626;
  border-color: #fecaca;
  border-left: 3px solid #dc2626;
}
.error-retry {
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  color: #dc2626;
  cursor: pointer;
  text-decoration: underline;
  background: none;
  border: none;
  padding: 0;
  flex-shrink: 0;
}
"""


# =======================================================
#  Page wrapper  (sidebar + topbar layout)
# =======================================================
def page(title, body, active="home"):
    username = session.get("username")

    # Build sidebar nav — only shown when logged in
    if username:
        def nav(href, icon_svg, label, key):
            cls = "nav-item active" if active == key else "nav-item"
            return f'''<a href="{href}" class="{cls}">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{icon_svg}</svg>
              {label}
            </a>'''

        sidebar_html = f'''
<aside class="sidebar" id="sidebar">
  <div class="sidebar-logo">
    <a href="/">
      <div class="logo-mark">C</div>
      <div>
        <div class="logo-text">Consc</div>
        <div class="logo-tagline">Behavior OS</div>
      </div>
    </a>
  </div>

  <nav class="sidebar-nav">
    <div class="nav-section-label">Workspace</div>
    {nav("/", '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>', "System Builder", "home")}
    {nav("/dashboard", '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>', "My Systems", "dashboard")}

    <div class="nav-section-label" style="margin-top:16px;">Community</div>
    {nav("/feedback", '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>', "Feedback", "feedback")}
  </nav>

  <div class="sidebar-footer">
    <div class="sidebar-user">
      <div class="avatar">{username[0].upper()}</div>
      <div>
        <div class="user-name">{username}</div>
        <div class="user-role">Free Plan</div>
      </div>
    </div>
    <a href="/logout" class="sidebar-logout">&#8592; Sign out</a>
  </div>
</aside>
<div class="sidebar-overlay" id="sidebar-overlay" onclick="closeSidebar()"></div>
'''

        topbar_html = f'''
<header class="topbar">
  <div class="flex items-center gap-8">
    <button class="menu-toggle" onclick="openSidebar()">&#9776;</button>
    <div class="topbar-breadcrumb">
      <span>Consc</span>
      <span style="color:var(--border)">&#47;</span>
      <strong style="color:var(--text)">{title}</strong>
    </div>
  </div>
  <div class="topbar-right">
    <div class="topbar-user-pill">
      <div class="avatar" style="width:24px;height:24px;font-size:11px;">{username[0].upper()}</div>
      {username}
    </div>
  </div>
</header>'''

        layout_open  = '<div class="layout">'
        layout_close = '</div>'
        main_open    = '<div class="main">'
        content_wrap = f'<div class="content">{body}</div>'
        main_close   = '</div>'

    else:
        # Unauthenticated — full-page centered layout (auth pages)
        sidebar_html = ""
        topbar_html  = ""
        layout_open  = ''
        layout_close = ''
        main_open    = ''
        content_wrap = body
        main_close   = ''

    sidebar_js = '''
<script>
function openSidebar() {
  document.getElementById("sidebar").classList.add("open");
  document.getElementById("sidebar-overlay").classList.add("open");
}
function closeSidebar() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sidebar-overlay").classList.remove("open");
}
</script>''' if username else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} &#8212; Consc</title>
  <style>{BASE_STYLE}</style>
</head>
<body>
{layout_open}
{sidebar_html}
{main_open}
{topbar_html}
{content_wrap}
{main_close}
{layout_close}
{sidebar_js}
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
            hashed = generate_password_hash(password, method='pbkdf2:sha256')
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
<div class="auth-page">
  <div class="auth-panel">
    <div class="auth-logo">
      <div class="auth-logo-mark">C</div>
      <h2>Create your account</h2>
      <p class="subtitle">Start correcting your behavior, not just tracking it.</p>
    </div>
    {err_html}
    <form method="POST">
      <div class="field">
        <label>Username</label>
        <input name="username" placeholder="e.g. alex123" required>
      </div>
      <div class="field">
        <label>Email</label>
        <input name="email" type="email" placeholder="you@email.com" required>
      </div>
      <div class="field">
        <label>Password <span>(min 6 characters)</span></label>
        <input name="password" type="password" placeholder="Choose a password" required>
      </div>
      <button class="btn btn-primary btn-full btn-lg" style="margin-top:6px;">
        Get Started
      </button>
    </form>
    <p class="auth-switch">Already have an account? <a href="/login">Sign in &rarr;</a></p>
  </div>
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
<div class="auth-page">
  <div class="auth-panel">
    <div class="auth-logo">
      <div class="auth-logo-mark">C</div>
      <h2>Welcome back</h2>
      <p class="subtitle">Your systems are waiting.</p>
    </div>
    {err_html}
    <form method="POST">
      <div class="field">
        <label>Email</label>
        <input name="email" type="email" placeholder="you@email.com" required>
      </div>
      <div class="field">
        <label>Password</label>
        <input name="password" type="password" placeholder="Your password" required>
      </div>
      <button class="btn btn-primary btn-full btn-lg" style="margin-top:6px;">
        Sign in
      </button>
    </form>
    <p class="auth-switch">No account yet? <a href="/signup">Create one free &rarr;</a></p>
  </div>
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
        # Clean up the raw OpenAI error string for display
        user_msg = str(error)
        if "auth" in user_msg.lower() or "api" in user_msg.lower():
            user_msg = "API key error. Check your OPENAI_API_KEY environment variable."
        elif "timeout" in user_msg.lower() or "connect" in user_msg.lower():
            user_msg = "Connection timed out. Please try again."
        elif len(user_msg) > 120:
            user_msg = "Something went wrong. Please try again in a moment."
        result_html = f'''
<div class="alert alert-error" style="align-items:flex-start; gap:12px;">
  <span style="font-size:16px; flex-shrink:0;">&#9888;</span>
  <div>
    <strong>Generation failed.</strong><br>
    <span style="font-size:13px;">{user_msg}</span>
  </div>
  <button class="error-retry" onclick="window.scrollTo(0,0)">Try again &uarr;</button>
</div>'''

    elif result:
        escaped = (result
                   .replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;"))
        result_html = f"""
<div class="result-card">
  <div class="result-header">
    <span class="result-header-label">&#10024; Your System is Ready</span>
    <div class="flex gap-8">
      <a href="/dashboard" class="btn btn-secondary btn-sm">&#128203; Dashboard</a>
      <form method="POST" action="/pdf_by_id" style="margin:0;">
        <input type="hidden" name="system_id" value="{saved_id}">
        <button class="btn btn-secondary btn-sm">&#128196; PDF</button>
      </form>
    </div>
  </div>
  <div class="result-body">{escaped}</div>
  <div class="result-footer">
    <a href="/dashboard" class="btn btn-primary">
      &#128293; Start Day 1
    </a>
    <span class="text-sm text-muted">Automatically saved to your systems.</span>
  </div>
</div>
"""

    body = f"""
<div class="page-header">
  <h1>Build your system</h1>
  <p>Be specific. The more honest you are, the more precise the output.</p>
</div>

<div class="card">
  <div class="card-header" style="margin-bottom:0; padding-bottom:0; border-bottom:none;">
    <span class="card-label">What are you trying to fix?</span>
  </div>

  <form method="POST" style="margin-top:20px;">
    <div class="form-grid">
      <div class="field">
        <label>Your Goal</label>
        <input name="goal" placeholder="e.g. Wake up at 6am every day" required>
      </div>
      <div class="field">
        <label>Book or Method</label>
        <input name="book" placeholder="e.g. Atomic Habits" required>
      </div>
    </div>

    <div class="form-grid">
      <div class="field">
        <label>What habit are you trying to quit?</label>
        <input name="struggle" placeholder="e.g. Scrolling until 2am" required>
      </div>
      <div class="field">
        <label>When do you fail? <span>(trigger or time)</span></label>
        <input name="why" placeholder="e.g. After dinner, when I'm tired" required>
      </div>
    </div>

    <div class="form-grid">
      <div class="field">
        <label>What are you procrastinating on?</label>
        <input name="custom" placeholder="e.g. Starting the gym routine">
      </div>
      <div class="field">
        <label>Your motivation</label>
        <input name="why" placeholder="e.g. I want more energy and discipline" required>
      </div>
    </div>

    <div class="form-grid" style="grid-template-columns: 120px 1fr; gap:16px;">
      <div class="field">
        <label>Daily time <span>(min)</span></label>
        <input name="daily_time" type="number" min="5" max="240" value="30">
      </div>
      <div class="field">
        <label>Difficulty</label>
        <select name="difficulty">
          <option>Easy</option>
          <option selected>Medium</option>
          <option>Hard</option>
        </select>
      </div>
    </div>

    <button id="gen-btn" class="btn btn-primary btn-lg" style="margin-top:4px; min-width:200px;">
      Generate My System &#8594;
    </button>
  </form>
</div>

{result_html}

<script>
(function() {{
  var form = document.querySelector('.card form[method="POST"]');
  var btn  = document.getElementById('gen-btn');
  if (!form || !btn) return;

  form.addEventListener('submit', function() {{
    // Slight delay so the browser's native validation runs first
    setTimeout(function() {{
      if (!form.checkValidity || form.checkValidity()) {{
        btn.classList.add('btn-loading');
        btn.disabled = true;
        btn.dataset.orig = btn.textContent;
        // Fallback: re-enable after 30s in case something goes wrong
        setTimeout(function() {{
          btn.classList.remove('btn-loading');
          btn.disabled = false;
        }}, 30000);
      }}
    }}, 0);
  }});
}})();
</script>
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

    is_first_visit = not rows  # used for welcome banner below

    if not rows:
        table_html = """
<div class="empty-state">
  <div class="empty-icon">&#127775;</div>
  <h3>You haven&#39;t created a system yet</h3>
  <p>Your first behavior system takes 60 seconds to generate.</p>
  <p class="empty-hint">Start with something simple &#8212; waking up early, reducing phone usage, or exercising daily.</p>
  <a href="/" class="btn btn-primary btn-lg">Create your first system &rarr;</a>
</div>"""
    else:
        # Count stats
        total = len(rows)
        completed_today = sum(1 for row in rows if get_today_completion(user_id, row["id"]))
        best_streak = max((get_streak(user_id, row["id"]) for row in rows), default=0)

        rows_html = ""
        for row in rows:
            try:
                dt = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
                date_str = dt.strftime("%b %d, %Y")
            except Exception:
                date_str = row["created_at"] or ""

            goal_safe = (row["goal"] or "").replace("<","&lt;").replace(">","&gt;")
            book_safe = (row["book"] or "").replace("<","&lt;").replace(">","&gt;")

            done   = get_today_completion(user_id, row["id"])
            streak = get_streak(user_id, row["id"])

            if done:
                btn_html = f'''<button class="btn btn-done btn-sm today-btn" data-id="{row['id']}" title="Click to undo" onclick="toggleToday(this, {row['id']})">&#10003; Completed</button>'''
            else:
                btn_html = f'''<button class="btn btn-mark btn-sm today-btn" data-id="{row['id']}" title="Mark as done for today" onclick="toggleToday(this, {row['id']})">Mark done</button>'''

            if streak > 0:
                streak_html = f'''<span class="streak-pill" data-sid="{row['id']}" title="{streak}-day streak">&#128293; {streak} day{"s" if streak != 1 else ""}</span>'''
            else:
                streak_html = f'''<span class="streak-pill empty" data-sid="{row['id']}">No streak</span>'''

            rows_html += f"""
<tr>
  <td class="goal-cell">{goal_safe}</td>
  <td class="meta-cell">{book_safe}</td>
  <td class="date-cell">{date_str}</td>
  <td class="today-cell">
    <div class="today-cell-inner">
      {btn_html}
      {streak_html}
    </div>
  </td>
  <td>
    <div class="action-group">
      <a href="/system/{row['id']}" class="btn btn-secondary btn-xs">View</a>
      <form method="POST" action="/pdf_by_id" style="margin:0;">
        <input type="hidden" name="system_id" value="{row['id']}">
        <button class="btn btn-secondary btn-xs">PDF</button>
      </form>
    </div>
  </td>
</tr>"""

        table_html = f"""
<div class="stats-row">
  <div class="stat-card">
    <div class="stat-label">Total Systems</div>
    <div class="stat-value">{total}</div>
    <div class="stat-sub">behavior programs</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Done Today</div>
    <div class="stat-value">{completed_today}</div>
    <div class="stat-sub">of {total} systems</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Best Streak</div>
    <div class="stat-value">{best_streak}</div>
    <div class="stat-sub">consecutive days</div>
  </div>
</div>

<div class="card" style="padding:0; overflow:hidden;">
  <table class="systems-table">
    <thead>
      <tr>
        <th>Goal</th>
        <th>Method</th>
        <th>Created</th>
        <th>Today</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""

    welcome_html = ""
    if is_first_visit:
        welcome_html = f"""
<div class="welcome-banner">
  <div class="welcome-banner-icon">&#128075;</div>
  <div>
    <h3>Welcome, {session.get("username", "there")}!</h3>
    <p>This is your behavior dashboard. Build a system, mark it done each day, and watch your streak grow.</p>
    <a href="/" class="btn btn-primary">Start by creating your first system &rarr;</a>
  </div>
</div>"""

    body = f"""
<div class="page-header" style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
  <div>
    <h1>My Systems</h1>
    <p>Mark each system done daily to build your streak.</p>
  </div>
  <a href="/" class="btn btn-primary">+ New System</a>
</div>

{welcome_html}
{table_html}

<script>
function toggleToday(btn, systemId) {{
  btn.disabled = true;
  var orig = btn.innerHTML;

  fetch('/complete_today/' + systemId, {{ method: 'POST' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{

      if (data.completed) {{
        btn.innerHTML  = '&#10003; Completed';
        btn.className  = 'btn btn-done btn-sm today-btn';
        btn.title      = 'Click to undo';
      }} else {{
        btn.innerHTML  = 'Mark done';
        btn.className  = 'btn btn-mark btn-sm today-btn';
        btn.title      = 'Mark as done for today';
      }}

      // Update streak pill in same today-cell-inner
      var pill = btn.parentElement.querySelector('.streak-pill[data-sid="' + systemId + '"]');
      if (pill) {{
        if (data.streak > 0) {{
          var days = data.streak === 1 ? 'day' : 'days';
          pill.innerHTML = '&#128293; ' + data.streak + ' ' + days;
          pill.title     = data.streak + '-day streak';
          pill.className = 'streak-pill';
        }} else {{
          pill.innerHTML = 'No streak';
          pill.title     = 'No streak yet';
          pill.className = 'streak-pill empty';
        }}
      }}
    }})
    .catch(function() {{
      btn.innerHTML = '&#9888; Retry';
      btn.className = 'btn btn-danger btn-sm';
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
<div class="flex gap-8 mb-16" style="margin-bottom:20px;">
  <a href="/dashboard" class="btn btn-secondary btn-sm">&larr; My Systems</a>
</div>

<div class="card" style="margin-bottom:16px;">
  <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:12px; align-items:flex-start;">
    <div>
      <div class="card-title" style="margin-bottom:6px;">System #{row['id']}</div>
      <div style="font-family:'DM Serif Display',serif; font-size:22px; color:var(--text); margin-bottom:6px;">{goal_safe}</div>
      <div class="flex gap-8 items-center" style="flex-wrap:wrap;">
        <span class="chip">&#128218; {book_safe}</span>
        <span class="chip">&#128197; {date_str}</span>
      </div>
    </div>
    <form method="POST" action="/pdf_by_id">
      <input type="hidden" name="system_id" value="{row['id']}">
      <button class="btn btn-secondary btn-sm">&#128196; Download PDF</button>
    </form>
  </div>
</div>

<div class="result-card">
  <div class="result-body">{escaped}</div>
  <div class="result-footer">
    <a href="/dashboard" class="btn btn-primary">&#128293; Mark Done Today</a>
    <a href="/" class="btn btn-secondary">+ New System</a>
  </div>
</div>
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
<div class="feedback-card">
  <div class="feedback-author">
    <span class="feedback-author-dot"></span>{row['name']}
  </div>
  <div class="feedback-msg">{msg}</div>
  {reply_html}
</div>"""

    if not items_html:
        items_html = """
<div class="empty-state" style="padding:40px 20px;">
  <div class="empty-icon">&#128172;</div>
  <p>No feedback yet &#8212; be the first!</p>
</div>"""

    body = f"""
<div class="page-header">
  <h1>Feedback</h1>
  <p>Feature requests, bugs, or praise &#8212; all welcome.</p>
</div>

<div class="card" style="margin-bottom:24px;">
  <div class="card-label" style="margin-bottom:18px;">Send a message</div>
  <form method="POST" action="/feedback_submit">
    <div class="field">
      <label>Your name</label>
      <input name="name" placeholder="e.g. Alex" required>
    </div>
    <div class="field">
      <label>Message</label>
      <textarea name="message" placeholder="What's on your mind?" required></textarea>
    </div>
    <button class="btn btn-primary">Send Feedback</button>
  </form>
</div>

<div class="card-label" style="margin-bottom:14px; color:var(--text-muted);">WHAT PEOPLE ARE SAYING</div>
{items_html}
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
<div class="page-header"><h1>Thank you!</h1></div>
<div class="alert alert-success">&#10003; We read every message. Thanks for taking the time.</div>
<div class="flex gap-8 mt-16">
  <a href="/feedback" class="btn btn-secondary">&larr; Back to Feedback</a>
  <a href="/" class="btn btn-primary">Go to Generator &rarr;</a>
</div>
"""
    return page("Feedback Received", body)


# =======================================================
#  Run
# =======================================================
if __name__ == "__main__":
    debug_mode = os.getenv("DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode)