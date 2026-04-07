"""
consc.app  --  Full-stack Flask app  (PREMIUM EDITION)
======================================================
Features:
  * User auth  (signup / login / logout)
  * Password hashing via werkzeug
  * Flask sessions for login state
  * Protected routes  (login required)
  * 3-step onboarding for first-time users
  * AI system generator with cleaned output
  * Systems linked to logged-in user
  * Personal dashboard with streak counters
  * Progress page  (weekly stats, calendar, totals)
  * Settings page  (account / preferences / danger zone)
  * Branded PDF download
  * Feedback wall
  * Premium white + green UI, fully responsive

Run locally:
  pip install flask openai fpdf2 werkzeug
  export OPENAI_API_KEY="sk-..."
  export SECRET_KEY="something-long-and-random"
  python app_web.py
"""

import io
import os
import re
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
#  AI output cleaner
# =======================================================
def clean_ai_output(text: str) -> str:
    """
    Strip markdown noise from GPT output so it renders cleanly in HTML and PDF.
    Removes #, ##, ###, **bold**, *italic*, `code`, leading bullets, and
    collapses runs of blank lines.
    """
    if not text:
        return ""

    # Remove heading hashes at line start
    text = re.sub(r'^\s{0,3}#{1,6}\s*', '', text, flags=re.MULTILINE)

    # Remove bold/italic wrappers but keep the inner text
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Convert "- " or "* " bullets to a clean bullet
    text = re.sub(r'^\s*[-*]\s+', '• ', text, flags=re.MULTILINE)

    # Collapse 3+ newlines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Strip trailing whitespace per line
    text = '\n'.join(line.rstrip() for line in text.split('\n'))

    return text.strip()


# =======================================================
#  Daily progress helpers
# =======================================================
def get_today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def get_today_completion(user_id: int, system_id: int) -> bool:
    conn = get_db()
    row = conn.execute(
        """SELECT completed FROM daily_progress
           WHERE user_id = ? AND system_id = ? AND date = ?""",
        (user_id, system_id, get_today())
    ).fetchone()
    conn.close()
    return bool(row and row["completed"])


def get_streak(user_id: int, system_id: int) -> int:
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

    completed_dates = {row["date"] for row in rows}
    today = datetime.utcnow().date()

    if today.strftime("%Y-%m-%d") in completed_dates:
        check = today
    else:
        check = today - timedelta(days=1)

    streak = 0
    while check.strftime("%Y-%m-%d") in completed_dates:
        streak += 1
        check  -= timedelta(days=1)

    return streak


def get_week_stats(user_id: int, system_id: int):
    """Return (completed_count, [bool, bool, ...] for last 7 days)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT date FROM daily_progress
           WHERE user_id = ? AND system_id = ? AND completed = 1""",
        (user_id, system_id)
    ).fetchall()
    conn.close()
    completed_dates = {r["date"] for r in rows}

    today = datetime.utcnow().date()
    days = []
    for offset in range(6, -1, -1):  # 6 days ago → today
        d = today - timedelta(days=offset)
        days.append({
            "date": d.strftime("%Y-%m-%d"),
            "label": d.strftime("%a")[0],
            "done": d.strftime("%Y-%m-%d") in completed_dates,
        })
    completed = sum(1 for d in days if d["done"])
    return completed, days


def get_total_completions(user_id: int) -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM daily_progress WHERE user_id = ? AND completed = 1",
        (user_id,)
    ).fetchone()
    conn.close()
    return row["n"] if row else 0


# =======================================================
#  Auth decorator
# =======================================================
def login_required(f):
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
  --green:       #16a34a;
  --green-light: #dcfce7;
  --green-mid:   #bbf7d0;
  --green-dark:  #14532d;

  --bg:          #f8fafc;
  --bg-alt:      #f1f5f9;
  --card:        #ffffff;
  --sidebar:     #ffffff;

  --text:        #0f172a;
  --text-muted:  #64748b;
  --text-xs:     #94a3b8;

  --border:      #e2e8f0;
  --border-mid:  #cbd5e1;
  --shadow-sm:   0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
  --shadow-md:   0 4px 16px rgba(0,0,0,.08), 0 2px 6px rgba(0,0,0,.05);
  --shadow-lg:   0 12px 40px rgba(0,0,0,.10), 0 4px 12px rgba(0,0,0,.06);

  --r-sm: 8px;
  --r-md: 12px;
  --r-lg: 16px;
  --r-xl: 20px;

  --sidebar-w: 240px;
}

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
.layout { display: flex; min-height: 100vh; }

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

.sidebar-logo { padding: 24px 20px 20px; border-bottom: 1px solid var(--border); }
.sidebar-logo a { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--text); }
.logo-mark {
  width: 32px; height: 32px;
  background: var(--green);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: white; font-size: 16px; font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(22,163,74,.3);
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

.sidebar-nav { flex: 1; padding: 12px; overflow-y: auto; }

.nav-section-label {
  font-size: 10px; font-weight: 600; letter-spacing: 1px;
  text-transform: uppercase; color: var(--text-xs);
  padding: 8px 8px 6px; margin-top: 8px;
}

.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 10px;
  border-radius: var(--r-sm);
  text-decoration: none;
  color: var(--text-muted);
  font-size: 14px; font-weight: 500;
  transition: all .15s ease;
  margin-bottom: 2px;
}
.nav-item:hover { background: var(--bg-alt); color: var(--text); }
.nav-item.active { background: var(--green-light); color: var(--green-dark); font-weight: 600; }
.nav-item.active .nav-icon { color: var(--green); opacity: 1; }
.nav-icon { width: 18px; height: 18px; opacity: .7; flex-shrink: 0; }

