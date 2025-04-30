import sqlite3

conn = sqlite3.connect("reviews.db")
cur = conn.cursor()

username = "traweru"  # ← замени на нужного
cur.execute("UPDATE users SET role = 'admin' WHERE username = ?", (username,))
conn.commit()
conn.close()

print(f"Пользователь '{username}' теперь администратор.")
