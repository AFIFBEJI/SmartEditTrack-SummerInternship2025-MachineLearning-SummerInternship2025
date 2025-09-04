# main.py — SmartEditTrack (Admin/Prof via Supabase • Étudiants via ID local)
import os, re
import streamlit as st

# --- Config Streamlit le plus tôt possible (évite des glitchs de front) -----
st.set_page_config(page_title="SmartEditTrack", page_icon="🧠", layout="wide")

# --- Exposer st.secrets en variables d'env (utile sur Render) ---------------
# ✅ PATCH : on écrase toujours l'env avec les valeurs de secrets
try:
    for k, v in st.secrets.items():
        os.environ[k] = str(v)   # <-- au lieu de os.environ.setdefault(...)
except Exception:
    pass

from auth import (
    bootstrap_on_startup, get_conn, ensure_schema, record_login,
    auth_user, create_session, get_user_by_token, delete_session,
    login_is_locked, register_failed_login, reset_throttle,
)
from sb_auth import (
    sign_in_with_password, sign_out, get_user,
    send_reset_email, upsert_profile, get_profile,
    verify_recovery_token, update_current_password, admin_set_password_for_user,
)

# Helpers Supabase Storage et chemins locaux (app_prof)
from supa import list_prefix, download_to_file
from app_prof import _class_csv, _class_copies_dir

# ---------------------------------------------------------------------------
# Restauration /tmp depuis Supabase (utile sur Render Free où /tmp est éphémère)
# ---------------------------------------------------------------------------
def _slugify(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\-]+", "-", s).strip("-")
    return s or "classe"

