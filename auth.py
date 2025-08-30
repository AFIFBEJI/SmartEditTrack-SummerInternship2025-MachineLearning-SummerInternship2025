# auth.py — robuste au cold start Render
import os, csv, uuid, sqlite3
from datetime import datetime, timedelta
from passlib.context import CryptContext

DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "smartedittrack.db")
PWD_CTX = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_conn():
    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,
    )
    ensure_schema(conn)
    return conn

def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name  TEXT NOT NULL,
            role       TEXT NOT NULL,
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

def _hash(p): return PWD_CTX.hash(p)
def _verify(ph, p):
    try: return PWD_CTX.verify(p, ph)
    except Exception: return False

def create_user(conn, user_id, first_name, last_name, role, password_plain, class_name=None):
    conn.execute(
        "INSERT INTO users(id, first_name, last_name, role, class_name, password_hash) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, first_name, last_name, role, class_name, _hash(password_plain)),
    )
    conn.commit()

def set_password_for_user(conn, user_id, new_password):
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash(new_password), user_id))
    conn.commit()

def change_password(conn, user_id, current_pwd, new_pwd):
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not _verify(row[0], current_pwd):
        return False
    set_password_for_user(conn, user_id, new_pwd)
    return True

def create_or_update_admin_from_env(conn):
    admin_id = (os.getenv("ADMIN_ID") or "").strip()
    admin_pw = (os.getenv("ADMIN_PASSWORD") or "").strip()
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
    conn = get_conn()
    try:
        create_or_update_admin_from_env(conn)
    finally:
        conn.close()

def auth_user(conn, user_id, password_plain):
    # Robustesse: si la table n’existe pas (cold start), on répare et on retente
    sql = "SELECT id, first_name, last_name, role, class_name, password_hash FROM users WHERE id=?"
    try:
        row = conn.execute(sql, (user_id.strip(),)).fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            ensure_schema(conn)
            create_or_update_admin_from_env(conn)
            row = conn.execute(sql, (user_id.strip(),)).fetchone()
        else:
            raise
    if not row or not _verify(row[5], password_plain.strip()):
        return None
    return {"id": row[0], "first_name": row[1], "last_name": row[2],
            "role": row[3], "class_name": row[4]}

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
    return conn.execute("SELECT * FROM submissions WHERE user_id=? ORDER BY submitted_at DESC",
                        (user_id,)).fetchall()

def create_session(conn, user_id, ttl_hours=12):
    tok = uuid.uuid4().hex
    expires = datetime.utcnow() + timedelta(hours=ttl_hours)
    conn.execute("INSERT INTO sessions(token, user_id, expires_at) VALUES (?,?,?)",
                 (tok, user_id, expires))
    conn.commit()
    return tok

def get_user_by_token(conn, token: str):
    if not token:
        return None
    row = conn.execute("""
        SELECT u.id, u.first_name, u.last_name, u.role, u.class_name
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token=? AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)
    """, (token,)).fetchone()
    if not row: return None
    return {"id": row[0], "first_name": row[1], "last_name": row[2],
            "role": row[3], "class_name": row[4]}

def delete_session(conn, token: str):
    if token:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()

def upsert_student(conn, user_id, first_name, last_name, class_name, default_pwd="changeme"):
    exists = conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is not None
    if exists:
        conn.execute("UPDATE users SET first_name=?, last_name=?, class_name=? WHERE id=?",
                     (first_name, last_name, class_name, user_id))
    else:
        conn.execute(
            "INSERT INTO users (id, first_name, last_name, role, class_name, password_hash) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, first_name, last_name, "student", class_name, _hash(default_pwd))
        )
    conn.commit()

def import_students_csv(conn, csv_path, class_name, default_pwd="changeme"):
    created, updated = 0, 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            uid  = (row.get("id") or "").strip()
            nom  = (row.get("nom") or "").strip()
            pren = (row.get("prenom") or "").strip()
            if not uid: continue
            existed = conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone() is not None
            upsert_student(conn, uid, pren, nom, class_name, default_pwd=default_pwd)
            if existed: updated += 1
            else:       created += 1
    return created, updated
# auth.py — robuste au cold start Render
import os, csv, uuid, sqlite3
from datetime import datetime, timedelta
from passlib.context import CryptContext

# --------- CONFIG / CHEMINS ---------
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "smartedittrack.db")

PWD_CTX = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --------- DB ---------
def get_conn():
    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,
    )
    ensure_schema(conn)
    return conn

