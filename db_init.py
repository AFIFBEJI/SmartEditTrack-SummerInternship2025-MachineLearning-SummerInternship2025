# db_init.py
import csv
from auth import get_conn, ensure_schema, create_user
import sqlite3

CSV_PATH = "liste_etudiants.csv"   # must have headers: id,nom,prenom

def main():
    conn = get_conn()
    ensure_schema(conn)

    created, skipped = 0, 0
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        # verify headers
        expected = {"id", "nom", "prenom"}
        if set(h.strip().lower() for h in r.fieldnames) != expected:
            raise SystemExit(
                f"En-têtes CSV invalides. Attendus: {expected} ; trouvés: {r.fieldnames}"
            )

        for row in r:
            etu_id = row["id"].strip()
            nom = row["nom"].strip()
            prenom = row["prenom"].strip()

            try:
                # mot de passe par défaut = ID (à changer après 1ère connexion)
                create_user(conn,
                            user_id=etu_id,
                            first_name=prenom,
                            last_name=nom,
                            role="student",
                            password_plain=etu_id,
                            class_name="CLASS_A")
                print(f"OK: {etu_id} {prenom} {nom}")
                created += 1
            except sqlite3.IntegrityError:
                # id déjà présent (clé unique) -> on ignore
                print(f"SKIP (existe déjà): {etu_id}")
                skipped += 1

    print(f"\n✅ Import terminé. Créés: {created} | Ignorés (existaient déjà): {skipped}")

if __name__ == "__main__":
    main()