def _restore_from_supabase():
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT DISTINCT class_name
            FROM users
            WHERE class_name IS NOT NULL AND class_name <> ''
        """).fetchall()
    except Exception:
        rows = []

    for (classname,) in rows:
        if not classname:
            continue
        slug = _slugify(classname)

        os.makedirs(os.path.dirname(_class_csv(slug)), exist_ok=True)
        os.makedirs(_class_copies_dir(slug), exist_ok=True)

        # CSV
        try:
            download_to_file(f"classes/{slug}/liste_etudiants.csv", _class_csv(slug))
        except Exception:
            pass

        # Copies .xlsm
        try:
            for it in (list_prefix(f"copies/{slug}") or []):
                if it.get("is_folder"):
                    continue
                remote = it.get("name") or ""
                if remote.lower().endswith(".xlsm"):
                    local = os.path.join(_class_copies_dir(slug), os.path.basename(remote))
                    if not os.path.exists(local):
                        download_to_file(remote, local)
        except Exception:
            pass

@st.cache_resource(show_spinner=False)
def restore_from_supabase_once():
    try:
        _restore_from_supabase()
    except Exception as e:
        # on loggue mais on ne bloque pas l'app
        print("restore_from_supabase skipped:", e)

# ---------------------------------------------------------------------------

bootstrap_on_startup()
conn = get_conn()
ensure_schema(conn)

# Lance la restauration une seule fois (désactivable via env)
if os.getenv("RESTORE_FROM_SUPABASE", "1") == "1":
    restore_from_supabase_once()

def _q(name: str):
    v = st.query_params.get(name, None)
    return (v[0] if isinstance(v, list) else v)

def reset_view():
    st.markdown("""
    <style>
      [data-testid="stSidebar"], [data-testid="stSidebarNav"] { display: none !important; }
      header, footer { display: none !important; }
      .block-container { padding-top: 2rem !important; }
    </style>
    """, unsafe_allow_html=True)
    st.title("Réinitialisation du mot de passe")

    if "token" not in st.query_params and "recovery_user_id" not in st.session_state:
        st.components.v1.html("""
        <script>
        (function(){
          const h = window.location.hash;
          if (h && h.length > 1) {
            const p = new URLSearchParams(h.substring(1));
            const t = p.get('token') || p.get('token_hash') || p.get('access_token');
            if (t) {
              const url = new URL(window.location.href);
              url.hash = '';
              url.searchParams.set('token', t);
              const em = p.get('email'); if (em) url.searchParams.set('email', em);
              window.location.replace(url.toString());
            }
          }
        })();
        </script>
        """, height=0)

    if "recovery_user_id" not in st.session_state:
        token = _q("token")
        if not token:
            st.error("Lien invalide ou incomplet. Ouvre le lien « Reset Password » reçu par email.")
            st.stop()
        with st.spinner("Vérification du lien…"):
            try:
                res = verify_recovery_token(token)
            except Exception as e:
                st.error(f"Le lien n’est plus valide ou a déjà été utilisé. Détail : {e}")
                st.stop()

        user_obj = getattr(res, "user", None) or getattr(res, "data", None) or {}
        user_id = getattr(user_obj, "id", None) if hasattr(user_obj, "id") else (
            user_obj.get("id") if isinstance(user_obj, dict) else None
        )
        if not user_id:
            st.error("Impossible d’identifier l’utilisateur. Redemande un email de réinitialisation.")
            st.stop()
        st.session_state["recovery_user_id"] = user_id

    st.success("Lien validé ✅. Choisis un nouveau mot de passe.")
    pwd1 = st.text_input("Nouveau mot de passe", type="password", key="reset_pwd1")
    pwd2 = st.text_input("Confirme le mot de passe", type="password", key="reset_pwd2")

    if st.button("Mettre à jour le mot de passe", type="primary", key="btn_reset_update"):
        if not pwd1 or len(pwd1) < 8:
            st.error("Le mot de passe doit contenir au moins 8 caractères."); return
        if pwd1 != pwd2:
            st.error("Les deux mots de passe ne correspondent pas."); return

        user_id = st.session_state.get("recovery_user_id")
        ok = False
        try:
            update_current_password(pwd1); ok = True
        except Exception:
            ok = False
        if not ok:
            try:
                admin_set_password_for_user(user_id, pwd1); ok = True
            except Exception as e:
                st.error(f"Erreur pendant la mise à jour : {e}"); ok = False
        if ok:
            st.session_state.pop("recovery_user_id", None)
            st.success("Mot de passe mis à jour 🎉. Tu peux maintenant te connecter.")
            st.write("[↩ Revenir à l’écran de connexion](/)")

LOGIN_CSS = """
<style>
#MainMenu, header, footer{display:none!important;}
[data-testid="stSidebar"]{display:none!important;}
html,body,[class*="css"]{font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
.block-container{min-height:100vh; padding:0 18px!important; display:flex; align-items:center; justify-content:center;}
.wrap{ width:min(1080px,95vw); display:grid; grid-template-columns:1.2fr .8fr; gap:34px; }
.h-title{ font-weight:900; font-size:1.45rem; color:#0f172a; margin:2px 0 6px;}
.h-sub{ color:#334155; font-weight:600; margin:0 0 18px; }
.stTextInput>label{ color:#0f172a!important; font-weight:700; font-size:.9rem; margin-bottom:6px;}
.stTextInput>div>div>input{ background:#0b1837!important; color:#fff!important; border:1px solid rgba(15,23,42,.35)!important; border-radius:12px!important; padding:.85rem 1rem!important;}
.stTextInput>div>div>input::placeholder{ color:#c7d2fe!important; }
.stButton{ display:flex; justify-content:flex-start; }
.stButton>button{ width:260px; background:linear-gradient(90deg,#7C4DFF 0%, #3FA9F5 100%);
  color:#fff; font-weight:900; letter-spacing:.2px; border:0; border-radius:14px; padding:.78rem 1rem;}
</style>
"""

SVG_ILLU = """
<svg class="illu" viewBox="0 0 640 520" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#7C4DFF"/><stop offset="1" stop-color="#3FA9F5"/>
  </linearGradient></defs>
  <rect x="260" y="70" rx="26" width="260" height="380" fill="url(#g1)" opacity=".95"/>
  <rect x="282" y="122" rx="12" width="216" height="36" fill="#ffffff" opacity=".95"/>
  <rect x="282" y="168" rx="12" width="216" height="36" fill="#ffffff" opacity=".92"/>
  <rect x="282" y="214" rx="16" width="216" height="160" fill="#ffffff" opacity=".95"/>
  <circle cx="390" cy="278" r="44" fill="#E8EDFF"/>
  <circle cx="390" cy="260" r="16" fill="#7C4DFF"/>
  <path d="M360 300 C385 280 395 280 420 300" stroke="#3FA9F5" stroke-width="7" stroke-linecap="round"/>
</svg>
"""

def login_view():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    st.markdown('<div class="wrap">', unsafe_allow_html=True)
    left, right = st.columns([1.2, .8])

    with left:
        st.markdown(
            '<div class="login-head">'
            '<div class="h-title">SmartEditTrack — Connexion</div>'
            '<div class="h-sub">Choisissez votre méthode de connexion</div>'
            '</div>', unsafe_allow_html=True
        )

        tabs = st.tabs(["Admin/Prof (email + mot de passe)", "Étudiant (ID + mot de passe)"])

        # --- Admin/Prof ---
        with tabs[0]:
            email = st.text_input("Email (admin/prof)", key="adm_email")
            password = st.text_input("Mot de passe", type="password", key="adm_pwd")

            if st.button("Se connecter (Admin/Prof)", key="btn_login_admin"):
                email_norm = (email or "").strip().lower()
                ip = "unknown"

                locked, wait_s = login_is_locked(conn, email_norm, ip)
                if locked:
                    m, s = divmod(wait_s, 60)
                    st.error(f"Trop d’essais. Compte verrouillé encore {m} min {s:02d} s.")
                    st.stop()

                try:
                    res = sign_in_with_password(email_norm, (password or "").strip())
                    ok = bool(getattr(res, "user", None))
                except Exception:
                    ok = False

                if not ok:
                    locked_now, wait_s, remaining = register_failed_login(conn, email_norm, ip)
                    if locked_now:
                        m, s = divmod(wait_s, 60)
                        st.error(f"Identifiants invalides. Compte verrouillé {m} min {s:02d} s.")
                    else:
                        st.error(f"Identifiants invalides. Tentatives restantes : {remaining}.")
                else:
                    reset_throttle(conn, email_norm, ip)
                    try:
                        su = get_user()
                        u = getattr(su, "user", None)
                    except Exception:
                        u = None

                    if not u:
                        st.error("Session non trouvée après login.")
                    else:
                        prof = get_profile(u.id)
                        if not prof:
                            default_role = "prof"
                            admins = [e.strip().lower() for e in os.environ.get("ADMIN_EMAILS","").split(",") if e.strip()]
                            if u.email and u.email.lower() in admins:
                                default_role = "admin"
                            upsert_profile(
                                u.id, u.email, default_role,
                                (getattr(u, "user_metadata", {}) or {}).get("full_name", None)
                            )
                        try:
                            record_login(conn, u.id, ip=ip, ua="streamlit-supabase")
                        except Exception:
                            pass
                        st.session_state["supabase_user"] = {"id": u.id, "email": u.email}
                        st.success("Connexion réussie.")
                        st.rerun()

            with st.expander("Mot de passe oublié ?"):
                reset_email = st.text_input("Votre email", key="adm_reset_email")
                if st.button("Envoyer le lien de réinitialisation", key="btn_send_reset"):
                    try:
                        send_reset_email((reset_email or "").strip().lower())
                        st.info("Si le compte existe, un email a été envoyé.")
                    except Exception as e:
                        st.error(f"Erreur: {e}")

        # --- Étudiant ---
        with tabs[1]:
            sid = st.text_input("Identifiant (ex. ETUD001)", key="stu_id")
            spw = st.text_input("Mot de passe", type="password", key="stu_pwd")

            if st.button("Se connecter (Étudiant)", key="btn_login_student"):
                sid = (sid or "").strip()
                ip = "unknown"

                locked, wait_s = login_is_locked(conn, sid, ip)
                if locked:
                    m, s = divmod(wait_s, 60)
                    st.error(f"Trop d'essais. Compte verrouillé encore {m} min {s:02d} s.")
                    st.stop()

                user = auth_user(conn, sid, spw)
                if not user:
                    locked_now, wait_s, remaining = register_failed_login(conn, sid, ip)
                    if locked_now:
                        m, s = divmod(wait_s, 60)
                        st.error(f"Identifiant ou mot de passe invalide. Compte verrouillé {m} min {s:02d} s.")
                    else:
                        st.error(f"Identifiant ou mot de passe invalide. Tentatives restantes : {remaining}.")
                else:
                    reset_throttle(conn, sid, ip)
                    tok = create_session(conn, user["id"])
                    st.session_state["local_token"] = tok
                    st.session_state["local_user"] = user
                    try:
                        record_login(conn, user["id"], ip=ip, ua="streamlit-local")
                    except Exception:
                        pass
                    st.success("Connexion réussie.")
                    st.rerun()

    with right:
        st.markdown(SVG_ILLU, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

def app_view():
    st.markdown("""<style>[data-testid="stSidebarNav"]{ display:none !important; }</style>""",
                unsafe_allow_html=True)

    try:
        su = get_user()
        sb_user = getattr(su, "user", None)
    except Exception:
        sb_user = None

    local_tok = st.session_state.get("local_token")
    local_user = get_user_by_token(conn, local_tok) if local_tok else None

    if sb_user:
        prof = get_profile(sb_user.id) or {}
        role = prof.get("role", "student")
        st.sidebar.success(f"{sb_user.email} — ({role})")
        if st.sidebar.button("Se déconnecter (Admin/Prof)", use_container_width=True, key="btn_logout_admin"):
            try: sign_out()
            except Exception: pass
            st.session_state.pop("supabase_user", None)
            st.rerun()

        if role in ("admin", "prof"):
            from app_prof import run as prof_run
            prof_run({"id": sb_user.id, "role": role}); return
        else:
            st.warning("Profil non reconnu — rôle par défaut étudiant.")
            from app_etudiant import run as etu_run
            etu_run({"id": sb_user.id, "role": "student"}); return

    if local_user:
        st.sidebar.success(f"{local_user['id']} — (étudiant)")
        if st.sidebar.button("Se déconnecter (Étudiant)", use_container_width=True, key="btn_logout_student"):
            try: delete_session(conn, local_tok)
            finally:
                st.session_state.pop("local_token", None)
                st.session_state.pop("local_user", None)
                st.rerun()
        from app_etudiant import run as etu_run
        etu_run(local_user); return

    login_view()

def main():
    p = (_q("page") or "").lower()
    token_present = any(_q(k) for k in ("token", "token_hash", "access_token"))
    if p == "reset" or token_present:
        reset_view(); return
    app_view()

if __name__ == "__main__":
    main()
