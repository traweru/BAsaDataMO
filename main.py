from fastapi import FastAPI, Request, Form, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3
from datetime import datetime

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB_NAME = "reviews.db"


def get_db():
    conn = sqlite3.connect(DB_NAME)
    return conn, conn.cursor()


def init_db():
    conn, cur = get_db()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        );

        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (service_id) REFERENCES services(id)
        );
    """)
    if not cur.execute("SELECT * FROM services").fetchone():
        cur.executemany("INSERT INTO services (name) VALUES (?)", [("Химчистка",), ("Ремонт техники",), ("Доставка еды",)])
    if not cur.execute("SELECT * FROM users WHERE role = 'admin'").fetchone():
        cur.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ("admin", "admin123", "admin"))
    conn.commit()
    conn.close()


init_db()


def get_current_user(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    conn, cur = get_db()
    cur.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, q: str = "", service_filter: str = ""):
    user = get_current_user(request)
    conn, cur = get_db()

    query_sql = """
        SELECT reviews.id, users.username, services.name, reviews.rating, reviews.comment, reviews.timestamp, reviews.user_id
        FROM reviews
        JOIN users ON reviews.user_id = users.id
        JOIN services ON reviews.service_id = services.id
        WHERE 1=1
    """
    params = []

    if q:
        query_sql += " AND reviews.comment LIKE ?"
        params.append(f"%{q}%")

    if service_filter:
        query_sql += " AND services.id = ?"
        params.append(service_filter)

    query_sql += " ORDER BY reviews.timestamp DESC"
    cur.execute(query_sql, params)
    reviews = cur.fetchall()

    cur.execute("SELECT id, name FROM services")
    services = cur.fetchall()

    conn.close()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "reviews": reviews,
        "services": services,
        "query": q,
        "service_filter": service_filter
    })


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register")
def register(username: str = Form(...), password: str = Form(...)):
    conn, cur = get_db()
    try:
        cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
    except sqlite3.IntegrityError:
        return HTMLResponse("Пользователь с таким именем уже существует", status_code=400)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(response: Response, username: str = Form(...), password: str = Form(...)):
    conn, cur = get_db()
    cur.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, password))
    row = cur.fetchone()
    if not row:
        return HTMLResponse("Неверный логин или пароль", status_code=401)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(key="user_id", value=str(row[0]))
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("user_id")
    return response


@app.post("/add")
def add_review(request: Request, service_id: int = Form(...), rating: int = Form(...), comment: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    timestamp = datetime.utcnow().isoformat()
    conn, cur = get_db()
    cur.execute("INSERT INTO reviews (user_id, service_id, rating, comment, timestamp) VALUES (?, ?, ?, ?, ?)",
                (user[0], service_id, rating, comment, timestamp))
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)


@app.post("/delete/{review_id}")
def delete_review(request: Request, review_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    conn, cur = get_db()
    cur.execute("SELECT user_id FROM reviews WHERE id = ?", (review_id,))
    row = cur.fetchone()
    if row and (row[0] == user[0] or user[2] == "admin"):
        cur.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
        conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)


@app.get("/add_service", response_class=HTMLResponse)
def add_service_form(request: Request):
    user = get_current_user(request)
    if not user or user[2] != "admin":
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("add_service.html", {"request": request, "user": user})


@app.post("/add_service")
def add_service(request: Request, name: str = Form(...)):
    user = get_current_user(request)
    if not user or user[2] != "admin":
        return RedirectResponse("/", status_code=303)

    conn, cur = get_db()
    cur.execute("INSERT INTO services (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)


# Новый роут для редактирования
@app.get("/edit/{review_id}", response_class=HTMLResponse)
def edit_form(request: Request, review_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    conn, cur = get_db()
    cur.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
    review = cur.fetchone()
    if not review:
        conn.close()
        return HTMLResponse("Отзыв не найден", status_code=404)

    if review[1] != user[0] and user[2] != "admin":
        conn.close()
        return HTMLResponse("Доступ запрещён", status_code=403)

    cur.execute("SELECT id, name FROM services")
    services = cur.fetchall()
    conn.close()
    return templates.TemplateResponse("edit.html", {"request": request, "review": review, "services": services})


@app.post("/edit/{review_id}")
def edit_review(request: Request, review_id: int, service_id: int = Form(...), rating: int = Form(...), comment: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    conn, cur = get_db()
    cur.execute("SELECT user_id FROM reviews WHERE id = ?", (review_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return HTMLResponse("Отзыв не найден", status_code=404)

    if row[0] != user[0] and user[2] != "admin":
        conn.close()
        return HTMLResponse("Доступ запрещён", status_code=403)

    cur.execute("UPDATE reviews SET service_id = ?, rating = ?, comment = ? WHERE id = ?", (service_id, rating, comment, review_id))
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)
