# main.py
import streamlit as st
from auth import bootstrap_on_startup
bootstrap_on_startup()   # crée/MAJ la BD + l’admin depuis les variables d’env

from auth import (
    get_conn, ensure_schema,              # ⬅️ plus de ensure_session_schema ici
    auth_user, record_login,
    create_session, get_user_by_token, delete_session,
)

# ------------ BOOTSTRAP ------------
st.set_page_config(page_title="SmartEditTrack", page_icon="🧠", layout="wide")

# DB
conn = get_conn()
# Optionnel : get_conn() appelle déjà ensure_schema() en interne
ensure_schema(conn)

# ------------ SESSION HELPERS ------------
def _set_query_token(token: str | None):
    q = st.query_params
    if token:
        q["token"] = token
    elif "token" in q:
        del q["token"]

def restore_session_if_any():
    if "user" not in st.session_state:
        tok = st.query_params.get("token", None)
        if tok:
            u = get_user_by_token(conn, tok)
            if u:
                st.session_state["user"] = u

def logout():
    tok = st.query_params.get("token", None)
    delete_session(conn, tok)
    _set_query_token(None)
    st.session_state.pop("user", None)
    st.rerun()

# ------------ CSS (login uniquement) ------------
CSS = """
<style>
#MainMenu, header, footer{display:none!important;}
[data-testid="stSidebar"]{display:none!important;}

html,body,[class*="css"]{font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
body{
  background:
    linear-gradient(180deg,#CFEBFF 0%,#DDEAFF 26%,#E7E5FF 54%,#F6E0F0 78%,#F7F9FF 100%) fixed !important;
}
.block-container{
  min-height:100vh; padding:0 18px!important;
  display:flex; align-items:center; justify-content:center;
}

/* ======= KILL la pastille/bloc blanc du haut (sans toucher au titre) ======= */
.block-container > div[data-testid="stMarkdownContainer"]:not(:has(.login-head)):first-of-type{
  display:none!important;
}
/* au cas où il resterait un 2e bloc décoratif résiduel juste avant le titre */
.block-container > div[data-testid="stMarkdownContainer"]:not(:has(.login-head)):nth-of-type(2){
  display:none!important;
}

/* grille: formulaire à gauche, illustration à droite */
.wrap{ width:min(1080px,95vw); display:grid; grid-template-columns:1.2fr .8fr; gap:34px; }

/* titres */
.h-title{ font-weight:900; font-size:1.45rem; color:#0f172a; margin:2px 0 6px;}
.h-sub{ color:#334155; font-weight:600; margin:0 0 18px; }

/* champs */
.stTextInput>label{ color:#0f172a!important; font-weight:700; font-size:.9rem; margin-bottom:6px;}
.stTextInput>div>div>input{
  background:#0b1837!important; color:#fff!important;
  border:1px solid rgba(15,23,42,.35)!important; border-radius:12px!important;
  padding:.85rem 1rem!important;
}
.stTextInput>div>div>input::placeholder{ color:#c7d2fe!important; }

/* bouton compact centré */
.stButton{ display:flex; justify-content:flex-start; }
.stButton>button{
  width:220px;
  background:linear-gradient(90deg,#7C4DFF 0%, #3FA9F5 100%);
  color:#fff; font-weight:900; letter-spacing:.2px;
  border:0; border-radius:14px; padding:.78rem 1rem;
  box-shadow:0 14px 44px rgba(63,169,245,.28), 0 6px 12px rgba(124,77,255,.18);
  transition:transform .06s ease, box-shadow .15s ease, filter .15s ease;
}
.stButton>button:hover{
  transform:translateY(-1px);
  box-shadow:0 0 18px rgba(124,77,255,.32), 0 24px 60px rgba(63,169,245,.32);
  filter:saturate(1.05);
}

/* astuce */
.hint{ color:#334155; font-size:.9rem; margin-top:12px; }

/* illustration */
.illu-wrap{ display:flex; align-items:center; justify-content:center; }
.illu{ width:min(420px, 100%); height:auto; }

@media (max-width: 980px){
  .wrap{ grid-template-columns:1fr; gap:22px; }
  .stButton{ justify-content:center; }
}
</style>
"""

