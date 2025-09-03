# create_admin.py
from auth import get_conn, create_or_update_admin_from_env
from sb_auth import get_user as sb_get_user, get_profile as sb_get_profile


if __name__ == "__main__":
    conn = get_conn()
    create_or_update_admin_from_env(conn)
    conn.close()

def auth_user_via_supabase(conn):
    """
    Lit l'utilisateur courant depuis Supabase (session côté serveur) et
    renvoie un dict {id, first_name, last_name, role, class_name, email, full_name}
    pour l'app. On n'utilise plus password_hash local pour l'auth.
    """
    su = sb_get_user()
    if not su or not getattr(su, "user", None):
        return None

    uid = su.user.id
    email = su.user.email or ""

    # Rôle via Supabase (profiles)
    prof = sb_get_profile(uid)
    role = prof.get("role", "student")
    full_name = prof.get("full_name", "") or ""

    # On garde ta table users locale pour class_name, etc.
    row = conn.execute(
        "SELECT first_name,last_name,class_name FROM users WHERE id=?",
        (uid,)
    ).fetchone()

    first_name, last_name, class_name = "", "", ""
    if row:
        first_name, last_name, class_name = row[0] or "", row[1] or "", row[2] or ""

    return {
        "id": uid,
        "first_name": first_name,
        "last_name": last_name,
        "role": role,
        "class_name": class_name,
        "email": email,
        "full_name": full_name
    }
