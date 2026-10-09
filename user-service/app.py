from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import requests

app = Flask(__name__)
DB = "user.db"   # this service's OWN database


# ---------- Database helpers ----------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'spectator',
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


# ---------- Health check ----------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"service": "user-service", "status": "UP"})


# ---------- API v1 ----------
# REGISTER
@app.route("/api/v1/users", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    for field in ("name", "email", "password"):
        if not data.get(field):
            return jsonify({"error": f"'{field}' is required"}), 400
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO users (name, email, password, role, phone) VALUES (?,?,?,?,?)",
            (data["name"], data["email"],
             generate_password_hash(data["password"]),
             data.get("role", "spectator"), data.get("phone"))
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "User registered"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email already exists"}), 400


# LIST all users (v1: basic fields)
@app.route("/api/v1/users", methods=["GET"])
def list_users_v1():
    conn = get_db()
    rows = conn.execute("SELECT id, name, email, role FROM users").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# GET one user (v1)
@app.route("/api/v1/users/<int:user_id>", methods=["GET"])
def get_user_v1(user_id):
    conn = get_db()
    row = conn.execute("SELECT id, name, email, role FROM users WHERE id=?",
                       (user_id,)).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": "User not found"}), 404
    return jsonify(dict(row))


# UPDATE
@app.route("/api/v1/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "'name' is required"}), 400
    conn = get_db()
    cur = conn.execute("UPDATE users SET name=?, role=?, phone=? WHERE id=?",
                       (data["name"], data.get("role", "spectator"),
                        data.get("phone"), user_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"message": "User updated"})


# DELETE
@app.route("/api/v1/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"message": "User deleted"})


# LOGIN
@app.route("/api/v1/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    if not data.get("email") or not data.get("password"):
        return jsonify({"error": "email and password required"}), 400
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=?", (data["email"],)).fetchone()
    conn.close()
    if row is None or not check_password_hash(row["password"], data["password"]):
        return jsonify({"error": "Invalid email or password"}), 401
    return jsonify({"message": "Login successful",
                    "user": {"id": row["id"], "name": row["name"], "role": row["role"]}})


# ---------- API v2 (extended fields) ----------
@app.route("/api/v2/users", methods=["GET"])
def list_users_v2():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, email, role, phone, created_at FROM users").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/v2/users/<int:user_id>", methods=["GET"])
def get_user_v2(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, name, email, role, phone, created_at FROM users WHERE id=?",
        (user_id,)).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": "User not found"}), 404
    return jsonify(dict(row))


# ---------- Service Registry ----------
def register_with_registry():
    try:
        requests.post("http://localhost:5000/register",
                      json={"name": "user-service", "url": "http://localhost:5001"},
                      timeout=2)
        print("Registered with service registry")
    except Exception:
        print("Registry not running yet, skipping registration")


# ---------- Start ----------
if __name__ == "__main__":
    init_db()
    register_with_registry()
    app.run(port=5001, debug=True)