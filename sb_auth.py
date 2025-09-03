# sb_auth.py — Identity via Supabase Auth (email/mdp, magic link, reset, profiles)
import os
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client, Client

# Charge .env en local (Render ignore ceci et prend ses own env vars)
load_dotenv(override=True)

def _require(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Variable d'environnement manquante: {name}")
    return v

# ---- Clés & URLs ----
SB_URL: str = _require("SUPABASE_URL")
SB_ANON: str = _require("SUPABASE_ANON_KEY")
SB_SERVICE: Optional[str] = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# Redirections multipage Streamlit (utilisées dans les mails)
# ⚠️ Assure-toi que ces URL existent aussi dans Auth → URL Configuration → Redirect URLs
RESET_REDIRECT_URL: str  = os.environ.get("RESET_REDIRECT_URL", "http://localhost:8501/?page=1_reset")
MAGIC_REDIRECT_URL: str  = os.environ.get("MAGIC_REDIRECT_URL", "http://localhost:8501/?page=2_magic")

# Clients
_sb: Client = create_client(SB_URL, SB_ANON)
_sb_admin: Optional[Client] = create_client(SB_URL, SB_SERVICE) if SB_SERVICE else None

# ---------- Sessions / User ----------
def sign_in_with_password(email: str, password: str):
    return _sb.auth.sign_in_with_password({"email": email, "password": password})

def sign_out():
    _sb.auth.sign_out()

def get_session():
    # laissé pour compatibilité
    return _sb.auth.get_session()

def get_user():
    return _sb.auth.get_user()

# ---------- Passwordless / Reset ----------
def send_magic_link(email: str):
    _sb.auth.sign_in_with_otp({
        "email": email,
        "options": {"email_redirect_to": MAGIC_REDIRECT_URL}
    })

def send_reset_email(email: str):
    _sb.auth.reset_password_for_email(email, {"redirect_to": RESET_REDIRECT_URL})

def update_current_password(new_password: str):
    # Si l'utilisateur est déjà en 'recovery session', cela fonctionne aussi
    _sb.auth.update_user({"password": new_password})

# ---------- Profiles (robustes aux 204 No Content) ----------
def upsert_profile(user_id: str, email: str, role: str, full_name: Optional[str] = None):
    """
    INSERT/UPDATE le profil via le client 'service role' et on force un .select()
    pour éviter les 204 No Content, courants avec PostgREST.
    """
    if _sb_admin is None:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY manquante (serveur)")

    # existe ?
    try:
        r = _sb_admin.table("profiles").select("id").eq("id", user_id).limit(1).execute()
        exists = bool(getattr(r, "data", None))
    except Exception:
        exists = False

    payload = {
        "id": user_id,
        "email": email,
        "role": role,
        "full_name": full_name or "",
    }

    try:
        if not exists:
            _sb_admin.table("profiles").insert(payload).select("*").execute()
        else:
            _sb_admin.table("profiles").update({
                "email": email,
                "role": role,
                "full_name": full_name or "",
            }).eq("id", user_id).select("*").execute()
    except Exception:
        # En dernier recours (ex: 204), on ignore l'exception
        pass

def get_profile(user_id: str) -> dict:
    """
    Lecture du profil. Utilise _sb_admin si dispo (bypass RLS).
    On évite maybe_single() et on fait un limit(1) + data[0].
    """
    client = _sb_admin or _sb
    try:
        res = client.table("profiles").select("*").eq("id", user_id).limit(1).execute()
        data = getattr(res, "data", None)
        return data[0] if data else {}
    except Exception:
        return {}

# ---------- Admin helper ----------
def invite_user(email: str):
    if _sb_admin is None:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY manquante (serveur)")
    try:
        return _sb_admin.auth.admin.invite_user_by_email(email)
    except Exception:
        return _sb_admin.auth.sign_up({"email": email, "password": os.urandom(9).hex()})

# ---------- Réinitialisation : vérif du token & changement de mot de passe ----------
def verify_recovery_token(token_hash: str):
    """
    Vérifie le lien de réinitialisation (token_hash) et crée une session temporaire 'recovery'
    pour cet utilisateur côté Supabase si succès.
    """
    return _sb.auth.verify_otp({"type": "recovery", "token_hash": token_hash})

def admin_set_password_for_user(user_id: str, new_password: str):
    """
    Change le mot de passe via l'API Admin (service role).
    À utiliser côté serveur uniquement (Streamlit = OK).
    """
    if not _sb_admin:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY manquante (serveur).")
    _sb_admin.auth.admin.update_user_by_id(user_id, {"password": new_password})
