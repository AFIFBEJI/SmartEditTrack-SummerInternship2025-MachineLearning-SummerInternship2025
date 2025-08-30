# create_admin.py  — bootstrap non interactif pour Render
import os, sqlite3, sys
from pathlib import Path

# -------- Réglages depuis l'env --------
DATA_DIR   = os.environ.get("DATA_DIR", "./")
DB_PATH    = Path(DATA_DIR) / "smartedittrack.db"
ADMIN_ID   = os.environ.get("ADMIN_ID", "admin").strip()
ADMIN_PWD  = os.environ.get("ADMIN_PASSWORD", "ChangeMoi!2025")

# Hash (passlib[bcrypt] est déjà dans requirements.txt)
try:
    from passlib.hash import bcrypt
except Exception as e:
    print(f"[create_admin] ERREUR: passlib/bcrypt manquant ({e})", file=sys.stderr)
    sys.exit(1)

def ensure_db_file():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        # DB vide : on la crée, le schéma sera créé ailleurs (db_init.py) ou on accepte qu'il existe déjà.
        open(DB_PATH, "a").close()

def upsert_admin():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Vérifie que la table users existe
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cur.fetchone():
        # crée un schéma minimal si rien n’existe (sans casser si plus de colonnes existent dans ta DB finale)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            password_hash TEXT,
            role TEXT,
            class_name TEXT
        )
        """)

    # Colonnes disponibles
    cur.execute("PRAGMA table_info(users)")
    cols = [c[1] for c in cur.fetchall()]

    # Prépare la ligne admin selon les colonnes existantes
    row = {
        "id": ADMIN_ID,
        "password_hash": bcrypt.hash(ADMIN_PWD),
        "role": "prof",
        "class_name": ""
    }
    keep_cols = [c for c in row.keys() if c in cols]

    # Existence ?
    cur.execute("SELECT 1 FROM users WHERE id=?", (ADMIN_ID,))
    exists = cur.fetchone() is not None

    if exists:
        # UPDATE password (et role/class_name si présents)
        set_clause = ", ".join([f"{c}=?" for c in keep_cols if c != "id"])
        values = [row[c] for c in keep_cols if c != "id"] + [ADMIN_ID]
        cur.execute(f"UPDATE users SET {set_clause} WHERE id=?", values)
        print(f"[create_admin] ADMIN '{ADMIN_ID}' mis à jour.")
    else:
        # INSERT
        ins_cols = ", ".join(keep_cols)
        placeholders = ", ".join(["?"] * len(keep_cols))
        values = [row[c] for c in keep_cols]
        cur.execute(f"INSERT INTO users ({ins_cols}) VALUES ({placeholders})", values)
        print(f"[create_admin] ADMIN '{ADMIN_ID}' créé.")

    conn.commit()
    conn.close()

def main():
    ensure_db_file()
    upsert_admin()
    print(f"[create_admin] OK — DB: {DB_PATH}")

if __name__ == "__main__":
    main()
