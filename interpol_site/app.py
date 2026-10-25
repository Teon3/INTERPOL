import os
import secrets
import sqlite3
import uuid
from functools import wraps
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, abort
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
# On Render set DATA_DIR=/var/data and attach a persistent disk there.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
DB_PATH = DATA_DIR / "records.db"
UPLOAD_FOLDER = DATA_DIR / "uploads"

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
NOTICE_TYPES = [
    "Red Notice",
    "Yellow Notice",
    "Blue Notice",
    "Black Notice",
    "Green Notice",
    "Orange Notice",
    "Purple Notice",
]

app = Flask(__name__)

# Обов'язково задай секрет через змінну середовища.
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError(
        "Задай FLASK_SECRET_KEY у змінних середовища перед запуском."
    )

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

        # Перевіряємо, чи існує поле в старій базі даних
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(people)"
            ).fetchall()
        }

        # Якщо поля немає — додаємо його
        if "updated_at" not in columns:
            conn.execute("""
                ALTER TABLE people
                ADD COLUMN updated_at TEXT
                NOT NULL DEFAULT CURRENT_TIMESTAMP
            """)



def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def save_photo(file):
    """Зберігає дозволене зображення під випадковим ім'ям."""
    if not file or not file.filename:
        return ""

    if not allowed_file(file.filename):
        raise ValueError("Дозволені формати: JPG, JPEG, PNG, WEBP.")

    # secure_filename нормалізує ім'я; користувацьке ім'я не
    # використовується як шлях збереження.
    safe_name = secure_filename(file.filename)
    ext = safe_name.rsplit(".", 1)[1].lower()

    filename = f"{uuid.uuid4().hex}.{ext}"
    destination = UPLOAD_FOLDER / filename
    file.save(destination)

    return filename


def delete_photo_file(filename):
    if not filename:
        return

    # Видаляємо лише файл з очікуваним випадковим ім'ям.
    if Path(filename).name != filename:
        return

    path = UPLOAD_FOLDER / filename
    try:
        path.unlink(missing_ok=True)
    except OSError:
        app.logger.exception("Не вдалося видалити фото")


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
    return {
        "notice_types": NOTICE_TYPES,
        "admin_logged_in": bool(session.get("admin_logged_in")),
    }


