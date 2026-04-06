from flask import Flask, request, render_template_string, send_file
import io
from openai import OpenAI
from fpdf import FPDF
import sqlite3
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = Flask(__name__)

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute('''
    CREATE TABLE IF NOT EXISTS systems (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT,
        rating INTEGER DEFAULT 0
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        message TEXT,
        reply TEXT
    )
    ''')

    conn.commit()
    conn.close()

init_db()

# ================= UI =================
HTML = """
<!doctype html>
<html>
<head>
<meta charset="UTF-8">
<title>consc.app — Build Systems, Not Goals</title>
</head>

<body style="margin:0; font-family:system-ui; background:#0f172a; color:white;">

<div style="max-width:1000px; margin:auto; padding:40px;">

<!-- NAV -->
<div style="display:flex; justify-content:space-between;">
  <h2>⚡ consc.app</h2>
  <div>
    <a href="/saved" style="color:#38bdf8; margin-right:15px;">Saved</a>
    <a href="/feedback" style="color:#38bdf8;">Feedback</a>
  </div>
</div>

<!-- HERO -->
<h1 style="font-size:40px;">Turn Knowledge into Action</h1>
<p style="color:#94a3b8;">AI-powered systems that actually fit your life.</p>

<!-- TRUST -->
<p style="color:#64748b; font-size:14px;">
Built to solve the biggest problem in self-help: knowing but not doing.
</p>

<br>

<!-- SAMPLE SYSTEMS -->
<h3>✨ Example Systems</h3>
<div style="display:grid; gap:10px;">
<div style="background:#1e293b; padding:15px; border-radius:10px;">
Wake up early system (adapted for night workers)
</div>
<div style="background:#1e293b; padding:15px; border-radius:10px;">
Start earning from zero using Rich Dad Poor Dad
</div>
</div>

<br>

<!-- FORM -->
<form method="post" style="background:#1e293b; padding:25px; border-radius:12px;">

<input name="goal" placeholder="Your Goal (e.g. wake up early)" required style="width:100%; padding:12px; margin-bottom:10px;">
<input name="book" placeholder="Book / Source (e.g. Atomic Habits)" required style="width:100%; padding:12px; margin-bottom:10px;">
<input name="why" placeholder="Why do you want this?" required style="width:100%; padding:12px; margin-bottom:10px;">

<select name="level" style="width:100%; padding:12px; margin-bottom:10px;">
<option>Beginner</option>
<option>Intermediate</option>
<option>Advanced</option>
</select>

<input name="struggle" placeholder="Biggest Struggle" required style="width:100%; padding:12px; margin-bottom:10px;">
<input name="custom" placeholder="Constraints (e.g. work till 11pm)" style="width:100%; padding:12px; margin-bottom:20px;">

<button style="width:100%; padding:14px; background:#38bdf8; border:none; border-radius:8px;">
Generate System 🚀
</button>

</form>

{% if result %}

<h2>Your System</h2>

<div style="background:#1e293b; padding:20px; border-radius:10px;">
{{ result.replace('\\n','<br>') | safe }}
</div>

<br>

<form method="POST" action="/save">
<textarea name="content" style="display:none;">{{ result }}</textarea>
<button style="background:#22c55e; padding:10px;">Save</button>
</form>

<br>

<form method="POST" action="/rate">
<input type="hidden" name="content" value="{{ result }}">
<select name="rating">
<option value="5">⭐️⭐️⭐️⭐️⭐️</option>
<option value="4">⭐️⭐️⭐️⭐️</option>
<option value="3">⭐️⭐️⭐️</option>
<option value="2">⭐️⭐️</option>
<option value="1">⭐️</option>
</select>
<button>Rate</button>
</form>

{% endif %}

</div>
</body>
</html>
"""

# ================= ROUTES =================

@app.route("/", methods=["GET", "POST"])
def index():
    result = None

    if request.method == "POST":
        goal = request.form.get("goal")
        book = request.form.get("book")
        why = request.form.get("why")
        level = request.form.get("level")
        struggle = request.form.get("struggle")
        custom = request.form.get("custom")

        prompt = f"""
You are a world-class habit coach.

User:
Goal: {goal}
Book: {book}
Level: {level}
Struggle: {struggle}
Why: {why}
Constraints: {custom}

Make system practical and realistic.

1. 🎯 Goal
2. 🧠 Identity
3. 🔥 Motivation
4. ⚡ Daily System
5. 📅 Weekly Plan
6. 🚧 Constraints
7. 📜 Rules
8. ❌ Mistakes
9. 🚀 Start Today
"""

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.choices[0].message.content

    return render_template_string(HTML, result=result)

# SAVE
@app.route("/save", methods=["POST"])
def save():
    content = request.form.get("content")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT INTO systems (content) VALUES (?)", (content,))
    conn.commit()
    conn.close()

    return "<h2>Saved ✅</h2><a href='/'>Back</a>"

# RATE
@app.route("/rate", methods=["POST"])
def rate():
    content = request.form.get("content")
    rating = request.form.get("rating")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT INTO systems (content, rating) VALUES (?, ?)", (content, rating))
    conn.commit()
    conn.close()

    return "<h2>Thanks for rating ⭐</h2><a href='/'>Back</a>"

# RUN
if __name__ == "__main__":
    app.run(debug=True)