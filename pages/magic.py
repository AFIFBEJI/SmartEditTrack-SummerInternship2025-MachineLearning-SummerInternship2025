import streamlit as st
from sb_auth import get_user

st.set_page_config(page_title="Connexion (Magic Link)")

st.title("Connexion par lien magique")
su = get_user()
if su and getattr(su, "user", None):
    st.success("Connexion réussie via le lien magique. Retour à l’accueil…")
    st.experimental_set_query_params()  # nettoie l'URL
    st.experimental_rerun()
else:
    st.info("En attente de session… Si rien ne se passe, réessayez depuis l’email.")
