# pages/reset.py
import streamlit as st
from sb_auth import (
    verify_recovery_token,
    update_current_password,        # 1er essai (session "recovery")
    admin_set_password_for_user,    # secours via service role
)

st.set_page_config(
    page_title="Réinitialiser le mot de passe",
    initial_sidebar_state="collapsed",
)

# 🔒 Masquer totalement la sidebar et la nav multipage sur CETTE page
st.markdown("""
<style>
  [data-testid="stSidebar"], [data-testid="stSidebarNav"] { display:none !important; }
  header, footer { display:none !important; }
  .block-container { padding-top: 2.0rem !important; }
</style>
""", unsafe_allow_html=True)

st.title("Réinitialisation du mot de passe")

# --- 0) Si un ancien mail met le token dans le hash (#...), on le remonte en ?token=...
if "token" not in st.query_params and "recovery_user_id" not in st.session_state:
    st.components.v1.html("""
    <script>
      (function () {
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

# --- 1) Vérifier le token **UNE SEULE FOIS** puis mémoriser l'user_id
if "recovery_user_id" not in st.session_state:
    token = st.query_params.get("token", None)
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
    if hasattr(user_obj, "id"):
        user_id = getattr(user_obj, "id", None)
    else:
        user_id = user_obj.get("id") if isinstance(user_obj, dict) else None

    if not user_id:
        st.error("Impossible d’identifier l’utilisateur. Redemande un email de réinitialisation.")
        st.stop()

    # ✅ mémoriser pour les relances Streamlit
    st.session_state["recovery_user_id"] = user_id

# --- 2) Formulaire (sans re-vérifier le token)
st.success("Lien validé ✅. Choisis un nouveau mot de passe.")
pwd1 = st.text_input("Nouveau mot de passe", type="password")
pwd2 = st.text_input("Confirme le mot de passe", type="password")

if st.button("Mettre à jour le mot de passe", type="primary"):
    if not pwd1 or len(pwd1) < 8:
        st.error("Le mot de passe doit contenir au moins 8 caractères.")
    elif pwd1 != pwd2:
        st.error("Les deux mots de passe ne correspondent pas.")
    else:
        uid = st.session_state.get("recovery_user_id")

        ok = False
        # 1️⃣ essaie via la session "recovery" (update_user)
        try:
            update_current_password(pwd1)
            ok = True
        except Exception:
            ok = False

        # 2️⃣ si jamais la session "recovery" n'est pas active côté SDK, on force via service role
        if not ok and uid:
            try:
                admin_set_password_for_user(uid, pwd1)
                ok = True
            except Exception as e:
                st.error(f"Erreur pendant la mise à jour : {e}")
                ok = False

        if ok:
            st.session_state.pop("recovery_user_id", None)
            st.success("Mot de passe mis à jour 🎉. Tu peux maintenant te connecter.")
            st.write("[↩ Revenir à l’écran de connexion](/)")
