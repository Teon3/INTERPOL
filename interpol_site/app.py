import os
import secrets
import sqlite3
import uuid
from functools import wraps
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, abort
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
DB_PATH = DATA_DIR / "records.db"
UPLOAD_FOLDER = DATA_DIR / "uploads"

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
NOTICE_TYPES = [
    "Red Notice", "Yellow Notice", "Blue Notice",
    "Black Notice", "Green Notice", "Orange Notice", "Purple Notice",
]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("Задай FLASK_SECRET_KEY у файлі .env")

app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

csrf = CSRFProtect(app)

ADMIN_USERNAME = os.environ.get("INTERPOL_ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.environ.get("INTERPOL_ADMIN_PASSWORD", "")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                nationality TEXT DEFAULT '',
                notice_type TEXT NOT NULL DEFAULT 'Red Notice',
                warrant_number TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                photo TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(people)").fetchall()}
        
        # Автоматичне додавання нових колонок для розширеної анкети
        new_columns = {
            "date_of_birth": "TEXT DEFAULT ''",
            "place_of_birth": "TEXT DEFAULT ''",
            "languages": "TEXT DEFAULT ''",
            "charges": "TEXT DEFAULT ''",
            "height": "TEXT DEFAULT ''",
            "eye_color": "TEXT DEFAULT ''"
        }
        for col, col_type in new_columns.items():
            if col not in columns:
                conn.execute(f"ALTER TABLE people ADD COLUMN {col} {col_type}")
                
        if "updated_at" not in columns:
            conn.execute("ALTER TABLE people ADD COLUMN updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def save_photo(file):
    if not file or not file.filename: return ""
    if not allowed_file(file.filename): raise ValueError("Дозволені формати: JPG, JPEG, PNG, WEBP.")
    safe_name = secure_filename(file.filename)
    ext = safe_name.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    destination = UPLOAD_FOLDER / filename
    file.save(destination)
    return filename

def delete_photo_file(filename):
    if not filename: return
    if Path(filename).name != filename: return
    try: (UPLOAD_FOLDER / filename).unlink(missing_ok=True)
    except OSError: app.logger.exception("Не вдалося видалити фото")

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Увійдіть, щоб виконати цю дію.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

@app.context_processor
def inject_template_data():
    return {"notice_types": NOTICE_TYPES, "admin_logged_in": bool(session.get("admin_logged_in"))}

@app.route("/")
def index():
    q = request.args.get("q", "").strip()[:100]
    notice_type = request.args.get("type", "").strip()
    conditions, params = [], []
    if q:
        conditions.append("(full_name LIKE ? OR record_id LIKE ? OR nationality LIKE ?)")
        pattern = f"%{q}%"
        params.extend([pattern, pattern, pattern])
    if notice_type in NOTICE_TYPES:
        conditions.append("notice_type = ?")
        params.append(notice_type)
    else: notice_type = ""
    sql = "SELECT * FROM people"
    if conditions: sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at DESC, id DESC"
    with get_db() as conn:
        people = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    return render_template("index.html", people=people, q=q, selected_type=notice_type, total=total)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    if Path(filename).name != filename: abort(404)
    return __import__("flask").send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_logged_in"): return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not ADMIN_USERNAME or not ADMIN_PASSWORD:
            flash("Адміністратора не налаштовано. Перевірте змінні середовища.", "error")
        elif secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session["admin_logged_in"] = True
            session.permanent = True
            flash("Ви успішно увійшли.", "success")
            next_url = request.args.get("next", "")
            return redirect(next_url) if next_url.startswith("/") and not next_url.startswith("//") else redirect(url_for("index"))
        else: flash("Неправильний логін або пароль.", "error")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
@admin_required
def logout():
    session.clear()
    flash("Ви вийшли з облікового запису.", "success")
    return redirect(url_for("index"))

@app.route("/apply", methods=["GET", "POST"])
@admin_required
def apply():
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in [
            "record_id", "full_name", "nationality", "notice_type", "warrant_number",
            "date_of_birth", "place_of_birth", "languages", "charges", "height", "eye_color", "summary"
        ]}
        if not data["record_id"] or not data["full_name"]:
            flash("ID справи та повне ім'я обов'язкові.", "error")
            return render_template("apply.html", form_data=request.form)
        photo_name = ""
        try:
            photo_name = save_photo(request.files.get("photo"))
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO people
                    (record_id, full_name, nationality, notice_type, warrant_number, date_of_birth, place_of_birth, languages, charges, height, eye_color, summary, photo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, tuple(data.values()) + (photo_name,))
            flash("Досьє створено.", "success")
            return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            delete_photo_file(photo_name)
            flash("Такий ID справи вже існує.", "error")
        except Exception as e:
            delete_photo_file(photo_name)
            flash(str(e), "error")
        return render_template("apply.html", form_data=request.form)
    return render_template("apply.html", form_data={})

@app.route("/person/<int:pid>")
def person(pid):
    with get_db() as conn:
        p = conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
    if p is None: abort(404)
    return render_template("person.html", p=p)

@app.route("/edit/<int:pid>", methods=["GET", "POST"])
@admin_required
def edit(pid):
    with get_db() as conn:
        p = conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
    if p is None: abort(404)
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in [
            "record_id", "full_name", "nationality", "notice_type", "warrant_number",
            "date_of_birth", "place_of_birth", "languages", "charges", "height", "eye_color", "summary"
        ]}
        if not data["record_id"] or not data["full_name"]:
            flash("Помилка валідації.", "error")
            return render_template("edit.html", p=p, form_data=request.form)
        new_photo = ""
        try:
            uploaded = request.files.get("photo")
            if uploaded and uploaded.filename: new_photo = save_photo(uploaded)
            with get_db() as conn:
                query = f"""
                    UPDATE people SET record_id=?, full_name=?, nationality=?, notice_type=?, warrant_number=?,
                    date_of_birth=?, place_of_birth=?, languages=?, charges=?, height=?, eye_color=?, summary=?,
                    {'photo=?,' if new_photo else ''} updated_at=CURRENT_TIMESTAMP WHERE id=?
                """
                params = tuple(data.values()) + ((new_photo, pid) if new_photo else (pid,))
                conn.execute(query, params)
            if new_photo: delete_photo_file(p["photo"])
            flash("Досьє оновлено.", "success")
            return redirect(url_for("person", pid=pid))
        except Exception as e:
            if new_photo: delete_photo_file(new_photo)
            flash(str(e), "error")
        return render_template("edit.html", p=p, form_data=request.form)
    return render_template("edit.html", p=p, form_data={})

@app.route("/delete/<int:pid>", methods=["POST"])
@admin_required
def delete(pid):
    with get_db() as conn:
        p = conn.execute("SELECT photo FROM people WHERE id = ?", (pid,)).fetchone()
        if p is None: abort(404)
        conn.execute("DELETE FROM people WHERE id = ?", (pid,))
    delete_photo_file(p["photo"])
    flash("Досьє видалено.", "success")
    return redirect(url_for("index"))

init_db()

if __name__ == "__main__":
    app.run(debug=True)