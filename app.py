from flask import Flask, render_template, request
import os
import sqlite3
from utils.parser import extract_text
from utils.preprocess import preprocess_text
from utils.skill_extractor import load_skills, extract_skills
from utils.similarity import jaccard_similarity
from utils.ml_similarity import compute_similarity
from flask import send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from flask import redirect
from reportlab.platypus import Image
import matplotlib.pyplot as plt
import matplotlib
from flask import session
from openpyxl import Workbook
from flask import send_from_directory


import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders


matplotlib.use('Agg')   #  FIX (no GUI)

app = Flask(__name__)

app.secret_key = "supersecretkey"
# Send email
def send_email():
    sender = "ramalakshmi17293@gmail.com"
    password = "hjpq sxqs mwdb nbra"
    receiver = "immanuelhepsi@gmail.com"

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = "Resume Screening Report"

    attachment = open("report.pdf", "rb")

    part = MIMEBase("application", "octet-stream")
    part.set_payload(attachment.read())
    encoders.encode_base64(part)

    part.add_header("Content-Disposition", "attachment; filename=report.pdf")
    msg.attach(part)

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender, password)
    server.send_message(msg)
    server.quit()

#  GLOBAL VARIABLE
results_global = []
history = []

# LOAD SKILLS
skill_set = load_skills("data/skills.txt")

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