@app.route("/")
def index():
    q = request.args.get("q", "").strip()[:100]
    notice_type = request.args.get("type", "").strip()

    conditions = []
    params = []

    if q:
        conditions.append(
            "(full_name LIKE ? OR record_id LIKE ? OR nationality LIKE ?)"
        )
        pattern = f"%{q}%"
        params.extend([pattern, pattern, pattern])

    if notice_type in NOTICE_TYPES:
        conditions.append("notice_type = ?")
        params.append(notice_type)
    else:
        notice_type = ""

    sql = "SELECT * FROM people"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at DESC, id DESC"

    with get_db() as conn:
        people = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]

    return render_template(
        "index.html",
        people=people,
        q=q,
        selected_type=notice_type,
        total=total,
    )


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Only serve files stored directly in the upload directory.
    if Path(filename).name != filename:
        abort(404)
    return __import__("flask").send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_logged_in"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        # Якщо облікові дані не налаштовано, вхід заборонено.
        if not ADMIN_USERNAME or not ADMIN_PASSWORD:
            flash(
                "Адміністратора не налаштовано. Перевірте змінні середовища.",
                "error",
            )
        elif (
            secrets.compare_digest(username, ADMIN_USERNAME)
            and secrets.compare_digest(password, ADMIN_PASSWORD)
        ):
            session.clear()
            session["admin_logged_in"] = True
            session.permanent = True
            flash("Ви успішно увійшли.", "success")

            next_url = request.args.get("next", "")
            # Не дозволяємо перенаправлення на сторонній сайт.
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("index"))
        else:
            flash("Неправильний логін або пароль.", "error")

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
        record_id = request.form.get("record_id", "").strip()
        full_name = request.form.get("full_name", "").strip()
        nationality = request.form.get("nationality", "").strip()
        notice_type = request.form.get("notice_type", "Red Notice")
        warrant_number = request.form.get("warrant_number", "").strip()
        summary = request.form.get("summary", "").strip()

        if not record_id or not full_name:
            flash("ID справи та повне ім'я обов'язкові.", "error")
            return render_template("apply.html", form_data=request.form)

        if len(record_id) > 50 or len(full_name) > 150:
            flash("ID або ім'я задовге.", "error")
            return render_template("apply.html", form_data=request.form)

        if notice_type not in NOTICE_TYPES:
            flash("Невідомий тип повідомлення.", "error")
            return render_template("apply.html", form_data=request.form)

        photo_name = ""
        try:
            photo_name = save_photo(request.files.get("photo"))

            with get_db() as conn:
                conn.execute("""
                    INSERT INTO people
                    (record_id, full_name, nationality, notice_type,
                     warrant_number, summary, photo)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    record_id, full_name, nationality, notice_type,
                    warrant_number, summary, photo_name
                ))

            flash("Демонстраційну анкету створено.", "success")
            return redirect(url_for("index"))

        except sqlite3.IntegrityError:
            delete_photo_file(photo_name)
            flash("Такий ID справи вже існує.", "error")
        except ValueError as exc:
            flash(str(exc), "error")
        except OSError:
            delete_photo_file(photo_name)
            app.logger.exception("Помилка завантаження фото")
            flash("Не вдалося зберегти фотографію.", "error")
        except sqlite3.Error:
            delete_photo_file(photo_name)
            app.logger.exception("Помилка бази даних")
            flash("Не вдалося зберегти анкету.", "error")

        return render_template("apply.html", form_data=request.form)

    return render_template("apply.html", form_data={})


@app.route("/person/<int:pid>")
def person(pid):
    with get_db() as conn:
        p = conn.execute(
            "SELECT * FROM people WHERE id = ?", (pid,)
        ).fetchone()

    if p is None:
        abort(404)

    return render_template("person.html", p=p)


@app.route("/edit/<int:pid>", methods=["GET", "POST"])
@admin_required
def edit(pid):
    with get_db() as conn:
        p = conn.execute(
            "SELECT * FROM people WHERE id = ?", (pid,)
        ).fetchone()

    if p is None:
        abort(404)

    if request.method == "POST":
        record_id = request.form.get("record_id", "").strip()
        full_name = request.form.get("full_name", "").strip()
        nationality = request.form.get("nationality", "").strip()
        notice_type = request.form.get("notice_type", "")
        warrant_number = request.form.get("warrant_number", "").strip()
        summary = request.form.get("summary", "").strip()

        if (
            not record_id
            or not full_name
            or len(record_id) > 50
            or len(full_name) > 150
            or notice_type not in NOTICE_TYPES
        ):
            flash("Перевірте обов'язкові поля та тип повідомлення.", "error")
            return render_template("edit.html", p=p, form_data=request.form)

        new_photo = ""
        try:
            uploaded = request.files.get("photo")
            if uploaded and uploaded.filename:
                new_photo = save_photo(uploaded)

            with get_db() as conn:
                if new_photo:
                    conn.execute("""
                        UPDATE people
                        SET record_id=?, full_name=?, nationality=?,
                            notice_type=?, warrant_number=?, summary=?,
                            photo=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                    """, (
                        record_id, full_name, nationality, notice_type,
                        warrant_number, summary, new_photo, pid
                    ))
                else:
                    conn.execute("""
                        UPDATE people
                        SET record_id=?, full_name=?, nationality=?,
                            notice_type=?, warrant_number=?, summary=?,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                    """, (
                        record_id, full_name, nationality, notice_type,
                        warrant_number, summary, pid
                    ))

            if new_photo:
                delete_photo_file(p["photo"])

            flash("Анкету оновлено.", "success")
            return redirect(url_for("person", pid=pid))

        except sqlite3.IntegrityError:
            delete_photo_file(new_photo)
            flash("Такий ID справи вже використовується.", "error")
        except ValueError as exc:
            flash(str(exc), "error")
        except OSError:
            delete_photo_file(new_photo)
            app.logger.exception("Помилка збереження фото")
            flash("Не вдалося зберегти фотографію.", "error")
        except sqlite3.Error:
            delete_photo_file(new_photo)
            app.logger.exception("Помилка оновлення бази")
            flash("Не вдалося оновити анкету.", "error")

        return render_template("edit.html", p=p, form_data=request.form)

    return render_template("edit.html", p=p, form_data={})


@app.route("/delete/<int:pid>", methods=["POST"])
@admin_required
def delete(pid):
    with get_db() as conn:
        p = conn.execute(
            "SELECT photo FROM people WHERE id = ?", (pid,)
        ).fetchone()

        if p is None:
            abort(404)

        conn.execute("DELETE FROM people WHERE id = ?", (pid,))

    delete_photo_file(p["photo"])
    flash("Анкету видалено.", "success")
    return redirect(url_for("index"))


@app.errorhandler(413)
def too_large(_error):
    flash("Файл завеликий. Максимальний розмір — 8 МБ.", "error")
    return redirect(request.referrer or url_for("index"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


init_db()

if __name__ == "__main__":
    app.run(debug=True)
