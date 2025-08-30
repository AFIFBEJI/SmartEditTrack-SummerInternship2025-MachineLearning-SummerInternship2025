# create_admin.py
from auth import get_conn, ensure_schema, create_user
import getpass

def main():
    conn = get_conn()
    ensure_schema(conn)
    prof_id = input("ID admin (ex: PROF001): ").strip()
    prenom = input("Prénom: ").strip()
    nom = input("Nom: ").strip()
    mdp = getpass.getpass("Mot de passe admin: ").strip()
    create_user(conn, prof_id, prenom, nom, role="admin", password_plain=mdp, class_name=None)
    print("✅ Admin créé.")

if __name__ == "__main__":
    main()
