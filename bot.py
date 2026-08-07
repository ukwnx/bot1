import os
import random
import sqlite3
import aiohttp
import pg8000
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

current_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(current_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "altvault_super_secret_key_1337")

# --- DATABASE INJECTION MANAGER ---
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        return sqlite3.connect(os.path.join(current_dir, "database.db"))
    
    try:
        clean_url = DATABASE_URL.replace("postgresql://", "")
        user_pass, host_db = clean_url.split("@")
        username, password = user_pass.split(":")
        host_port, dbname = host_db.split("/")
        host, port = host_port.split(":")
        if "?" in dbname:
            dbname = dbname.split("?")
            
        return pg8000.connect(
            user=username,
            password=password,
            host=host,
            port=int(port),
            database=dbname
        )
    except Exception as parse_error:
        print(f"URL Parsing Engine Log: {parse_error}")
        return sqlite3.connect(os.path.join(current_dir, "database.db"))

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if not DATABASE_URL or isinstance(conn, sqlite3.Connection):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, role TEXT DEFAULT 'Member'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                user_id TEXT, tier TEXT, claim_date TEXT, claim_count INTEGER, PRIMARY KEY (user_id, tier, claim_date)
            )
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT DEFAULT 'Member'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                user_id TEXT, tier TEXT, claim_date TEXT, claim_count INTEGER, PRIMARY KEY (user_id, tier, claim_date)
            )
        """)
        
    p = "?" if (not DATABASE_URL or isinstance(conn, sqlite3.Connection)) else "%s"
    cursor.execute(f"SELECT * FROM users WHERE username = {p}", ('admin',))
    if not cursor.fetchone():
        hashed_pw = generate_password_hash("admin123")
        cursor.execute(f"INSERT INTO users (username, password, role) VALUES ({p}, {p}, {p})", ('admin', hashed_pw, 'Admin'))
    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"Database initialization system update log: {e}")

# --- TIER ARRAYS CONFIGURATION ---
TIER_CONFIG = {
    "free": {"file": os.path.join(current_dir, "free.txt"), "limit": 2, "role_required": "Member", "link": "https://work.ink/2IoF/key-system"},
    "premium": {"file": os.path.join(current_dir, "premium.txt"), "limit": 5, "role_required": "Premium"},
    "vip": {"file": os.path.join(current_dir, "vip.txt"), "limit": 10, "role_required": "VIP"}
}

for tier in TIER_CONFIG.values():
    if "file" in tier and not os.path.exists(tier["file"]):
        with open(tier["file"], "w", encoding="utf-8") as f: pass

def count_lines(file_path):
    if not os.path.exists(file_path): return 0
    with open(file_path, "r", encoding="utf-8") as f:
        return len([line for line in f if line.strip()])

def get_daily_claims(user_id, tier):
    today = str(date.today())
    conn = get_db_connection()
    cursor = conn.cursor()
    p = "?" if (not DATABASE_URL or isinstance(conn, sqlite3.Connection)) else "%s"
    cursor.execute(f"SELECT claim_count FROM claims WHERE user_id = {p} AND tier = {p} AND claim_date = {p}", (str(user_id), tier, today))
    row = cursor.fetchone()
    conn.close()
    return row if row else 0

def increment_daily_claims(user_id, tier):
    today = str(date.today())
    current = get_daily_claims(user_id, tier)
    conn = get_db_connection()
    cursor = conn.cursor()
    p = "?" if (not DATABASE_URL or isinstance(conn, sqlite3.Connection)) else "%s"
    if current == 0:
        cursor.execute(f"INSERT INTO claims VALUES ({p}, {p}, {p}, 1)", (str(user_id), tier, today))
    else:
        cursor.execute(f"UPDATE claims SET claim_count = {p} WHERE user_id = {p} AND tier = {p} AND claim_date = {p}", (current + 1, str(user_id), tier, today))
    conn.commit()
    conn.close()

async def verify_workink_key(key: str) -> bool:
    base_address = "https://work" + ".ink/api/public/v1/keys/verify"
    url = f"{base_address}?key={key}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("valid", False)
        except Exception:
            return False
    return False
# --- PLATFORM ROUTES ---
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    stock_data = {t: count_lines(c["file"]) for t, c in TIER_CONFIG.items()}
    return render_template("index.html", username=session['username'], role=session['role'], stock=stock_data, free_link=TIER_CONFIG["free"]["link"])

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "?" if (not DATABASE_URL or isinstance(conn, sqlite3.Connection)) else "%s"
        cursor.execute(f"SELECT id, username, password, role FROM users WHERE username = {p}", (username,))
        user = cursor.fetchone()
        conn.close()
        
        if user and check_password_hash(user[2], password):
            session['user_id'] = str(user[0])  # Extracts clean string ID integer
            session['username'] = user[1]
            session['role'] = user[3]
            return redirect(url_for('index'))
        return render_template("login.html", error="Invalid username or password.")
    return render_template("login.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        if not username or not password:
            return render_template("register.html", error="Fields cannot be empty.")
            
        hashed_pw = generate_password_hash(password)
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "?" if (not DATABASE_URL or isinstance(conn, sqlite3.Connection)) else "%s"
        try:
            cursor.execute(f"INSERT INTO users (username, password) VALUES ({p}, {p})", (username, hashed_pw))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except Exception:
            conn.close()
            return render_template("register.html", error="Username already exists.")
    return render_template("register.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if 'user_id' not in session or session['role'] != 'Admin':
        return "Access Denied", 403
        
    conn = get_db_connection()
    cursor = conn.cursor()
    p = "?" if (not DATABASE_URL or isinstance(conn, sqlite3.Connection)) else "%s"
    
    if request.method == 'POST':
        if 'update_role' in request.form:
            target_uid = request.form['user_id']
            new_role = request.form['role']
            cursor.execute(f"UPDATE users SET role = {p} WHERE id = {p}", (new_role, target_uid))
            conn.commit()
        elif 'restock' in request.form:
            tier = request.form['tier']
            file_data = request.files['file']
            if file_data and tier in TIER_CONFIG:
                lines = file_data.read().decode('utf-8').splitlines()
                with open(TIER_CONFIG[tier]["file"], "a", encoding="utf-8") as f:
                    for line in lines:
                        if line.strip(): f.write(line.strip() + "\n")
                        
    cursor.execute("SELECT id, username, role FROM users WHERE username != 'admin'")
    all_users = cursor.fetchall()
    conn.close()
    return render_template("admin.html", users=all_users)

@app.route('/api/generate', methods=['POST'])
async def api_generate():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Unauthorized."})
        
    data = request.get_json() or {}
    tier = data.get("tier")
    key = data.get("key", "").strip()
    
    if tier not in TIER_CONFIG:
        return jsonify({"success": False, "message": "Invalid tier select."})
        
    config = TIER_CONFIG[tier]
    user_role = session['role']
    
    if user_role != "Admin":
        if tier == "premium" and user_role not in ["Premium", "VIP"]:
            return jsonify({"success": False, "message": "Requires Premium Role Status."})
        elif tier == "vip" and user_role != "VIP":
            return jsonify({"success": False, "message": "Requires VIP Role Status."})

        current_claims = get_daily_claims(session['user_id'], tier)
        if current_claims >= config["limit"]:
            return jsonify({"success": False, "message": f"Daily limit of {config['limit']} reached."})

    if tier == "free" and user_role != "Admin":
        if not key:
            return jsonify({"success": False, "message": "Verification key required."})
        is_valid = await verify_workink_key(key)
        if not is_valid:
            return jsonify({"success": False, "message": "Invalid or expired Work.ink key."})

    file_path = config["file"]
    if count_lines(file_path) == 0:
        return jsonify({"success": False, "message": "This tier is out of stock!"})

    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
        
    selected_account = random.choice(lines)
    lines.remove(selected_account)
    
    with open(file_path, "w", encoding="utf-8") as f:
        for line in lines: f.write(line + "\n")
        
    if user_role != "Admin":
        increment_daily_claims(session['user_id'], tier)
        
    return jsonify({"success": True, "account": selected_account})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
