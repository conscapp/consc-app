from flask import Flask, request, render_template_string, send_file, redirect, url_for, jsonify
import io
from openai import OpenAI
from fpdf import FPDF
import sqlite3
import os
from datetime import date, timedelta

# ─────────────────────────────────────────
#  Setup
# ─────────────────────────────────────────
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = Flask(__name__)

# ─────────────────────────────────────────
#  Database
# ─────────────────────────────────────────
def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row   # lets us access columns by name
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS systems (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT,
            rating  INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT,
            message TEXT,
            reply   TEXT DEFAULT ''
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_progress (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER,
            date      TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ─────────────────────────────────────────
#  Streak helper
# ─────────────────────────────────────────
def calculate_streak(conn, system_id):
    rows = conn.execute(
        "SELECT DISTINCT date FROM daily_progress WHERE system_id = ? ORDER BY date DESC",
        (system_id,)
    ).fetchall()
    dates = {row["date"] for row in rows}
    streak = 0
    current = date.today()
    while current.isoformat() in dates:
        streak += 1
        current -= timedelta(days=1)
    return streak


# ─────────────────────────────────────────
#  /complete_today/<system_id>
# ─────────────────────────────────────────
@app.route("/complete_today/<int:system_id>", methods=["POST"])
def complete_today(system_id):
    today = date.today().isoformat()
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM daily_progress WHERE system_id = ? AND date = ?",
        (system_id, today)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO daily_progress (system_id, date) VALUES (?, ?)",
            (system_id, today)
        )
        conn.commit()
    streak = calculate_streak(conn, system_id)
    conn.close()
    return jsonify({"completed": True, "streak": streak})


# ─────────────────────────────────────────
#  Shared CSS / design tokens
# ─────────────────────────────────────────
BASE_STYLE = """
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:       #080e1a;
  --surface:  #0f1c2e;
  --card:     #162032;
  --border:   #1e3a5f;
  --accent:   #38bdf8;
  --accent2:  #818cf8;
  --green:    #34d399;
  --red:      #f87171;
  --text:     #e2e8f0;
  --muted:    #64748b;
  --radius:   12px;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 16px;
  line-height: 1.6;
  min-height: 100vh;
}

/* Background mesh */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background:
    radial-gradient(ellipse 60% 40% at 20% 10%, #0c1f3d 0%, transparent 60%),
    radial-gradient(ellipse 50% 40% at 80% 90%, #0e1a35 0%, transparent 60%);
  pointer-events: none;
  z-index: 0;
}

.wrapper {
  position: relative;
  z-index: 1;
  max-width: 860px;
  margin: 0 auto;
  padding: 40px 24px 80px;
}

/* ── Nav ── */
nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 60px;
}
.logo {
  font-family: 'Syne', sans-serif;
  font-weight: 800;
  font-size: 22px;
  color: var(--accent);
  letter-spacing: -0.5px;
  text-decoration: none;
}
nav a {
  color: var(--muted);
  text-decoration: none;
  font-size: 14px;
  margin-left: 20px;
  transition: color .2s;
}
nav a:hover { color: var(--accent); }

/* ── Hero ── */
.hero h1 {
  font-family: 'Syne', sans-serif;
  font-weight: 800;
  font-size: clamp(32px, 5vw, 52px);
  line-height: 1.15;
  letter-spacing: -1px;
  margin-bottom: 14px;
}
.hero h1 span { color: var(--accent); }
.hero p {
  color: var(--muted);
  font-size: 17px;
  max-width: 520px;
  margin-bottom: 6px;
}
.trust {
  display: inline-block;
  margin-top: 12px;
  font-size: 13px;
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 100px;
  padding: 4px 14px;
}

/* ── Card ── */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  margin-bottom: 20px;
}
.card-title {
  font-family: 'Syne', sans-serif;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 16px;
}

/* ── Form elements ── */
input, select, textarea {
  width: 100%;
  padding: 12px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 15px;
  margin-bottom: 12px;
  transition: border-color .2s, box-shadow .2s;
  outline: none;
}
input::placeholder, textarea::placeholder { color: var(--muted); }
input:focus, select:focus, textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(56,189,248,.12);
}
select option { background: var(--surface); }
textarea { resize: vertical; min-height: 90px; }

/* ── Buttons ── */
.btn {
  display: inline-block;
  padding: 13px 28px;
  border-radius: 8px;
  border: none;
  font-family: 'Syne', sans-serif;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity .2s, transform .15s;
  text-decoration: none;
}
.btn:hover  { opacity: .88; transform: translateY(-1px); }
.btn:active { transform: translateY(0); }
.btn-primary { background: var(--accent);  color: #060e1b; width: 100%; text-align: center; }
.btn-green   { background: var(--green);   color: #060e1b; }
.btn-outline {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
}
.btn-outline:hover { border-color: var(--accent); color: var(--accent); }

/* ── Sample chips ── */
.samples { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 32px; }
.sample-chip {
  padding: 8px 16px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 100px;
  font-size: 13px;
  color: var(--muted);
}
.sample-chip strong { color: var(--text); }

/* ── Result block ── */
.result-body {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 24px;
  line-height: 1.8;
  font-size: 15px;
  white-space: pre-wrap;
}

/* ── Saved list ── */
.system-item {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  margin-bottom: 16px;
}
.system-meta {
  font-size: 13px;
  color: var(--muted);
  margin-top: 10px;
}

/* ── Feedback list ── */
.feedback-item {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  margin-bottom: 14px;
}
.feedback-item .author {
  font-family: 'Syne', sans-serif;
  font-weight: 700;
  font-size: 14px;
  color: var(--accent);
  margin-bottom: 6px;
}
.feedback-reply {
  margin-top: 12px;
  padding: 10px 14px;
  background: var(--surface);
  border-left: 3px solid var(--accent2);
  border-radius: 6px;
  font-size: 14px;
  color: var(--muted);
}

/* ── Rating stars ── */
.stars { color: #fbbf24; }

/* ── Section heading ── */
h2 {
  font-family: 'Syne', sans-serif;
  font-size: 26px;
  font-weight: 800;
  margin-bottom: 20px;
  letter-spacing: -0.5px;
}
h3 {
  font-family: 'Syne', sans-serif;
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 14px;
}

/* ── Alert / flash ── */
.alert {
  padding: 14px 18px;
  border-radius: 8px;
  margin-bottom: 24px;
  font-size: 14px;
}
.alert-success { background: rgba(52,211,153,.1); border: 1px solid var(--green); color: var(--green); }
.alert-info    { background: rgba(56,189,248,.08); border: 1px solid var(--accent); color: var(--accent); }

/* ── Row utils ── */
.row { display: flex; gap: 12px; }
.row > * { flex: 1; }
@media (max-width: 540px) { .row { flex-direction: column; } }

/* ── Streak UI ── */
.streak-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.btn-complete {
  padding: 8px 18px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  font-family: 'Syne', sans-serif;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: border-color .2s, color .2s, background .2s;
}
.btn-complete:hover:not(:disabled) {
  border-color: var(--green);
  color: var(--green);
}
.btn-complete.done {
  background: rgba(52,211,153,.1);
  border-color: var(--green);
  color: var(--green);
  cursor: default;
}
.streak-badge {
  font-size: 13px;
  color: var(--muted);
  padding: 4px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 100px;
  white-space: nowrap;
}
.streak-badge.active {
  color: #fbbf24;
  border-color: rgba(251,191,36,.5);
  background: rgba(251,191,36,.07);
}
"""

# ─────────────────────────────────────────
#  Helper: base page wrapper
# ─────────────────────────────────────────
def page(title, body, active="home"):
    nav_links = {
        "home":     ("/",         "Generator"),
        "saved":    ("/saved",    "Saved"),
        "feedback": ("/feedback", "Feedback"),
    }
    links_html = "".join(
        f'<a href="{href}" style="color:{"var(--accent)" if k == active else "var(--muted)"}">{label}</a>'
        for k, (href, label) in nav_links.items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — consc.app</title>
  <style>{BASE_STYLE}</style>
</head>
<body>
<div class="wrapper">
  <nav>
    <a href="/" class="logo">⚡ consc.app</a>
    <div>{links_html}</div>
  </nav>
  {body}
</div>
</body>
</html>"""

# ─────────────────────────────────────────
#  / — Generator
# ─────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error  = None

    if request.method == "POST":
        goal     = request.form.get("goal", "").strip()
        book     = request.form.get("book", "").strip()
        why      = request.form.get("why", "").strip()
        level    = request.form.get("level", "Beginner")
        struggle = request.form.get("struggle", "").strip()
        custom   = request.form.get("custom", "").strip()

        prompt = f"""You are a world-class habit coach. Build a practical, personalised action system.

User profile:
- Goal: {goal}
- Source book/method: {book}
- Experience level: {level}
- Why they want this: {why}
- Biggest struggle: {struggle}
- Constraints: {custom if custom else 'None'}

Respond with exactly these 9 sections. Keep language clear and direct:

1. 🎯 Goal — one crisp sentence
2. 🧠 Identity — the identity shift needed
3. 🔥 Motivation — connect to their "why"
4. ⚡ Daily System — 3-5 specific daily actions
5. 📅 Weekly Plan — Mon–Sun brief schedule
6. 🚧 Constraints — how to work around their limits
7. 📜 Rules — 3 non-negotiable rules
8. ❌ Mistakes to Avoid — top 3 pitfalls
9. 🚀 Start Today — the single first action to take right now
"""

        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1200,
            )
            result = response.choices[0].message.content
        except Exception as e:
            error = f"AI error: {e}"

    # Build result section
    result_html = ""
    if error:
        result_html = f'<div class="alert alert-info">{error}</div>'
    elif result:
        escaped = result.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        result_html = f"""
<div class="card" style="margin-top:40px;">
  <div class="card-title">Your Generated System</div>
  <div class="result-body">{escaped}</div>
</div>

<div class="row" style="margin-top:16px; flex-wrap:wrap; gap:12px;">

  <!-- Save -->
  <form method="POST" action="/save" style="flex:1; min-width:140px;">
    <input type="hidden" name="content" value="{result.replace('"', '&quot;')}">
    <button class="btn btn-green" style="width:100%;" title="Save this system to your list">
      💾 Save System
    </button>
  </form>

  <!-- Rate -->
  <form method="POST" action="/rate" style="display:flex; gap:8px; flex:1; min-width:220px;">
    <input type="hidden" name="content" value="{result.replace('"', '&quot;')}">
    <select name="rating" style="flex:1; margin:0;">
      <option value="5">⭐⭐⭐⭐⭐ Excellent</option>
      <option value="4">⭐⭐⭐⭐ Good</option>
      <option value="3">⭐⭐⭐ Okay</option>
      <option value="2">⭐⭐ Poor</option>
      <option value="1">⭐ Bad</option>
    </select>
    <button class="btn btn-outline" title="Submit your rating">Rate</button>
  </form>

  <!-- PDF -->
  <form method="POST" action="/pdf" style="flex:0;">
    <input type="hidden" name="content" value="{result.replace('"', '&quot;')}">
    <button class="btn btn-outline" title="Download as PDF">📄 PDF</button>
  </form>

</div>
"""

    body = f"""
<!-- Hero -->
<div class="hero" style="margin-bottom:40px;">
  <h1>Turn <span>Knowledge</span><br>into Action</h1>
  <p>Enter a goal and a book — we'll build a daily system personalised to your life.</p>
  <span class="trust">Built to close the gap between knowing and doing</span>
</div>

<!-- Sample systems -->
<div class="card-title" style="margin-bottom:10px;">✨ Example prompts to try</div>
<div class="samples">
  <span class="sample-chip"><strong>Goal:</strong> Wake up at 6am &nbsp;·&nbsp; <strong>Book:</strong> Atomic Habits</span>
  <span class="sample-chip"><strong>Goal:</strong> Build a side income &nbsp;·&nbsp; <strong>Book:</strong> Rich Dad Poor Dad</span>
  <span class="sample-chip"><strong>Goal:</strong> Read 20 books/year &nbsp;·&nbsp; <strong>Book:</strong> Deep Work</span>
</div>

<!-- Form -->
<div class="card">
  <div class="card-title">Build your system</div>
  <p style="color:var(--muted); font-size:14px; margin-bottom:20px;">
    Start by entering your goal — the more honest you are, the better the system.
  </p>
  <form method="POST">
    <div class="row">
      <input name="goal"     placeholder="Your goal  (e.g. wake up at 6am)"  required title="What do you want to achieve?">
      <input name="book"     placeholder="Book or method  (e.g. Atomic Habits)" required title="What book or framework should we use?">
    </div>
    <input name="why"      placeholder="Why do you want this?  (Be honest — it helps)"  required title="Your personal motivation">
    <div class="row">
      <select name="level" title="Your current experience with this goal">
        <option>Beginner</option>
        <option>Intermediate</option>
        <option>Advanced</option>
      </select>
      <input name="struggle" placeholder="Biggest struggle so far" required title="What always trips you up?">
    </div>
    <input name="custom" placeholder="Constraints  (e.g. work until 11pm, no gym access)"
           title="Life constraints we should design around">
    <button class="btn btn-primary" title="Generate your personalised action system">
      Generate My System 🚀
    </button>
  </form>
</div>

{result_html}
"""
    return page("Generator", body, active="home")


# ─────────────────────────────────────────
#  /save
# ─────────────────────────────────────────
@app.route("/save", methods=["POST"])
def save():
    content = request.form.get("content", "").strip()
    if content:
        conn = get_db()
        conn.execute("INSERT INTO systems (content) VALUES (?)", (content,))
        conn.commit()
        conn.close()
    body = """
<div class="alert alert-success">✅ System saved! You can find it in your Saved list.</div>
<a href="/" class="btn btn-outline">← Back to Generator</a>
&nbsp;
<a href="/saved" class="btn btn-outline">View Saved →</a>
"""
    return page("Saved", body)


# ─────────────────────────────────────────
#  /rate
# ─────────────────────────────────────────
@app.route("/rate", methods=["POST"])
def rate():
    content = request.form.get("content", "").strip()
    rating  = request.form.get("rating",  "5")
    if content:
        conn = get_db()
        conn.execute("INSERT INTO systems (content, rating) VALUES (?, ?)", (content, int(rating)))
        conn.commit()
        conn.close()
    body = f"""
<div class="alert alert-success">⭐ Thanks for rating — you gave it {rating} star(s)!</div>
<a href="/" class="btn btn-outline">← Back to Generator</a>
"""
    return page("Rating", body)


# ─────────────────────────────────────────
#  /saved
# ─────────────────────────────────────────
@app.route("/saved")
def saved():
    today = date.today().isoformat()
    conn  = get_db()
    rows  = conn.execute("SELECT id, content, rating FROM systems ORDER BY id DESC").fetchall()

    if not rows:
        conn.close()
        items_html = '<p style="color:var(--muted);">No saved systems yet. Generate one on the homepage!</p>'
    else:
        items_html = ""
        for row in rows:
            sid = row["id"]
            done_today = conn.execute(
                "SELECT 1 FROM daily_progress WHERE system_id = ? AND date = ?",
                (sid, today)
            ).fetchone() is not None
            streak = calculate_streak(conn, sid)

            stars = "⭐" * (row["rating"] or 0)
            preview = row["content"][:300].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            btn_class = "btn-complete done" if done_today else "btn-complete"
            btn_label = "Completed Today ✅" if done_today else "Not Done ❌"
            btn_disabled = "disabled" if done_today else ""
            badge_class = "streak-badge active" if streak > 0 else "streak-badge"
            streak_label = f"🔥 {streak} day streak" if streak > 0 else "0 day streak"

            items_html += f"""
<div class="system-item">
  <div style="white-space:pre-wrap; font-size:14px; line-height:1.7;">{preview}{'…' if len(row['content']) > 300 else ''}</div>
  <div class="system-meta">
    {'<span class="stars">' + stars + '</span>' if stars else 'No rating yet'}
    &nbsp;·&nbsp; ID #{sid}
  </div>
  <div class="streak-row">
    <button id="btn-{sid}" class="{btn_class}" {btn_disabled}
            onclick="completeToday({sid})">{btn_label}</button>
    <span id="streak-{sid}" class="{badge_class}">{streak_label}</span>
  </div>
</div>"""

        conn.close()

    body = f"""
<h2>Saved Systems</h2>
{items_html}
<br>
<a href="/" class="btn btn-outline">← Back to Generator</a>

<script>
function completeToday(systemId) {{
  var btn = document.getElementById('btn-' + systemId);
  btn.disabled = true;
  btn.textContent = 'Saving…';
  fetch('/complete_today/' + systemId, {{method: 'POST'}})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      btn.textContent = 'Completed Today ✅';
      btn.classList.add('done');
      var badge = document.getElementById('streak-' + systemId);
      badge.textContent = '🔥 ' + data.streak + ' day streak';
      badge.classList.add('active');
    }})
    .catch(function() {{
      btn.disabled = false;
      btn.textContent = 'Not Done ❌';
    }});
}}
</script>
"""
    return page("Saved Systems", body, active="saved")


# ─────────────────────────────────────────
#  /pdf
# ─────────────────────────────────────────
@app.route("/pdf", methods=["POST"])
def pdf():
    content = request.form.get("content", "").strip()
    if not content:
        return redirect(url_for("index"))

    pdf_doc = FPDF()
    pdf_doc.add_page()
    pdf_doc.set_font("Helvetica", "B", 16)
    pdf_doc.cell(0, 10, "consc.app — Your Action System", ln=True)
    pdf_doc.ln(4)
    pdf_doc.set_font("Helvetica", size=11)

    for line in content.split("\n"):
        safe_line = line.encode("latin-1", errors="replace").decode("latin-1")
        pdf_doc.multi_cell(0, 7, safe_line)

    buffer = io.BytesIO(pdf_doc.output())
    return send_file(buffer, as_attachment=True, download_name="consc_system.pdf", mimetype="application/pdf")


# ─────────────────────────────────────────
#  /feedback  (view + submit form)
# ─────────────────────────────────────────
@app.route("/feedback")
def feedback():
    conn  = get_db()
    rows  = conn.execute("SELECT name, message, reply FROM feedback ORDER BY id DESC").fetchall()
    conn.close()

    items_html = ""
    for row in rows:
        reply_html = ""
        if row["reply"]:
            reply_html = f'<div class="feedback-reply">💬 <strong>Reply:</strong> {row["reply"]}</div>'
        msg = row["message"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        items_html += f"""