# Illustration SVG
SVG_ILLU = """
<svg class="illu" viewBox="0 0 640 520" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#7C4DFF"/><stop offset="1" stop-color="#3FA9F5"/>
    </linearGradient>
  </defs>
  <rect x="260" y="70" rx="26" width="260" height="380" fill="url(#g1)" opacity=".95"/>
  <rect x="282" y="122" rx="12" width="216" height="36" fill="#ffffff" opacity=".95"/>
  <rect x="282" y="168" rx="12" width="216" height="36" fill="#ffffff" opacity=".92"/>
  <rect x="282" y="214" rx="16" width="216" height="160" fill="#ffffff" opacity=".95"/>
  <circle cx="390" cy="278" r="44" fill="#E8EDFF"/>
  <circle cx="390" cy="260" r="16" fill="#7C4DFF"/>
  <path d="M360 300 C385 280 395 280 420 300" stroke="#3FA9F5" stroke-width="7" stroke-linecap="round"/>
  <circle cx="120" cy="172" r="46" fill="#E8EDFF"/>
  <circle cx="120" cy="158" r="14" fill="#7C4DFF"/>
  <path d="M92 190 C120 168 128 168 148 190" stroke="#3FA9F5" stroke-width="6" stroke-linecap="round"/>
  <circle cx="170" cy="310" r="46" fill="#E8EDFF"/>
  <circle cx="170" cy="296" r="14" fill="#3FA9F5"/>
  <path d="M142 328 C170 306 178 306 198 328" stroke="#7C4DFF" stroke-width="6" stroke-linecap="round"/>
</svg>
"""

# ------------ LOGIN VIEW ------------
def login_view():
    st.markdown(CSS, unsafe_allow_html=True)

    st.markdown('<div class="wrap">', unsafe_allow_html=True)
    left, right = st.columns([1.2, .8])

    with left:
        st.markdown(
            '<div class="login-head">'
            '<div class="h-title">SmartEditTrack — Connexion</div>'
            '<div class="h-sub">Entrez vos identifiants pour accéder à votre espace</div>'
            '</div>',
            unsafe_allow_html=True
        )

        user = st.text_input("Identifiant (ETUDxxx ou PROFxxx)", placeholder="ETUD010, PROF001 …")
        pwd  = st.text_input("Mot de passe", type="password", placeholder="Votre mot de passe")

        if st.button("Se connecter"):
            u = auth_user(conn, user.strip(), pwd.strip())
            if u:
                tok = create_session(conn, u["id"], ttl_hours=24)
                _set_query_token(tok)
                st.session_state["user"] = u
                record_login(conn, u["id"], ip="unknown", ua="streamlit")
                st.rerun()
            else:
                st.error("Identifiant ou mot de passe incorrect.", icon="🚫")

        st.markdown(
            '<div class="hint">💡 Identifiants fournis par l’enseignant. '
            'Les étudiants peuvent changer leur mot de passe après connexion.</div>',
            unsafe_allow_html=True
        )

    with right:
        st.markdown('<div class="illu-wrap">', unsafe_allow_html=True)
        st.markdown(SVG_ILLU, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)  # /wrap

# ------------ APP VIEW ------------
def app_view():
    # On enlève la mise en page "plein écran" du login
    st.markdown(
        "<style>.block-container{min-height:unset;display:block;padding:1.25rem 2rem!important;}</style>",
        unsafe_allow_html=True
    )
    u = st.session_state["user"]
    st.sidebar.success(f"{u['first_name']} {u['last_name']} — {u['id']} ({u['role']})")
    if st.sidebar.button("Se déconnecter", use_container_width=True):
        logout()

    if u["role"] == "admin":
        from app_prof import run as prof_run
        prof_run(u)
    else:
        from app_etudiant import run as etu_run
        etu_run(u)

# ------------ ROUTER ------------
def main():
    restore_session_if_any()
    if "user" not in st.session_state:
        login_view()
    else:
        app_view()

if __name__ == "__main__":
    main()
