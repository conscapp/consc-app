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
        rating TEXT
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

<body style="margin:0; font-family:sans-serif; background:#0f172a; color:white;">

<div style="max-width:900px; margin:auto; padding:40px;">

<h2>⚡ consc.app</h2>

<h1>Turn Knowledge into Action</h1>
<p style="color:#94a3b8;">
AI-powered system builder that turns ideas into real execution plans.
</p>

<p style="font-size:14px; color:#64748b;">
Built to help you stop consuming and start doing.
</p>

<hr style="margin:30px 0;">

<h3>🧪 Try Sample Systems</h3>

<div style="background:#1e293b; padding:15px; margin-bottom:10px;">
<strong>Wake Up Early System</strong><br>
Simple nightly wind-down + gradual wake shift.
</div>

<div style="background:#1e293b; padding:15px; margin-bottom:10px;">
<strong>Make Money from Zero</strong><br>
Skill stacking + daily outreach system.
</div>

<hr style="margin:30px 0;">

<form method="post">

<input name="goal" placeholder="Your Goal (e.g. wake up early)" required style="width:100%; padding:12px; margin-bottom:10px;">
<input name="book" placeholder="Book / Source" required style="width:100%; padding:12px; margin-bottom:10px;">
<input name="why" placeholder="Why do you want this?" required style="width:100%; padding:12px; margin-bottom:10px;">

<select name="level" style="width:100%; padding:12px; margin-bottom:10px;">
<option>Beginner</option>
<option>Intermediate</option>
<option>Advanced</option>
</select>

<input name="struggle" placeholder="Biggest struggle" required style="width:100%; padding:12px; margin-bottom:10px;">
<input name="custom" placeholder="Constraints (optional)" style="width:100%; padding:12px; margin-bottom:20px;">

<button title="Generate your personalized system" style="width:100%; padding:14px; background:#38bdf8;">
Generate System
</button>

</form>

{% if result %}

<hr style="margin:30px 0;">

<h2>Your System</h2>

<div>
{{ result.replace('\\n','<br>') | safe }}
</div>

<br>

<button onclick="copyText()" title="Copy system">Copy</button>

<form method="POST" action="/save" style="display:inline;">
<textarea name="content" style="display:none;">{{ result }}</textarea>
<button title="Save this system">Save</button>
</form>

<form method="POST" action="/rate" style="display:inline;">
<input type="hidden" name="content" value="{{ result }}">
<button name="rating" value="good">👍</button>
<button name="rating" value="bad">👎</button>
</form>

{% endif %}

<hr style="margin:30px 0;">

<h3>💬 Feedback</h3>

<form method="POST" action="/feedback_submit">
<input name="name" placeholder="Your name" required>
<textarea name="message" placeholder="Your feedback..." required></textarea>
<button>Submit</button>
</form>

<hr style="margin:30px 0;">

<h4>About</h4>
<p style="color:#94a3b8;">
I built this tool to solve one problem: people read a lot but don’t execute.
This turns ideas into real systems you can follow daily.
</p>

</div>

<script>
function copyText() {
    const text = document.body.innerText;
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
You are a world-class system builder.

Goal: {goal}
Book: {book}
Why: {why}
Level: {level}
Struggle: {struggle}
Constraints: {custom}

Make it actionable.

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

# ================= SAVE =================

@app.route("/save", methods=["POST"])
def save():
    content = request.form.get("content")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT INTO systems (content, rating) VALUES (?, '')", (content,))
    conn.commit()
    conn.close()

    return "<h2>Saved ✅</h2><a href='/'>Back</a>"

# ================= RATE =================

@app.route("/rate", methods=["POST"])
def rate():
    content = request.form.get("content")
    rating = request.form.get("rating")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT INTO systems (content, rating) VALUES (?, ?)", (content, rating))
    conn.commit()
    conn.close()

    return "<h2>Thanks for feedback 🙌</h2><a href='/'>Back</a>"

# ================= FEEDBACK =================

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

if __name__ == "__main__":
    app.run(debug=True)