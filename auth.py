# auth.py — DB SQLite + anti brute-force + backup Supabase + emails identifiants
# -------------------------------------------------------------------------------
# Env attendues principales :
#   DATA_DIR
#   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_BUCKET, SUPABASE_DB_BACKUP_PATH
#   ADMIN_ID, ADMIN_PASSWORD
#   # Anti-bruteforce (facultatif)
#   MAX_LOGIN_FAIL=5, FAIL_WINDOW_SECS=900, LOCK_SECS=600
#   # Email (voir mailer.py) :
#   RESEND_API_KEY, RESEND_FROM
#   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_TLS, SMTP_FROM
#   APP_BASE_URL  (URL de l'app à inclure dans les emails)
# -------------------------------------------------------------------------------

import os, csv, uuid, sqlite3, re
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext

DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "smartedittrack.db")

PWD_CTX = CryptContext(schemes=["bcrypt"], deprecated="auto")

_SUPA_OK = False
_DB_REMOTE_PATH = os.getenv("SUPABASE_DB_BACKUP_PATH", "backups/smartedittrack.db")
try:
    from supa import upload_file as _supa_upload, download_to_file as _supa_download
    _SUPA_OK = True
except Exception:
    _SUPA_OK = False

# --- email helper
try:
    from mailer import send_credentials_email
except Exception:
    def send_credentials_email(*a, **k):  # fallback inoffensif
        return False

def _restore_db_if_missing():
    if _SUPA_OK and (not os.path.exists(DB_PATH)):
        ok = _supa_download(_DB_REMOTE_PATH, DB_PATH)
        print("[bootstrap] DB restaurée depuis Supabase." if ok else "[bootstrap] Pas de backup DB trouvé.")

def _backup_db():
    if _SUPA_OK and os.path.exists(DB_PATH):
        try:
            _supa_upload(DB_PATH, _DB_REMOTE_PATH, content_type="application/octet-stream")
        except Exception as e:
            print("[WARN] Échec backup DB:", e)

def get_conn():
    _restore_db_if_missing()
    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,
        timeout=30,
    )
    ensure_schema(conn)
    return conn

def _has_column(conn, table: str, col: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {r[1].lower() for r in rows}
        return col.lower() in names
    except Exception:
        return False

def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            first_name   TEXT NOT NULL,
            last_name    TEXT NOT NULL,
            role         TEXT NOT NULL,
            class_name   TEXT,
            password_hash TEXT NOT NULL
        )
    """)
    # Ajouter colonne email si absente
    if not _has_column(conn, "users", "email"):
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_throttle(
            user_id TEXT NOT NULL,
            ip      TEXT NOT NULL,
            fail_count   INTEGER DEFAULT 0,
            last_fail    TEXT,
            locked_until TEXT,
            PRIMARY KEY (user_id, ip)
        )
    """)
    conn.commit()

def _hash(p): 
    return PWD_CTX.hash(p)

def _verify(ph, p):
    try:
        return PWD_CTX.verify(p, ph)
    except Exception:
        return False

def _from_iso(s):
    try: return datetime.fromisoformat(s)
    except Exception: return None

def create_user(conn, user_id, first_name, last_name, role, password_plain, class_name=None, email=None):
    conn.execute(
        "INSERT INTO users(id, first_name, last_name, role, class_name, password_hash, email) "
        "VALUES (?,?,?,?,?,?,?)",
        (user_id, first_name, last_name, role, class_name, _hash(password_plain), email),
    )
    conn.commit(); _backup_db()

def set_password_for_user(conn, user_id, new_password):
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash(new_password), user_id))
    conn.commit(); _backup_db()

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
            "INSERT INTO users (id, first_name, last_name, role, class_name, password_hash, email) "
            "VALUES (?, '', '', 'admin', '', ?, NULL)",
            (admin_id, _hash(admin_pw))
        )
        conn.commit(); _backup_db()
        print(f"[bootstrap] Admin '{admin_id}' créé.")

def bootstrap_on_startup():
    conn = get_conn()
    try: create_or_update_admin_from_env(conn)
    finally: conn.close()

# ---------- Auth / sessions ----------
def auth_user(conn, user_id, password_plain):
    sql = "SELECT id, first_name, last_name, role, class_name, password_hash FROM users WHERE id=?"
    try:
        row = conn.execute(sql, (user_id.strip(),)).fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            ensure_schema(conn); create_or_update_admin_from_env(conn)
            row = conn.execute(sql, (user_id.strip(),)).fetchone()
        else:
            raise
    if not row or not _verify(row[5], password_plain.strip()):
        return None
    return {"id": row[0], "first_name": row[1], "last_name": row[2],
            "role": row[3], "class_name": row[4]}

def record_login(conn, user_id, ip=None, ua=None):
    conn.execute("INSERT INTO logins(user_id, ip, user_agent) VALUES (?,?,?)", (user_id, ip, ua))
    conn.commit(); _backup_db()

def record_submission(conn, user_id, filename, status="received"):
    conn.execute("INSERT INTO submissions(user_id, filename, status) VALUES (?,?,?)",
                 (user_id, filename, status))
    conn.commit(); _backup_db()

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
    conn.commit(); _backup_db()
    return tok

def get_user_by_token(conn, token: str):
    if not token: return None
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
        conn.commit(); _backup_db()

# ---------- Anti-bruteforce ----------
_MAX_LOGIN_FAIL   = int(os.getenv("MAX_LOGIN_FAIL", "5"))
_FAIL_WINDOW_SECS = int(os.getenv("FAIL_WINDOW_SECS", "900"))
_LOCK_SECS        = int(os.getenv("LOCK_SECS", "600"))

