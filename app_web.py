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
        content TEXT
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
<title>consc.app — System Builder</title>
</head>

<body style="margin:0; font-family:'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif; background:#0f172a; color:white;">

<div style="max-width:900px; margin:auto; padding:40px;">

<div style="display:flex; justify-content:space-between;">
  <h2>⚡ consc.app</h2>
  <div>
    <a href="/saved" style="color:#38bdf8; margin-right:15px;">Saved</a>
    <a href="/feedback" style="color:#38bdf8;">Feedback</a>
  </div>
</div>

<br>

<h1>Turn Knowledge into Action</h1>
<p style="color:#94a3b8;">Build systems that actually work.</p>

<br>

<form method="post" id="mainForm" style="background:#1e293b; padding:30px; border-radius:12px;">

<input name="goal" placeholder="Your Goal" required style="width:100%; padding:12px; margin-bottom:10px;">
<input name="book" placeholder="Book / Source" required style="width:100%; padding:12px; margin-bottom:10px;">
<input name="why" placeholder="Why do you want this?" required style="width:100%; padding:12px; margin-bottom:10px;">

<select name="level" style="width:100%; padding:12px; margin-bottom:10px;">
<option>Beginner</option>
<option>Intermediate</option>
<option>Advanced</option>
</select>

<input name="struggle" placeholder="Biggest Struggle" required style="width:100%; padding:12px; margin-bottom:10px;">
<input name="custom" placeholder="Constraints (e.g. work till 11pm)" style="width:100%; padding:12px; margin-bottom:20px;">

<button id="generateBtn" style="width:100%; padding:14px; background:#38bdf8; border:none; border-radius:8px; font-weight:bold;">
Generate System
</button>

</form>

{% if result %}

<br><br>

<h2>Your System</h2>

<form method="post">
<input type="hidden" name="goal" value="{{ request.form.get('goal') }}">
<input type="hidden" name="book" value="{{ request.form.get('book') }}">
<input type="hidden" name="why" value="{{ request.form.get('why') }}">
<input type="hidden" name="level" value="{{ request.form.get('level') }}">
<input type="hidden" name="struggle" value="{{ request.form.get('struggle') }}">
<input type="hidden" name="custom" value="{{ request.form.get('custom') }}">

<button style="background:#ef4444; padding:8px 14px; border:none; border-radius:6px; margin-bottom:15px;">
🔄 Regenerate
</button>
</form>

<div id="resultBox">
{% set parts = result.split('\\n\\n') %}
{% for part in parts %}
<div style="background:#1e293b; padding:15px; margin:10px 0; border-radius:8px;">
{{ part.replace('\\n','<br>') | safe }}
</div>
{% endfor %}
</div>

<br>

<button onclick="copyResult()" style="background:#f59e0b; padding:10px 15px; border:none; border-radius:6px; margin-right:10px;">
📋 Copy
</button>

<form method="POST" action="/save" style="display:inline;">
<textarea name="content" style="display:none;">{{ result }}</textarea>
<button style="background:#22c55e; padding:10px 15px; border:none; border-radius:6px;">
Save
</button>
</form>

<form method="POST" action="/download" style="display:inline;">
<textarea name="content" style="display:none;">{{ result }}</textarea>
<button style="background:#6366f1; padding:10px 15px; border:none; border-radius:6px;">
PDF
</button>
</form>

<br><br>

<h3>💬 Share Feedback</h3>

<form method="POST" action="/feedback_submit" style="background:#1e293b; padding:20px; border-radius:10px;">
<input name="name" placeholder="Your Name" required style="width:100%; padding:10px; margin-bottom:10px;">
<textarea name="message" placeholder="Your feedback..." required style="width:100%; padding:10px; margin-bottom:10px;"></textarea>
<button style="background:#22c55e; padding:10px; border:none; border-radius:6px;">
Submit Feedback
</button>
</form>

{% endif %}

</div>

<script>
document.getElementById("mainForm").addEventListener("submit", function() {
    const btn = document.getElementById("generateBtn");
    btn.innerText = "Generating...";
    btn.style.opacity = "0.7";
});

function copyResult() {
    const text = document.getElementById("resultBox").innerText;
    navigator.clipboard.writeText(text);
    alert("Copied!");
}
</script>

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

Use emojis in titles.

1. 🎯 Goal
2. 🧠 Identity
3. 🔥 Motivation
4. ⚡ Daily System
5. 📅 Weekly Plan
6. 🚧 Constraints Handling
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

# ================= SAVE SYSTEM =================

@app.route("/save", methods=["POST"])
def save():
    content = request.form.get("content")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT INTO systems (content) VALUES (?)", (content,))
    conn.commit()
    conn.close()

    return "<h2>Saved ✅</h2><a href='/'>Back</a>"

# ================= VIEW SYSTEMS =================

@app.route("/saved")
def saved():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT * FROM systems")
    systems = c.fetchall()
    conn.close()

    html = "<h1>Saved Systems</h1><a href='/'>Back</a><br><br>"

    for system in systems:
        html += f"""
        <div>
        <pre>{system[1]}</pre>
        <form method="POST" action="/delete">
        <input type="hidden" name="id" value="{system[0]}">
        <button>Delete</button>
        </form>
        </div><br>
        """

    return html

# ================= DELETE =================

@app.route("/delete", methods=["POST"])
def delete():
    system_id = request.form.get("id")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("DELETE FROM systems WHERE id=?", (system_id,))
    conn.commit()
    conn.close()

    return "<h2>Deleted 🗑️</h2><a href='/saved'>Back</a>"

# ================= FEEDBACK =================

@app.route("/feedback")
def feedback():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT * FROM feedback")
    entries = c.fetchall()
    conn.close()

    html = "<h1>💬 Feedback</h1><a href='/'>Back</a><br><br>"

    for entry in entries:
        html += f"""
        <div style="margin-bottom:20px;">
        <pre>👤 {entry[1]}\n💬 {entry[2]}</pre>
        <p><strong>Reply:</strong> {entry[3]}</p>

        <form method="POST" action="/reply">
        <input type="hidden" name="id" value="{entry[0]}">
        <input name="reply" placeholder="Write reply">
        <button>Reply</button>
        </form>
        </div>
        """

    return html

@app.route("/feedback_submit", methods=["POST"])
def feedback_submit():
    name = request.form.get("name")
    message = request.form.get("message")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT INTO feedback (name, message, reply) VALUES (?, ?, '')", (name, message))
    conn.commit()
    conn.close()

    return "<h2>Thanks 🙌</h2><a href='/'>Back</a>"

@app.route("/reply", methods=["POST"])
def reply():
    feedback_id = request.form.get("id")
    reply_text = request.form.get("reply")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE feedback SET reply=? WHERE id=?", (reply_text, feedback_id))
    conn.commit()
    conn.close()

    return "<h2>Reply Added ✅</h2><a href='/feedback'>Back</a>"

# ================= PDF =================

@app.route("/download", methods=["POST"])
def download():
    content = request.form.get("content")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, content.encode('latin-1', 'replace').decode('latin-1'))

    return send_file(
        io.BytesIO(pdf.output(dest='S').encode('latin-1')),
        as_attachment=True,
        download_name="consc_system.pdf",
        mimetype="application/pdf"
    )

# ================= RUN =================

if __name__ == "__main__":
    app.run(debug=True)