.sidebar-footer { padding: 16px; border-top: 1px solid var(--border); }
.sidebar-user { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: var(--r-sm); }
.avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  background: var(--green-light);
  display: flex; align-items: center; justify-content: center;
  font-weight: 600; font-size: 13px;
  color: var(--green-dark);
  flex-shrink: 0;
}
.user-name { font-size: 13px; font-weight: 600; color: var(--text); line-height: 1.2; }
.user-role { font-size: 11px; color: var(--text-muted); }
.sidebar-logout {
  display: block; text-align: center;
  margin-top: 8px; padding: 7px;
  border-radius: var(--r-sm);
  font-size: 13px; color: var(--text-muted);
  text-decoration: none;
  transition: all .15s;
  border: 1px solid var(--border);
}
.sidebar-logout:hover { background: #fef2f2; color: #dc2626; border-color: #fecaca; }

/* ── Main ── */
.main {
  margin-left: var(--sidebar-w);
  flex: 1;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  background: var(--card);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky; top: 0; z-index: 50;
}
.topbar-breadcrumb { font-size: 13px; color: var(--text-muted); display: flex; align-items: center; gap: 6px; }
.topbar-breadcrumb span { color: var(--text-xs); }
.topbar-right { display: flex; align-items: center; gap: 12px; }
.topbar-user-pill {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 12px 5px 6px;
  border: 1px solid var(--border);
  border-radius: 100px;
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
}

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

.content { flex: 1; padding: 36px 40px; max-width: 980px; width: 100%; }

.page-header { margin-bottom: 28px; }
.page-header h1 {
  font-family: 'DM Serif Display', serif;
  font-size: 28px; font-weight: 400;
  letter-spacing: -.5px;
  color: var(--text);
  line-height: 1.2;
}
.page-header p { margin-top: 6px; font-size: 14px; color: var(--text-muted); }

/* ── Cards ── */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 28px;
  box-shadow: var(--shadow-sm);
  margin-bottom: 20px;
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
  font-size: 13px; font-weight: 600;
  letter-spacing: .8px;
  color: var(--text-muted);
  text-transform: uppercase;
}
.card-label { font-size: 15px; font-weight: 600; color: var(--text); }

/* ── Form ── */
.field { margin-bottom: 18px; }
.field label {
  display: block;
  font-size: 13px; font-weight: 500;
  color: var(--text);
  margin-bottom: 6px;
}
.field label span { color: var(--text-muted); font-weight: 400; }
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
  transition: border-color .15s, box-shadow .15s, background .15s;
  outline: none;
  appearance: none;
}
.field input::placeholder, .field textarea::placeholder { color: var(--text-xs); }
.field input:focus, .field select:focus, .field textarea:focus {
  border-color: var(--green);
  box-shadow: 0 0 0 3px rgba(22,163,74,.10);
  background: #fff;
}
.field input:disabled { background: var(--bg-alt); color: var(--text-muted); cursor: not-allowed; }
.field select {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 36px;
  cursor: pointer;
}
.field textarea { resize: vertical; min-height: 88px; }
.field-hint { font-size: 12px; color: var(--text-muted); margin-top: 5px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

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
  font-size: 14px; font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  transition: all .15s ease;
  white-space: nowrap;
  line-height: 1;
  user-select: none;
}
.btn:hover { transform: translateY(-1px); }
.btn:active:not(:disabled) { transform: scale(.97) translateY(0); opacity: .9; }
.btn:disabled { opacity: .55; cursor: not-allowed; transform: none; }

