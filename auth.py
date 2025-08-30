# auth.py  — version fusionnée (DB + sécurité + bootstrap admin)
import os, csv, uuid, sqlite3
from datetime import datetime, timedelta
from passlib.context import CryptContext

# --------- CONFIG / CHEMINS ---------
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "smartedittrack.db")

PWD_CTX = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --------- CONNEXION & SCHEMAS ---------
def get_conn():
    """Ouvre une connexion SQLite (et garantit le schéma)."""
    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,
    )
    ensure_schema(conn)
    return conn

def ensure_schema(conn):
    """Crée les tables si besoin (idempotent)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name  TEXT NOT NULL,
            role       TEXT NOT NULL,   -- 'student' | 'admin'
            class_name TEXT,
            password_hash TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            status TEXT DEFAULT 'received',
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logins(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            ip TEXT,
            user_agent TEXT,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions(
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    """)
    conn.commit()


# --------- UTILISATEURS / AUTH ---------
def _hash(p: str) -> str:
    return PWD_CTX.hash(p)

def _verify(ph: str, p: str) -> bool:
    try:
        return PWD_CTX.verify(p, ph)
    except Exception:
        return False

def create_user(conn, user_id, first_name, last_name, role, password_plain, class_name=None):
    ph = _hash(password_plain)
    conn.execute(
        "INSERT INTO users(id, first_name, last_name, role, class_name, password_hash) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, first_name, last_name, role, class_name, ph),
    )
    conn.commit()

def set_password_for_user(conn, user_id, new_password):
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash(new_password), user_id))
    conn.commit()

def change_password(conn, user_id, current_pwd, new_pwd) -> bool:
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return False
    if not _verify(row[0], current_pwd):
        return False
    set_password_for_user(conn, user_id, new_pwd)
    return True

def auth_user(conn, user_id, password_plain):
    row = conn.execute(
        "SELECT id, first_name, last_name, role, class_name, password_hash FROM users WHERE id=?",
        (user_id.strip(),)
    ).fetchone()
    if not row:
        return None
    if not _verify(row[5], password_plain.strip()):
        return None
    return {"id": row[0], "first_name": row[1], "last_name": row[2],
            "role": row[3], "class_name": row[4]}


# --------- TRACKING / DÉPÔTS ---------
def record_login(conn, user_id, ip=None, ua=None):
    conn.execute("INSERT INTO logins(user_id, ip, user_agent) VALUES (?,?,?)", (user_id, ip, ua))
    conn.commit()

def record_submission(conn, user_id, filename, status="received"):
    conn.execute(
        "INSERT INTO submissions(user_id, filename, status) VALUES (?,?,?)",
        (user_id, filename, status)
    )
    conn.commit()

def list_submissions(conn):
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM submissions ORDER BY submitted_at DESC").fetchall()

def list_submissions_by_user(conn, user_id):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM submissions WHERE user_id=? ORDER BY submitted_at DESC", (user_id,)
    ).fetchall()


# --------- SESSIONS PERSISTANTES ---------
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
        WHERE s.token = ?
          AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)
    """, (token,)).fetchone()
    if not row:
        return None
    return {"id": row[0], "first_name": row[1], "last_name": row[2],
            "role": row[3], "class_name": row[4]}

def delete_session(conn, token: str):
    if token:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()


# --------- IMPORT CSV ETUDIANTS ---------
def upsert_student(conn, user_id, first_name, last_name, class_name, default_pwd="changeme"):
    """Crée ou met à jour un étudiant et sa classe."""
    exists = conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is not None
    if exists:
        conn.execute(
            "UPDATE users SET first_name=?, last_name=?, class_name=? WHERE id=?",
            (first_name, last_name, class_name, user_id)
        )
    else:
        conn.execute(
            "INSERT INTO users (id, first_name, last_name, role, class_name, password_hash) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, first_name, last_name, "student", class_name, _hash(default_pwd))
        )
    conn.commit()

def import_students_csv(conn, csv_path, class_name, default_pwd="changeme"):
    """
    CSV attendu: colonnes id, nom, prenom
    -> insère / met à jour chaque étudiant et l’assigne à la classe.
    """
    created, updated = 0, 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            uid  = (row.get("id") or "").strip()
            nom  = (row.get("nom") or "").strip()
            pren = (row.get("prenom") or "").strip()
            if not uid:
                continue
            existed = conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone() is not None
            upsert_student(conn, uid, pren, nom, class_name, default_pwd=default_pwd)
            if existed: updated += 1
            else:       created += 1
    return created, updated


# --------- BOOTSTRAP ADMIN (ENV) ---------
def create_or_update_admin_from_env(conn):
    """
    Lit ADMIN_ID et ADMIN_PASSWORD et crée/MAJ l’admin au démarrage.
    """
    admin_id = os.getenv("ADMIN_ID", "").strip()
    admin_pw = os.getenv("ADMIN_PASSWORD", "").strip()
    if not admin_id or not admin_pw:
        print("[bootstrap] ADMIN_ID / ADMIN_PASSWORD manquants -> skip")
        return

    ensure_schema(conn)
    row = conn.execute("SELECT id FROM users WHERE id=?", (admin_id,)).fetchone()
    if row:
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (admin_id,))
        set_password_for_user(conn, admin_id, admin_pw)
        print(f"[bootstrap] Admin '{admin_id}' mis à jour.")
    else:
        conn.execute(
            "INSERT INTO users (id, first_name, last_name, role, class_name, password_hash) "
            "VALUES (?, '', '', 'admin', '', ?)",
            (admin_id, _hash(admin_pw))
        )
        conn.commit()
        print(f"[bootstrap] Admin '{admin_id}' créé.")

def bootstrap_on_startup():
    """À appeler une fois au démarrage de l’app (main.py)."""
    conn = get_conn()
    try:
        create_or_update_admin_from_env(conn)
    finally:
        conn.close()