def _now_utc(): return datetime.now(timezone.utc)

def login_is_locked(conn, user_id, ip):
    row = conn.execute(
        "SELECT locked_until FROM login_throttle WHERE user_id=? AND ip=?",
        (user_id, ip)
    ).fetchone()
    if not row or not row[0]: return (False, 0)
    lu = _from_iso(row[0])
    if lu and datetime.now(timezone.utc) < lu:
        return True, int((lu - datetime.now(timezone.utc)).total_seconds())
    return False, 0

def register_failed_login(conn, user_id, ip,
                          max_fail=_MAX_LOGIN_FAIL,
                          window_secs=_FAIL_WINDOW_SECS,
                          lock_secs=_LOCK_SECS):
    now = datetime.now(timezone.utc)
    row = conn.execute(
        "SELECT fail_count, last_fail, locked_until FROM login_throttle WHERE user_id=? AND ip=?",
        (user_id, ip)
    ).fetchone()

    if row:
        fail_count, last_fail, locked_until = row
        lu = _from_iso(locked_until) if locked_until else None
        if lu and now < lu:
            return True, int((lu - now).total_seconds()), 0

        lf = _from_iso(last_fail) if last_fail else None
        count = 1 if (lf is None or (now - lf).total_seconds() > window_secs) \
                else int(fail_count or 0) + 1

        if count >= max_fail:
            lu = now + timedelta(seconds=lock_secs)
            conn.execute(
                "UPDATE login_throttle SET fail_count=?, last_fail=?, locked_until=? WHERE user_id=? AND ip=?",
                (count, now.isoformat(), lu.isoformat(), user_id, ip)
            )
            conn.commit(); _backup_db()
            return True, lock_secs, 0
        else:
            conn.execute(
                "UPDATE login_throttle SET fail_count=?, last_fail=?, locked_until=NULL WHERE user_id=? AND ip=?",
                (count, now.isoformat(), user_id, ip)
            )
            conn.commit(); _backup_db()
            return False, 0, max_fail - count
    else:
        conn.execute(
            "INSERT INTO login_throttle(user_id, ip, fail_count, last_fail, locked_until) VALUES (?,?,?,?,NULL)",
            (user_id, ip, 1, now.isoformat())
        )
        conn.commit(); _backup_db()
        return False, 0, max_fail - 1

def reset_throttle(conn, user_id, ip):
    conn.execute("DELETE FROM login_throttle WHERE user_id=? AND ip=?", (user_id, ip))
    conn.commit(); _backup_db()

# ---------- Étudiants : upsert + import CSV + emails ----------
def upsert_student(conn, user_id, first_name, last_name, class_name,
                   default_pwd="id", reset_password=False, email=None):
    """
    Crée / met à jour un étudiant.
    - default_pwd="id"   -> mdp initial = identifiant (ETUDxxx)
      default_pwd="xxx"  -> mdp initial = 'xxx'
    - reset_password=True -> remet le mdp lors d'une synchro
    - email: facultatif
    """
    exists = conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is not None
    initial_pwd = user_id if (default_pwd == "id") else default_pwd

    if exists:
        conn.execute(
            "UPDATE users SET first_name=?, last_name=?, class_name=?, email=COALESCE(?, email) WHERE id=?",
            (first_name, last_name, class_name, email, user_id)
        )
        if reset_password:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash(initial_pwd), user_id))
    else:
        conn.execute(
            "INSERT INTO users (id, first_name, last_name, role, class_name, password_hash, email) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, first_name, last_name, "student", class_name, _hash(initial_pwd), email)
        )
    conn.commit(); _backup_db()
    return initial_pwd, (not exists)  # retourne mdp initial + bool(created)

def _get_csv_val(row, key: str):
    # robuste à "Email", "email", "E-mail" etc.
    keys = {k.lower(): k for k in row.keys()}
    k = key.lower()
    if k in keys: return (row.get(keys[k]) or "").strip()
    if k == "prenom":
        for cand in ("prénom","prenom","first_name","firstname"): 
            if cand in keys: return (row.get(keys[cand]) or "").strip()
    if k == "nom":
        for cand in ("nom","last_name","lastname"): 
            if cand in keys: return (row.get(keys[cand]) or "").strip()
    if k == "email":
        for cand in ("email","e-mail","mail"): 
            if cand in keys: return (row.get(keys[cand]) or "").strip()
    return (row.get(key) or "").strip()

def import_students_csv(conn, csv_path, class_name,
                        default_pwd="id",
                        reset_password=False,
                        send_email=False,
                        login_url=None):
    """
    CSV attendu: colonnes 'id, nom, prenom' et (optionnel) 'email'
    - reset_password=True : remet le mdp (et envoie email à tous si send_email=True)
    - send_email=True     : envoie un email aux nouveaux comptes, et aussi aux MAJ si reset_password=True
    Retourne dict: {"created": int, "updated": int, "emailed": int}
    """
    created, updated, emailed = 0, 0, 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            uid  = _get_csv_val(row, "id")
            nom  = _get_csv_val(row, "nom")
            pren = _get_csv_val(row, "prenom")
            email = _get_csv_val(row, "email")
            if not uid: 
                continue

            initial_pwd, is_new = upsert_student(
                conn, uid, pren, nom, class_name,
                default_pwd=default_pwd,
                reset_password=reset_password,
                email=email or None
            )
            if is_new: created += 1
            else:      updated += 1

            if send_email and email:
                # envoyer aux nouveaux; et si reset_password, à tous
                if is_new or reset_password:
                    if send_credentials_email(email, uid, initial_pwd, login_url):
                        emailed += 1
    _backup_db()
    return {"created": created, "updated": updated, "emailed": emailed}
