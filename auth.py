# auth.py
import sqlite3
from passlib.context import CryptContext
from datetime import datetime, timedelta
import uuid

PWD_CTX = CryptContext(schemes=["bcrypt"], deprecated="auto")
DB_PATH = "smartedittrack.db"

# ---------------------------
# Connexion DB
# ---------------------------
def get_conn():
    return sqlite3.connect(
        DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )

def ensure_schema(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        role TEXT NOT NULL,            -- 'student' | 'admin'
        class_name TEXT,
        password_hash TEXT NOT NULL
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        status TEXT DEFAULT 'received',
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS logins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        ip TEXT,
        user_agent TEXT,
        ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

# ---------------------------
# Utilisateurs
# ---------------------------
def create_user(conn, user_id, first_name, last_name, role, password_plain, class_name=None):
    ph = PWD_CTX.hash(password_plain)
    conn.execute(
        "INSERT INTO users(id, first_name, last_name, role, class_name, password_hash) VALUES (?,?,?,?,?,?)",
        (user_id, first_name, last_name, role, class_name, ph)
    )
    conn.commit()

def auth_user(conn, user_id, password_plain):
    row = conn.execute("SELECT id, first_name, last_name, role, class_name, password_hash FROM users WHERE id=?",
                       (user_id,)).fetchone()
    if not row:
        return None
    if PWD_CTX.verify(password_plain, row[5]):
        return {"id": row[0], "first_name": row[1], "last_name": row[2], "role": row[3], "class_name": row[4]}
    return None

def change_password(conn, user_id, current_pwd, new_pwd):
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return False
    if not PWD_CTX.verify(current_pwd, row[0]):
        return False
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (PWD_CTX.hash(new_pwd), user_id))
    conn.commit()
    return True

# ---------------------------
# Tracking
# ---------------------------
def record_login(conn, user_id, ip=None, ua=None):
    conn.execute("INSERT INTO logins(user_id, ip, user_agent) VALUES (?,?,?)", (user_id, ip, ua))
    conn.commit()

def record_submission(conn, user_id, filename, status="received"):
    conn.execute("INSERT INTO submissions(user_id, filename, status) VALUES (?,?,?)",
                 (user_id, filename, status))
    conn.commit()

def list_submissions(conn):
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM submissions ORDER BY submitted_at DESC").fetchall()

def list_submissions_by_user(conn, user_id):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM submissions WHERE user_id=? ORDER BY submitted_at DESC",
        (user_id,)
    ).fetchall()

# ---------------------------
# Sessions persistantes
# ---------------------------
def ensure_session_schema(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP
    )""")
    conn.commit()

def create_session(conn, user_id, ttl_hours=12):
    tok = uuid.uuid4().hex
    expires = datetime.utcnow() + timedelta(hours=ttl_hours)
    conn.execute(
        "INSERT INTO sessions(token, user_id, expires_at) VALUES (?,?,?)",
        (tok, user_id, expires)
    )
    conn.commit()
    return tok

def get_user_by_token(conn, token: str):
    if not token:
        return None
    row = conn.execute("""
        SELECT u.id, u.first_name, u.last_name, u.role, u.class_name
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)
    """, (token,)).fetchone()
    if not row:
        return None
    return {"id": row[0], "first_name": row[1], "last_name": row[2], "role": row[3], "class_name": row[4]}

def delete_session(conn, token: str):
    if token:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()


# --- Synchro des étudiants depuis un CSV vers la BD -----------------
def upsert_student(conn, user_id, first_name, last_name, class_name, default_pwd="changeme"):
    """Crée ou met à jour un étudiant avec sa classe."""
    row = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if row:
        conn.execute(
            "UPDATE users SET first_name=?, last_name=?, class_name=? WHERE id=?",
            (first_name, last_name, class_name, user_id)
        )
    else:
        from passlib.context import CryptContext
        PWD_CTX = CryptContext(schemes=["bcrypt"], deprecated="auto")
        ph = PWD_CTX.hash(default_pwd)
        conn.execute(
            "INSERT INTO users (id, first_name, last_name, role, class_name, password_hash) VALUES (?,?,?,?,?,?)",
            (user_id, first_name, last_name, "student", class_name, ph)
        )
    conn.commit()

def import_students_csv(conn, csv_path, class_name, default_pwd="changeme"):
    """
    Lit un CSV avec colonnes: id, nom, prenom
    -> crée/MAJ chaque étudiant et lui assigne class_name.
    """
    import csv
    created, updated = 0, 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            uid   = (row.get("id") or "").strip()
            nom   = (row.get("nom") or "").strip()
            pren  = (row.get("prenom") or "").strip()
            if not uid:
                continue
            existed = conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone() is not None
            # Mapping: CSV a 'prenom' et 'nom' -> BD: first_name, last_name
            upsert_student(conn, uid, pren, nom, class_name, default_pwd=default_pwd)
            if existed: updated += 1
            else:       created += 1
    return created, updated