#  PLACE FUNCTION HERE (ABOVE ROUTES)
def get_label(score):
    if score >= 90:
        return "Excellent"
    elif score >= 40:
        return "Good"
    elif score >= 20:
        return "Average"
    else:
        return "Low"

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        score REAL,
        skills TEXT,
        label TEXT
    )
    """)

    conn.commit()
    conn.close()

@app.route("/")
def home():
    if "user" not in session:
        return redirect("/login")

    return render_template("index.html", role=session.get("role"))

@app.route("/admin")
def admin():
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        return "Access Denied"

    search = request.args.get("search", "")
    min_score = request.args.get("min_score", 0, type=float)
    page = request.args.get("page", 1, type=int)

    per_page = 5
    offset = (page - 1) * per_page

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    # Filter query
    query = """
        SELECT * FROM results
        WHERE name LIKE ? AND score >= ?
        ORDER BY score DESC
        LIMIT ? OFFSET ?
    """

    cursor.execute(query, ('%' + search + '%', min_score, per_page, offset))
    data = cursor.fetchall()

    # Count total rows (for pagination)
    cursor.execute(
        "SELECT COUNT(*) FROM results WHERE name LIKE ? AND score >= ?",
        ('%' + search + '%', min_score)
    )
    total = cursor.fetchone()[0]

    conn.close()

    total_pages = (total // per_page) + (1 if total % per_page else 0)

    return render_template(
        "admin.html",
        data=data,
        page=page,
        total_pages=total_pages,
        search=search,
        min_score=min_score
    )
@app.route("/analyze", methods=["POST"])
def analyze():
    if "user" not in session:
        return redirect("/login")

    job_text = request.form["job_description"]

    job_tokens = preprocess_text(job_text)
    job_skills = extract_skills(job_tokens, skill_set)

    results = []
    files = request.files.getlist("resumes")

    # Ensure upload folder exists
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    for file in files:
        if file.filename == "":
            continue

        filename = file.filename
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        # Save file ONCE ✅
        file.save(filepath)

        text = extract_text(filepath)
        if not text:
            continue

        tokens = preprocess_text(text)
        candidate_skills = extract_skills(tokens, skill_set)

        # AI scoring
        jaccard = jaccard_similarity(job_skills, candidate_skills)
        ml_score = compute_similarity(job_text, text)

        score = (0.6 * ml_score + 0.4 * jaccard) * 100
        label = get_label(score)

        results.append((filename, round(score, 2), list(candidate_skills), label))

    # Sort results
    results.sort(key=lambda x: x[1], reverse=True)

    # Save history
    history.append(results)

    global results_global
    results_global = results

    # Save to DB
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    for name, score, skills, label in results:
        cursor.execute(
            "INSERT INTO results (name, score, skills, label) VALUES (?, ?, ?, ?)",
            (name, score, ", ".join(skills), label)
        )

    conn.commit()
    conn.close()

    return render_template("result.html", results=results, job_skills=job_skills)

@app.route("/view_resume/<filename>")
def view_resume(filename):
    if "user" not in session:
        return redirect("/login")

    return send_from_directory("uploads", filename)

@app.route("/download")
def download():
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet

    file_path = "report.pdf"
    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()

    content = []

    # -------------------------
    # LOGO
    # -------------------------
    logo_path = os.path.join(os.getcwd(), "static", "logo.jpg")
    logo = Image(logo_path, width=120, height=60)
    content.append(logo)
    content.append(Spacer(1, 10))

    # -------------------------
    # TITLE
    # -------------------------
    content.append(Paragraph("<b>AI Resume Screening Report</b>", styles["Title"]))
    content.append(Spacer(1, 20))

    # -------------------------
    # CREATE CHART FIRST
    # -------------------------
    names = [r[0] for r in results_global]
    scores = [r[1] for r in results_global]

    plt.figure(figsize=(6, 3))
    plt.bar(names, scores)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    chart_path = os.path.join(os.getcwd(), "static", "chart.png")
    plt.savefig(chart_path)
    plt.close()

    # -------------------------
    # TABLE DATA
    # -------------------------
    table_data = [["Rank", "Candidate", "Score (%)", "Skills", "Performance"]]

    for i, (name, score, skills, label) in enumerate(results_global, start=1):
        skill_text = ", ".join(skills)

        table_data.append([
            i,
            Paragraph(name, styles["Normal"]),
            score,
            Paragraph(skill_text, styles["Normal"]),
            Paragraph(label, styles["Normal"])
        ])

    # -------------------------
    # TABLE DESIGN
    # -------------------------
    table = Table(table_data, colWidths=[40, 120, 60, 180, 80], repeatRows=1)

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),

        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),

        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),

        ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
    ]))

    # Highlight TOP candidate
    if len(table_data) > 1:
        table.setStyle([
            ("BACKGROUND", (0, 1), (-1, 1), colors.lightgreen),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ])

    # -------------------------
    # ADD TABLE
    # -------------------------
    content.append(table)

    content.append(Spacer(1, 20))

    # -------------------------
    # ADD CHART
    # -------------------------
    content.append(Paragraph("<b>Score Visualization</b>", styles["Heading2"]))
    content.append(Spacer(1, 10))

    chart = Image("static/chart.png", width=500, height=250)
    content.append(chart)

    # -------------------------
    # BUILD PDF
    # -------------------------
    doc.build(content)

    return send_file(file_path, as_attachment=True)

@app.route("/export_excel")
def export_excel():
    wb = Workbook()
    ws = wb.active

    ws.append(["Name", "Score", "Skills", "Performance"])

    for name, score, skills, label in results_global:
        ws.append([name, score, ", ".join(skills), label])

    file_path = "report.xlsx"
    wb.save(file_path)

    return send_file(file_path, as_attachment=True)

@app.route("/send_email")
def email_report():
    send_email()
    if "user" not in session:
        return redirect("/login")
    return "Email sent successfully!"

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pwd = request.form["password"]

        # 👇 Simple role-based login
        users = {
            "admin": {"password": "1234", "role": "admin"},
            "hr": {"password": "1234", "role": "hr"}
        }

        if user in users and pwd == users[user]["password"]:
            session["user"] = user
            session["role"] = users[user]["role"]

            return redirect("/")   #  GO TO INDEX PAGE
        else:
            return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)   #  REMOVE SESSION
    return redirect("/login")

if __name__ == "__main__":
    os.makedirs("uploads", exist_ok=True)
    init_db()
    app.run(debug=True)