<div class="feedback-item">
  <div class="author">{row['name']}</div>
  <div style="font-size:15px;">{msg}</div>
  {reply_html}
</div>"""

    if not items_html:
        items_html = '<p style="color:var(--muted);">No feedback yet — be the first!</p>'

    body = f"""
<h2>Feedback Wall</h2>

<!-- Submit form -->
<div class="card" style="margin-bottom:36px;">
  <div class="card-title">Share your thoughts</div>
  <p style="color:var(--muted); font-size:14px; margin-bottom:18px;">
    Your feedback helps us make consc.app better for everyone.
  </p>
  <form method="POST" action="/feedback_submit">
    <input name="name"    placeholder="Your name"         required title="How should we credit you?">
    <textarea name="message" placeholder="What's on your mind? Feature request, bug, praise — all welcome."
              required title="Your feedback message"></textarea>
    <button class="btn btn-primary" title="Submit your feedback">Send Feedback 🙌</button>
  </form>
</div>

<!-- Existing feedback -->
<h3 style="margin-bottom:16px;">What people are saying</h3>
{items_html}

<br>
<a href="/" class="btn btn-outline">← Back to Generator</a>
"""
    return page("Feedback", body, active="feedback")


# ─────────────────────────────────────────
#  /feedback_submit
# ─────────────────────────────────────────
@app.route("/feedback_submit", methods=["POST"])
def feedback_submit():
    name    = request.form.get("name",    "").strip()
    message = request.form.get("message", "").strip()

    if name and message:
        conn = get_db()
        conn.execute("INSERT INTO feedback (name, message, reply) VALUES (?, ?, '')", (name, message))
        conn.commit()
        conn.close()

    body = """
<div class="alert alert-success">🙌 Thanks for your feedback! We read every message.</div>
<a href="/feedback" class="btn btn-outline">← Back to Feedback</a>
&nbsp;
<a href="/" class="btn btn-outline">Go to Generator →</a>
"""
    return page("Feedback Received", body)


# ─────────────────────────────────────────
#  Run
# ─────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)