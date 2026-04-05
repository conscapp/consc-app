from flask import Flask, request, render_template_string, send_file
import io
from openai import OpenAI
from fpdf import FPDF

import os
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = Flask(__name__)

HTML = """
<!doctype html>
<html>
<head>
<meta charset="UTF-8">
<title>Consc.app — System Builder</title>
</head>

<body style="margin:0; font-family:'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif; background:#0f172a; color:white;">

<div style="max-width:900px; margin:auto; padding:40px;">

<div style="display:flex; justify-content:space-between;">
  <h2>⚡ consc.app</h2>
  <a href="/saved" style="color:#38bdf8; margin-right:15px;">Saved</a>
  <a href="/feedback" style="color:#38bdf8;">Feedback</a>
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

IMPORTANT:
Use emojis in EVERY section title.

Build a realistic system.

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


@app.route("/save", methods=["POST"])
def save():
    content = request.form.get("content")

    with open("systems.txt", "a") as f:
        f.write(content + "\n\n---\n\n")

    return "<h2>Saved ✅</h2><a href='/'>Back</a>"


@app.route("/saved")
def saved():
    try:
        with open("systems.txt", "r") as f:
            content = f.read()
    except:
        content = ""

    systems = content.split("\n\n---\n\n")

    html = "<h1>Saved Systems</h1><a href='/'>Back</a><br><br>"

    for i, s in enumerate(systems):
        if s.strip():
            html += f"""
            <div>
            <pre>{s}</pre>
            <form method="POST" action="/delete">
            <input type="hidden" name="index" value="{i}">
            <button>Delete</button>
            </form>
            </div><br>
            """

    return html


@app.route("/delete", methods=["POST"])
def delete():
    index = int(request.form.get("index"))

    with open("systems.txt", "r") as f:
        systems = f.read().split("\n\n---\n\n")

    if 0 <= index < len(systems):
        systems.pop(index)

    with open("systems.txt", "w") as f:
        f.write("\n\n---\n\n".join(systems))

    return "<h2>Deleted 🗑️</h2><a href='/saved'>Back</a>"


@app.route("/feedback", methods=["GET"])
def feedback_page():
    try:
        with open("feedback.txt", "r") as f:
            content = f.read()
    except:
        content = ""

    entries = content.split("\n\n---\n\n")

    html = """
    <h1>💬 User Feedback</h1>
    <a href="/">⬅ Back</a><br><br>
    """

    for i, entry in enumerate(entries):
        if entry.strip() == "":
            continue

        html += f"""
        <div style="border:1px solid #ccc; padding:15px; margin-bottom:20px;">
            <pre>{entry}</pre>

            <form method="POST" action="/reply">
                <input type="hidden" name="index" value="{i}">
                <input name="reply" placeholder="Write a reply..." style="width:70%;">
                <button type="submit">Reply</button>
            </form>
        </div>
        """

    return html

@app.route("/feedback_submit", methods=["POST"])
def feedback_submit():
    name = request.form.get("name")
    message = request.form.get("message")

    entry = f"👤 {name}\n💬 {message}"

    with open("feedback.txt", "a", encoding="utf-8") as f:
        f.write(entry + "\n\n---\n\n")

    return "<h2>Thanks for your feedback! 🙌</h2><a href='/'>Back</a>"


@app.route("/reply", methods=["POST"])
def reply():
    index = int(request.form.get("index"))
    reply_text = request.form.get("reply")

    with open("feedback.txt", "r", encoding="utf-8") as f:
        entries = f.read().split("\n\n---\n\n")

    if 0 <= index < len(entries):
        entries[index] += f"\n\n🧑‍💻 Reply: {reply_text}"

    with open("feedback.txt", "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(entries))

    return "<h2>Reply added ✅</h2><a href='/feedback'>Back</a>"
if __name__ == "__main__":
    app.run(debug=True)