def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name  TEXT NOT NULL,
            role       TEXT NOT NULL,
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


# --------- UTILS ---------
def _hash(p): 
    return PWD_CTX.hash(p)

def _verify(ph, p):
    try:
        return PWD_CTX.verify(p, ph)
    except Exception:
        return False


# --------- ADMIN / BOOTSTRAP ---------
def create_user(conn, user_id, first_name, last_name, role, password_plain, class_name=None):
    conn.execute(
        "INSERT INTO users(id, first_name, last_name, role, class_name, password_hash) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, first_name, last_name, role, class_name, _hash(password_plain)),
    )
    conn.commit()

def set_password_for_user(conn, user_id, new_password):
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash(new_password), user_id))
    conn.commit()

def change_password(conn, user_id, current_pwd, new_pwd):
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not _verify(row[0], current_pwd):
        return False
    set_password_for_user(conn, user_id, new_pwd)
    return True

def create_or_update_admin_from_env(conn):
    admin_id = (os.getenv("ADMIN_ID") or "").strip()
    admin_pw = (os.getenv("ADMIN_PASSWORD") or "").strip()
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
    conn = get_conn()
    try:
        create_or_update_admin_from_env(conn)
    finally:
        conn.close()


# --------- AUTH ---------
def auth_user(conn, user_id, password_plain):
    # robustesse: si "no such table", on recrée le schéma + admin puis on retente
    sql = "SELECT id, first_name, last_name, role, class_name, password_hash FROM users WHERE id=?"
    try:
        row = conn.execute(sql, (user_id.strip(),)).fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            ensure_schema(conn)
            create_or_update_admin_from_env(conn)
            row = conn.execute(sql, (user_id.strip(),)).fetchone()
        else:
            raise
    if not row or not _verify(row[5], password_plain.strip()):
        return None
    return {"id": row[0], "first_name": row[1], "last_name": row[2],
            "role": row[3], "class_name": row[4]}


# --------- TRACKING ---------
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
    return conn.execute("SELECT * FROM submissions WHERE user_id=? ORDER BY submitted_at DESC",
                        (user_id,)).fetchall()


# --------- SESSIONS ---------
def create_session(conn, user_id, ttl_hours=12):
    tok = uuid.uuid4().hex
    expires = datetime.utcnow() + timedelta(hours=ttl_hours)
    conn.execute("INSERT INTO sessions(token, user_id, expires_at) VALUES (?,?,?)",
                 (tok, user_id, expires))
    conn.commit()
    return tok

def get_user_by_token(conn, token: str):
    if not token:
        return None
    row = conn.execute("""
        SELECT u.id, u.first_name, u.last_name, u.role, u.class_name
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token=? AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)
    """, (token,)).fetchone()
    if not row:
        return None
    return {"id": row[0], "first_name": row[1], "last_name": row[2],
            "role": row[3], "class_name": row[4]}

def delete_session(conn, token: str):
    if token:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()


# --------- ETUDIANTS (MDP initial = identifiant) ---------
def upsert_student(conn, user_id, first_name, last_name, class_name,
                   default_pwd="id", reset_password=False):
    """
    Crée / met à jour un étudiant.
    - default_pwd="id"   -> mdp initial = identifiant (ETUDxxx)
      default_pwd="xxx"  -> mdp initial = 'xxx'
    - reset_password=True -> remet le mdp lors d'une synchro
    """
    exists = conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is not None

    # quel mdp initial ?
    initial_pwd = user_id if (default_pwd == "id") else default_pwd

    if exists:
        conn.execute(
            "UPDATE users SET first_name=?, last_name=?, class_name=? WHERE id=?",
            (first_name, last_name, class_name, user_id)
        )
        if reset_password:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash(initial_pwd), user_id))
    else:
        conn.execute(
            "INSERT INTO users (id, first_name, last_name, role, class_name, password_hash) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, first_name, last_name, "student", class_name, _hash(initial_pwd))
        )
    conn.commit()

def import_students_csv(conn, csv_path, class_name, default_pwd="id", reset_password=False):
    """
    CSV attendu: colonnes 'id, nom, prenom'
    default_pwd="id"  -> mdp initial = identifiant (recommandé)
    reset_password=True -> réinitialise le mdp à la synchro
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
            upsert_student(conn, uid, pren, nom, class_name,
                           default_pwd=default_pwd, reset_password=reset_password)
            if existed: updated += 1
            else:       created += 1
    return created, updated