.btn-primary { background: var(--green); color: #fff; box-shadow: 0 1px 3px rgba(22,163,74,.3); }
.btn-primary:hover { background: #15803d; box-shadow: 0 4px 12px rgba(22,163,74,.35); }

.btn-secondary { background: var(--card); color: var(--text); border: 1px solid var(--border); }
.btn-secondary:hover { background: var(--bg-alt); border-color: var(--border-mid); }

.btn-ghost { background: transparent; color: var(--text-muted); border: none; }
.btn-ghost:hover { background: var(--bg-alt); color: var(--text); }

.btn-danger { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }
.btn-danger:hover { background: #fee2e2; }

.btn-done { background: var(--green-light); color: var(--green-dark); border: 1px solid var(--green-mid); }
.btn-done:hover { background: var(--green-mid); }

.btn-mark { background: var(--card); color: var(--text-muted); border: 1px solid var(--border); }
.btn-mark:hover { border-color: var(--green); color: var(--green); background: var(--green-light); }

.btn-full { width: 100%; }
.btn-lg { padding: 13px 28px; font-size: 15px; }
.btn-sm { padding: 7px 14px; font-size: 13px; }
.btn-xs { padding: 5px 10px; font-size: 12px; }

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
.alert-error   { background: #fef2f2; color: #dc2626; border-color: #fecaca; border-left: 3px solid #dc2626; }
.alert-info    { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
.alert-warn    { background: #fffbeb; color: #92400e; border-color: #fde68a; }
.error-retry {
  margin-left: auto;
  font-size: 12px; font-weight: 600;
  color: #dc2626;
  cursor: pointer;
  text-decoration: underline;
  background: none; border: none; padding: 0;
  flex-shrink: 0;
}

/* ── Dashboard table ── */
.systems-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.systems-table th {
  text-align: left;
  font-size: 11px; font-weight: 600;
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
.systems-table tbody tr { transition: background .12s; }
.systems-table tbody tr:hover td { background: var(--bg); }
.systems-table tbody tr:hover td:first-child { box-shadow: inset 3px 0 0 var(--green); }

.goal-cell { font-weight: 500; color: var(--text); max-width: 200px; }
.meta-cell { color: var(--text-muted); font-size: 13px; }
.date-cell { color: var(--text-muted); font-size: 13px; white-space: nowrap; }

/* ── Streak pill ── */
.streak-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 100px;
  font-size: 12px; font-weight: 600;
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
  white-space: nowrap;
}
.streak-pill.empty {
  background: var(--bg-alt);
  color: var(--text-xs);
  border-color: var(--border);
  font-weight: 400;
}

.today-cell { white-space: nowrap; }
.today-cell-inner { display: flex; flex-direction: column; gap: 4px; }
.action-group { display: flex; gap: 6px; align-items: center; }

/* ── Result card ── */
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
  font-size: 12px; font-weight: 600;
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
  font-family: 'DM Sans', sans-serif;
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

/* ── Auth pages — split layout ── */
.auth-split {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  background: var(--bg);
}
.auth-left {
  background: linear-gradient(160deg, #14532d 0%, #16a34a 100%);
  color: #fff;
  padding: 64px 56px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
  overflow: hidden;
}
.auth-left::before {
  content: "";
  position: absolute;
  top: -100px; right: -100px;
  width: 360px; height: 360px;
  background: radial-gradient(circle, rgba(255,255,255,.08) 0%, transparent 70%);
  border-radius: 50%;
}
.auth-left::after {
  content: "";
  position: absolute;
  bottom: -120px; left: -80px;
  width: 320px; height: 320px;
  background: radial-gradient(circle, rgba(255,255,255,.05) 0%, transparent 70%);
  border-radius: 50%;
}
.auth-brand {
  display: flex; align-items: center; gap: 12px;
  font-family: 'DM Serif Display', serif;
  font-size: 22px;
  position: relative;
}
.auth-brand-mark {
  width: 38px; height: 38px;
  background: #fff;
  color: var(--green-dark);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 18px;
}
.auth-headline { position: relative; }
.auth-headline h1 {
  font-family: 'DM Serif Display', serif;
  font-size: 40px; font-weight: 400;
  line-height: 1.15; letter-spacing: -.5px;
  margin-bottom: 16px;
}
.auth-headline p {
  font-size: 16px; line-height: 1.6;
  opacity: .9; max-width: 420px;
}
.auth-features {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 32px;
}
.auth-feature {
  display: flex; align-items: flex-start; gap: 12px;
  font-size: 14px;
  opacity: .95;
}
.auth-feature-dot {
  width: 22px; height: 22px;
  background: rgba(255,255,255,.18);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px;
  flex-shrink: 0;
  margin-top: 1px;
}
.auth-footer-note { position: relative; font-size: 12px; opacity: .7; }
.auth-right { display: flex; align-items: center; justify-content: center; padding: 40px 32px; }
.auth-panel {
  background: var(--card);
  width: 100%;
  max-width: 380px;
}
.auth-panel h2 {
  font-family: 'DM Serif Display', serif;
  font-size: 26px; font-weight: 400;
  color: var(--text);
  margin-bottom: 6px;
}
.auth-sub { font-size: 14px; color: var(--text-muted); margin-bottom: 22px; }
.auth-switch {
  text-align: center;
  margin-top: 20px;
  font-size: 13px;
  color: var(--text-muted);
}
.auth-switch a { color: var(--green); text-decoration: none; font-weight: 600; }
.auth-switch a:hover { text-decoration: underline; }

/* Standalone (onboarding) auth panel */
.auth-page {
  min-height: 100vh;
  background: var(--bg);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.auth-page .auth-panel {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  padding: 44px 40px;
  max-width: 440px;
  box-shadow: var(--shadow-lg);
}
.auth-logo { text-align: center; margin-bottom: 24px; }
.auth-logo-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px; height: 48px;
  background: var(--green);
  border-radius: 14px;
  color: white;
  font-size: 22px; font-weight: 700;
  box-shadow: 0 4px 14px rgba(22,163,74,.3);
}

/* ── Feedback ── */
.feedback-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 18px 20px;
  margin-bottom: 12px;
  transition: box-shadow .18s ease, transform .18s ease;
}
.feedback-card:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
.feedback-author {
  font-size: 13px; font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
  display: flex; align-items: center; gap: 8px;
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

/* ── Empty states ── */
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
.empty-hint { font-size: 12px; color: var(--text-xs); margin-bottom: 24px; font-style: italic; }

/* ── Stats row ── */
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
  font-size: 11px; font-weight: 600;
  letter-spacing: .8px; text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.stat-value {
  font-family: 'DM Serif Display', serif;
  font-size: 28px;
  color: var(--text);
  line-height: 1;
}
.stat-sub { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

/* ── Chips ── */
.chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 100px;
  font-size: 12px; font-weight: 500;
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--text-muted);
}

/* ── Welcome banner ── */
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
.welcome-banner-icon { font-size: 28px; flex-shrink: 0; line-height: 1; margin-top: 2px; }
.welcome-banner h3 {
  font-family: 'DM Serif Display', serif;
  font-size: 18px; font-weight: 400;
  color: var(--green-dark); margin-bottom: 4px;
}
.welcome-banner p {
  font-size: 13.5px; color: #166534;
  line-height: 1.5; margin-bottom: 12px;
}
.welcome-banner .btn-primary { font-size: 13px; padding: 8px 18px; }

/* ── Progress page — week dots ── */
.week-strip {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 16px;
  align-items: center;
  padding: 16px;
  background: var(--bg);
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  margin-top: 12px;
}
.week-strip-info { font-size: 13px; color: var(--text-muted); }
.week-strip-info strong { color: var(--text); font-size: 14px; }
.week-dots { display: flex; gap: 8px; }
.week-dot {
  width: 28px; height: 28px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700;
  background: var(--bg-alt);
  color: var(--text-xs);
  border: 1px solid var(--border);
  transition: all .2s ease;
}
.week-dot.done {
  background: var(--green);
  color: #fff;
  border-color: var(--green);
  box-shadow: 0 2px 6px rgba(22,163,74,.35);
}
.week-dot.today { outline: 2px solid var(--green); outline-offset: 2px; }

.progress-system-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 22px 24px;
  margin-bottom: 16px;
  box-shadow: var(--shadow-sm);
  transition: all .15s ease;
}
.progress-system-card:hover { box-shadow: var(--shadow-md); }
.progress-system-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
}
.progress-system-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}
.progress-system-sub { font-size: 12px; color: var(--text-muted); }
.progress-bar-track {
  height: 6px;
  background: var(--bg-alt);
  border-radius: 100px;
  overflow: hidden;
  margin-top: 14px;
}
.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--green) 0%, #22c55e 100%);
  border-radius: 100px;
  transition: width .5s ease;
}

/* ── Settings danger card ── */
.danger-card { border-color: #fecaca !important; }
.danger-card .card-header { border-bottom-color: #fecaca !important; }
.danger-card .card-title { color: #dc2626 !important; }

/* ── Mobile overlay ── */
.sidebar-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.3);
  z-index: 99;
}

/* ── Loading ── */
@keyframes spin { to { transform: rotate(360deg); } }
.btn-loading { position: relative; color: transparent !important; pointer-events: none; }
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

/* ── Utility ── */
.text-muted { color: var(--text-muted); }
.text-sm { font-size: 13px; }
.mt-16 { margin-top: 16px; }
.mb-16 { margin-bottom: 16px; }
.flex { display: flex; }
.items-center { align-items: center; }
.gap-8 { gap: 8px; }
.gap-12 { gap: 12px; }

/* ── Responsive ── */
@media (max-width: 880px) {
  .auth-split { grid-template-columns: 1fr; }
  .auth-left { padding: 40px 28px; min-height: auto; }
  .auth-headline h1 { font-size: 28px; }
  .auth-features { display: none; }
}
@media (max-width: 768px) {
  .sidebar { transform: translateX(-100%); }
  .sidebar.open { transform: translateX(0); box-shadow: var(--shadow-lg); }
  .sidebar-overlay.open { display: block; }
  .main { margin-left: 0; }
  .menu-toggle { display: flex; align-items: center; }
  .content { padding: 20px 16px; }
  .form-grid { grid-template-columns: 1fr; }
  .stats-row { grid-template-columns: 1fr; }
  .topbar { padding: 0 16px; }
  .systems-table th:nth-child(2),
  .systems-table td:nth-child(2) { display: none; }
  .week-strip { grid-template-columns: 1fr; }
}
"""


# =======================================================
#  Page wrapper  (sidebar + topbar layout)
# =======================================================
def page(title, body, active="home"):
    username = session.get("username")

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
    {nav("/progress", '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>', "Progress", "progress")}

    <div class="nav-section-label" style="margin-top:16px;">Account</div>
    {nav("/feedback", '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>', "Feedback", "feedback")}
    {nav("/settings", '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>', "Settings", "settings")}
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
#  Auth helpers — split panel
# =======================================================
def _auth_left_panel():
    return """
    <div class="auth-left">
      <div class="auth-brand">
        <div class="auth-brand-mark">C</div>
        <span>Consc</span>
      </div>

      <div class="auth-headline">
        <h1>You already know what to do.<br>You just don't do it.</h1>
        <p>Consc turns self-help knowledge into daily execution systems &mdash;
           so you finally break the habit loop instead of reading about it.</p>

        <div class="auth-features">
          <div class="auth-feature">
            <div class="auth-feature-dot">&#10003;</div>
            <div><strong>Break bad habits</strong><br>
              <span style="opacity:.75;">Identify your trigger, replace the loop.</span></div>
          </div>
          <div class="auth-feature">
            <div class="auth-feature-dot">&#10003;</div>
            <div><strong>Beat procrastination</strong><br>
              <span style="opacity:.75;">Get a concrete daily plan, not vague advice.</span></div>
          </div>
          <div class="auth-feature">
            <div class="auth-feature-dot">&#10003;</div>
            <div><strong>Track streaks</strong><br>
              <span style="opacity:.75;">Show up daily. Watch the streak grow.</span></div>
          </div>
        </div>
      </div>

      <div class="auth-footer-note">&copy; Consc &mdash; Behavior OS for people who keep restarting.</div>
    </div>
    """


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
<div class="auth-split">
  {_auth_left_panel()}
  <div class="auth-right">
    <div class="auth-panel">
      <h2>Create your account</h2>
      <p class="auth-sub">Start correcting your behavior, not just tracking it.</p>
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
<div class="auth-split">
  {_auth_left_panel()}
  <div class="auth-right">
    <div class="auth-panel">
      <h2>Welcome back</h2>
      <p class="auth-sub">Your systems are waiting.</p>
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
#  ONBOARDING   /onboarding
# =======================================================
@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    try:
        step = int(request.values.get("step", 1))
    except ValueError:
        step = 1
    if step < 1 or step > 3:
        step = 1

    if request.method == "POST":
        if step == 1:
            session["onb_struggle"] = request.form.get("struggle", "").strip()
            return redirect(url_for("onboarding", step=2))
        if step == 2:
            session["onb_trigger"] = request.form.get("trigger", "").strip()
            return redirect(url_for("onboarding", step=3))
        if step == 3:
            session["onb_procrastinate"] = request.form.get("procrastinate", "").strip()
            session["onb_done"] = True
            return redirect(url_for("index"))

    progress = int((step / 3) * 100)

    if step == 1:
        form_html = """
        <h2 style="text-align:center; font-family:'DM Serif Display',serif; font-size:24px; margin-bottom:6px;">What habit are you trying to quit?</h2>
        <p class="auth-sub" style="text-align:center;">Be specific. Vague goals fail.</p>
        <form method="POST">
          <input type="hidden" name="step" value="1">
          <div class="field">
            <input name="struggle" placeholder="e.g. Scrolling Instagram until 2am" required autofocus>
          </div>
          <button class="btn btn-primary btn-full btn-lg">Next &rarr;</button>
        </form>
        """
    elif step == 2:
        form_html = """
        <h2 style="text-align:center; font-family:'DM Serif Display',serif; font-size:24px; margin-bottom:6px;">When or where do you fail?</h2>
        <p class="auth-sub" style="text-align:center;">Most failure happens at predictable moments.</p>
        <form method="POST">
          <input type="hidden" name="step" value="2">
          <div class="field">
            <input name="trigger" placeholder="e.g. After dinner, lying in bed" required autofocus>
          </div>
          <button class="btn btn-primary btn-full btn-lg">Next &rarr;</button>
        </form>
        """
    else:
        form_html = """
        <h2 style="text-align:center; font-family:'DM Serif Display',serif; font-size:24px; margin-bottom:6px;">What are you procrastinating on?</h2>
        <p class="auth-sub" style="text-align:center;">The thing you keep avoiding but know matters.</p>
        <form method="POST">
          <input type="hidden" name="step" value="3">
          <div class="field">
            <input name="procrastinate" placeholder="e.g. Starting my gym routine" required autofocus>
          </div>
          <button class="btn btn-primary btn-full btn-lg">Build my system &rarr;</button>
        </form>
        <p class="auth-sub" style="margin-top:18px; font-style:italic; text-align:center;">
          "You don't fail because of motivation. You fail because you don't have a system."
        </p>
        """

    body = f"""
<div class="auth-page">
  <div class="auth-panel">
    <div class="auth-logo">
      <div class="auth-logo-mark">C</div>
    </div>
    <div style="height:6px; background:var(--bg-alt); border-radius:100px; margin-bottom:18px; overflow:hidden;">
      <div style="height:100%; width:{progress}%; background:var(--green); transition:width .4s ease;"></div>
    </div>
    <div style="text-align:center; font-size:11px; color:var(--text-muted); margin-bottom:22px; letter-spacing:1px; font-weight:600;">
      STEP {step} OF 3
    </div>
    {form_html}
  </div>
</div>
"""
    return page("Get Started", body)


# =======================================================
#  GENERATOR   /
# =======================================================
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    user_id = session["user_id"]

    # First-time user → onboarding
    conn = get_db()
    has_systems = conn.execute(
        "SELECT 1 FROM systems WHERE user_id = ? LIMIT 1", (user_id,)
    ).fetchone()
    conn.close()
    if not has_systems and not session.get("onb_done"):
        return redirect(url_for("onboarding"))

    # Onboarding prefill (consume on GET only)
    if request.method == "GET":
        onb_struggle      = session.pop("onb_struggle",      "")
        onb_trigger       = session.pop("onb_trigger",       "")
        onb_procrastinate = session.pop("onb_procrastinate", "")
    else:
        onb_struggle = onb_trigger = onb_procrastinate = ""

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

Respond with exactly these 6 sections. Be specific, not generic.
Use plain text only — no markdown symbols, no asterisks, no hashtags.

1. Identity Shift
   The new identity this person must adopt. One clear statement plus 2-3 supporting beliefs.

2. Daily Plan ({daily_time}-minute version)
   A concrete step-by-step routine that fits in {daily_time} minutes per day.

3. Weekly Plan
   Mon to Sun: one concrete action per day, building the habit progressively.

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
            result = clean_ai_output(response.choices[0].message.content)

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
            error = str(e)

    result_html = ""
    if error:
        user_msg = error
        low = user_msg.lower()
        if "auth" in low or "api" in low or "key" in low:
            user_msg = "API key error. Check your OPENAI_API_KEY environment variable."
        elif "timeout" in low or "connect" in low:
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
      <a href="/dashboard" class="btn btn-secondary btn-sm">Dashboard</a>
      <form method="POST" action="/pdf_by_id" style="margin:0;">
        <input type="hidden" name="system_id" value="{saved_id}">
        <button class="btn btn-secondary btn-sm">Download PDF</button>
      </form>
    </div>
  </div>
  <div class="result-body">{escaped}</div>
  <div class="result-footer">
    <a href="/dashboard" class="btn btn-primary">Start Day 1 &rarr;</a>
    <span class="text-sm text-muted">Automatically saved to your systems.</span>
  </div>
</div>
"""

    body = f"""
<div class="page-header">
  <h1>Build your execution system</h1>
  <p>Be specific. The more honest you are, the more precise the output. <em>This is not motivation &mdash; this is a system.</em></p>
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
        <input name="struggle" value="{onb_struggle}" placeholder="e.g. Scrolling until 2am" required>
      </div>
      <div class="field">
        <label>When do you fail? <span>(trigger or time)</span></label>
        <input name="why" value="{onb_trigger}" placeholder="e.g. After dinner, when I'm tired" required>
      </div>
    </div>

    <div class="form-grid">
      <div class="field">
        <label>What are you procrastinating on?</label>
        <input name="custom" value="{onb_procrastinate}" placeholder="e.g. Starting the gym routine">
      </div>
      <div class="field">
        <label>Your motivation</label>
        <input name="motivation" placeholder="e.g. I want more energy and discipline">
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

    <button id="gen-btn" class="btn btn-primary btn-lg" style="margin-top:4px; min-width:240px;">
      Build My Execution System &rarr;
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
    setTimeout(function() {{
      if (!form.checkValidity || form.checkValidity()) {{
        btn.classList.add('btn-loading');
        btn.disabled = true;
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

    is_first_visit = not rows

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
                btn_html = f'<button class="btn btn-done btn-sm today-btn" data-id="{row["id"]}" title="Click to undo" onclick="toggleToday(this, {row["id"]})">&#10003; Completed</button>'
            else:
                btn_html = f'<button class="btn btn-mark btn-sm today-btn" data-id="{row["id"]}" title="Mark as done for today" onclick="toggleToday(this, {row["id"]})">Mark done</button>'

            if streak >= 7:
                streak_html = f'<span class="streak-pill" data-sid="{row["id"]}" title="{streak}-day streak">&#128293; {streak} days &middot; don\'t break it</span>'
            elif streak > 0:
                streak_html = f'<span class="streak-pill" data-sid="{row["id"]}" title="{streak}-day streak">&#128293; {streak} day{"s" if streak != 1 else ""}</span>'
            else:
                streak_html = f'<span class="streak-pill empty" data-sid="{row["id"]}">Start your streak today</span>'

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

      var pill = btn.parentElement.querySelector('.streak-pill[data-sid="' + systemId + '"]');
      if (pill) {{
        if (data.streak >= 7) {{
          pill.innerHTML = '&#128293; ' + data.streak + ' days &middot; don\\'t break it';
          pill.title     = data.streak + '-day streak';
          pill.className = 'streak-pill';
        }} else if (data.streak > 0) {{
          var days = data.streak === 1 ? 'day' : 'days';
          pill.innerHTML = '&#128293; ' + data.streak + ' ' + days;
          pill.title     = data.streak + '-day streak';
          pill.className = 'streak-pill';
        }} else {{
          pill.innerHTML = 'Start your streak today';
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
#  PROGRESS   /progress
# =======================================================
@app.route("/progress")
@login_required
def progress():
    user_id = session["user_id"]
    conn = get_db()
    rows = conn.execute(
        "SELECT id, goal, book FROM systems WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        body = """
<div class="page-header">
  <h1>Progress</h1>
  <p>Your weekly consistency, at a glance.</p>
</div>
<div class="empty-state">
  <div class="empty-icon">&#128202;</div>
  <h3>Nothing to track yet</h3>
  <p>Create your first system to start seeing your progress here.</p>
  <a href="/" class="btn btn-primary btn-lg" style="margin-top:14px;">Create a system &rarr;</a>
</div>
"""
        return page("Progress", body, active="progress")

    # Aggregate stats
    total_systems       = len(rows)
    total_completions   = get_total_completions(user_id)
    best_streak_overall = max((get_streak(user_id, r["id"]) for r in rows), default=0)
    today_str           = get_today()

    # Per-system weekly cards
    cards_html = ""
    week_total_done = 0
    week_total_max  = 0

    for row in rows:
        completed, days = get_week_stats(user_id, row["id"])
        streak = get_streak(user_id, row["id"])
        week_total_done += completed
        week_total_max  += 7

        goal_safe = (row["goal"] or "").replace("<","&lt;").replace(">","&gt;")
        book_safe = (row["book"] or "").replace("<","&lt;").replace(">","&gt;")
        pct       = int((completed / 7) * 100)

        dots_html = ""
        for d in days:
            cls = "week-dot"
            if d["done"]:
                cls += " done"
            if d["date"] == today_str:
                cls += " today"
            dots_html += f'<div class="{cls}" title="{d["date"]}">{d["label"]}</div>'

        if streak >= 7:
            streak_label = f'<span class="streak-pill">&#128293; {streak} days &middot; don\'t break it</span>'
        elif streak > 0:
            streak_label = f'<span class="streak-pill">&#128293; {streak} day{"s" if streak != 1 else ""}</span>'
        else:
            streak_label = '<span class="streak-pill empty">No streak</span>'

        cards_html += f"""
<div class="progress-system-card">
  <div class="progress-system-head">
    <div>
      <div class="progress-system-title">{goal_safe}</div>
      <div class="progress-system-sub">{book_safe}</div>
    </div>
    {streak_label}
  </div>

  <div class="week-strip">
    <div class="week-strip-info">
      <strong>{completed}/7 days</strong> this week
      <div style="margin-top:2px;">{"You're showing up." if completed >= 4 else "Show up tomorrow."}</div>
    </div>
    <div class="week-dots">{dots_html}</div>
  </div>

  <div class="progress-bar-track">
    <div class="progress-bar-fill" style="width:{pct}%;"></div>
  </div>
</div>
"""

    overall_pct = int((week_total_done / week_total_max) * 100) if week_total_max else 0

    body = f"""
<div class="page-header">
  <h1>Progress</h1>
  <p>Your weekly consistency, at a glance. Show up daily &mdash; the rest takes care of itself.</p>
</div>

<div class="stats-row">
  <div class="stat-card">
    <div class="stat-label">This Week</div>
    <div class="stat-value">{week_total_done}/{week_total_max}</div>
    <div class="stat-sub">{overall_pct}% completion rate</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Best Streak</div>
    <div class="stat-value">{best_streak_overall}</div>
    <div class="stat-sub">consecutive days</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Total Check-ins</div>
    <div class="stat-value">{total_completions}</div>
    <div class="stat-sub">across {total_systems} system{"s" if total_systems != 1 else ""}</div>
  </div>
</div>

<div class="card-header" style="border-bottom:none; padding-bottom:0; margin-bottom:8px;">
  <span class="card-title">By System</span>
</div>

{cards_html}
"""
    return page("Progress", body, active="progress")


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
        body += '<a href="/dashboard" class="btn btn-secondary">&larr; Dashboard</a>'
        return page("Not Found", body)

    cleaned   = clean_ai_output(row["output_text"] or "")
    escaped   = cleaned.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
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
        <span class="chip">{book_safe}</span>
        <span class="chip">{date_str}</span>
      </div>
    </div>
    <form method="POST" action="/pdf_by_id">
      <input type="hidden" name="system_id" value="{row['id']}">
      <button class="btn btn-secondary btn-sm">Download PDF</button>
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
    return page("System", body)


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
    """Build a clean, branded PDF from text content."""
    MARGIN = 18
    LINE_H = 6.5

    pdf_doc = FPDF()
    pdf_doc.set_margins(left=MARGIN, top=MARGIN, right=MARGIN)
    pdf_doc.set_auto_page_break(auto=True, margin=MARGIN)
    pdf_doc.add_page()

    usable_w = max(pdf_doc.w - 2 * MARGIN, 50)

    # Green header band
    pdf_doc.set_fill_color(22, 163, 74)
    pdf_doc.rect(0, 0, pdf_doc.w, 22, style="F")
    pdf_doc.set_xy(MARGIN, 7)
    pdf_doc.set_font("Helvetica", "B", 16)
    pdf_doc.set_text_color(255, 255, 255)
    pdf_doc.cell(0, 8, "CONSC  -  Behavior System", ln=1)
    pdf_doc.set_text_color(17, 24, 39)
    pdf_doc.ln(10)

    if title:
        pdf_doc.set_font("Helvetica", "B", 13)
        pdf_doc.set_x(MARGIN)
        pdf_doc.multi_cell(usable_w, 7, _sanitise_for_pdf(title))
        pdf_doc.ln(2)
        pdf_doc.set_draw_color(220, 252, 231)
        pdf_doc.set_line_width(0.6)
        pdf_doc.line(MARGIN, pdf_doc.get_y(), pdf_doc.w - MARGIN, pdf_doc.get_y())
        pdf_doc.ln(5)

    cleaned = clean_ai_output(content or "")

    for line in cleaned.split("\n"):
        clean = _sanitise_for_pdf(line)

        if re.match(r'^\d+\.\s+\S', clean):
            pdf_doc.ln(2)
            pdf_doc.set_font("Helvetica", "B", 12)
            pdf_doc.set_text_color(20, 83, 45)
            pdf_doc.set_x(MARGIN)
            pdf_doc.multi_cell(usable_w, LINE_H + 1, clean)
            pdf_doc.set_text_color(17, 24, 39)
            pdf_doc.ln(1)
            continue

        pdf_doc.set_font("Helvetica", "", 11)
        pdf_doc.set_x(MARGIN)
        if not clean.strip():
            pdf_doc.ln(LINE_H * 0.6)
        else:
            try:
                pdf_doc.multi_cell(usable_w, LINE_H, clean)
            except Exception:
                pdf_doc.ln(LINE_H)

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
    user_id = session["user_id"]
    today   = get_today()

    # Verify ownership
    conn = get_db()
    owns = conn.execute(
        "SELECT 1 FROM systems WHERE id = ? AND user_id = ?",
        (system_id, user_id)
    ).fetchone()
    if not owns:
        conn.close()
        return jsonify({"error": "not found"}), 404

    existing = conn.execute(
        """SELECT id, completed FROM daily_progress
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

    streak = get_streak(user_id, system_id)
    return jsonify({"completed": new_status, "system_id": system_id, "streak": streak})


# =======================================================
#  SETTINGS   /settings
# =======================================================
@app.route("/settings")
@login_required
def settings_page():
    conn = get_db()
    user = conn.execute(
        "SELECT username, email FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    conn.close()

    if not user:
        session.clear()
        return redirect(url_for("login"))

    body = f"""
<div class="page-header">
  <h1>Settings</h1>
  <p>Manage your account, preferences, and data.</p>
</div>

<div class="card">
  <div class="card-header"><span class="card-title">Account</span></div>
  <div class="form-grid">
    <div class="field">
      <label>Username</label>
      <input value="{user['username']}" disabled>
    </div>
    <div class="field">
      <label>Email</label>
      <input value="{user['email']}" disabled>
    </div>
  </div>
  <button class="btn btn-secondary" onclick="alert('Password change coming soon. Contact support if you need help.')">Change password</button>
</div>

<div class="card">
  <div class="card-header"><span class="card-title">Preferences</span></div>
  <div class="form-grid">
    <div class="field">
      <label>Daily reminder time</label>
      <input type="time" value="09:00">
    </div>
    <div class="field">
      <label>Default difficulty</label>
      <select>
        <option>Easy</option>
        <option selected>Medium</option>
        <option>Hard</option>
      </select>
    </div>
  </div>
  <div class="field">
    <label>Email notifications</label>
    <select>
      <option>Daily reminder</option>
      <option>Weekly summary only</option>
      <option>Off</option>
    </select>
  </div>
  <p class="field-hint">Preferences are saved locally for now &mdash; backend hookup coming soon.</p>
</div>

<div class="card">
  <div class="card-header"><span class="card-title">About Consc</span></div>
  <p style="font-size:14px; color:var(--text-muted); line-height:1.7;">
    Consc exists to close the gap between knowing and doing.
    We don&#39;t give advice &mdash; we build systems that force execution.
    Every system you generate is tied to a daily action and a streak,
    because behavior changes through repetition, not inspiration.
  </p>
</div>

<div class="card danger-card">
  <div class="card-header"><span class="card-title">Danger Zone</span></div>
  <p style="font-size:13px; color:var(--text-muted); margin-bottom:14px;">
    Deleting your account permanently removes all your systems, streaks, and history. This cannot be undone.
  </p>
  <form method="POST" action="/delete_account"
        onsubmit="return confirm('This will permanently delete your account and ALL data. Are you sure?');">
    <button class="btn btn-danger">Delete my account</button>
  </form>
</div>
"""
    return page("Settings", body, active="settings")


@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    user_id = session["user_id"]
    conn = get_db()
    conn.execute("DELETE FROM daily_progress WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM systems        WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users          WHERE id      = ?", (user_id,))
    conn.commit()
    conn.close()
    session.clear()
    return redirect(url_for("signup"))


# =======================================================
#  FEEDBACK   /feedback
# =======================================================
@app.route("/feedback")
@login_required
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
                f'<strong>Reply:</strong> {row["reply"]}'
                f'</div>'
            )
        msg = (row["message"] or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        name = (row["name"] or "Anonymous").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        items_html += f"""
<div class="feedback-card">
  <div class="feedback-author">
    <span class="feedback-author-dot"></span>{name}
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
      <textarea name="message" placeholder="What&#39;s on your mind?" required></textarea>
    </div>
    <button class="btn btn-primary">Send Feedback</button>
  </form>
</div>

<div class="card-label" style="margin-bottom:14px; color:var(--text-muted);">WHAT PEOPLE ARE SAYING</div>
{items_html}
"""
    return page("Feedback", body, active="feedback")


@app.route("/feedback_submit", methods=["POST"])
@login_required
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
    app.run(debug=debug_mode, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))