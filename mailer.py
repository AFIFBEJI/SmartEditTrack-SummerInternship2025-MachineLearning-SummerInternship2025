# mailer.py — Envoi d'emails (Resend OU SMTP)
# -------------------------------------------
# Priorité: RESEND_API_KEY (plus simple) sinon SMTP classique.
# Variables d'env acceptées :
#   RESEND_API_KEY, RESEND_FROM
#   SMTP_HOST, SMTP_PORT=587, SMTP_USER, SMTP_PASS, SMTP_TLS=true/false, SMTP_FROM
#   APP_BASE_URL (URL de ton app, ex: https://cloudstage.onrender.com)

import os, re, smtplib, ssl, json
from email.mime.text import MIMEText
from email.utils import formataddr

try:
    import requests
except Exception:
    requests = None

def _valid_email(addr: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (addr or "").strip(), re.I))

def _app_base_url() -> str:
    return os.getenv("APP_BASE_URL", "").strip() or "http://localhost:8501"

def _render_html(uid: str, pwd: str, login_url: str) -> str:
    return f"""
    <div style="font-family:Inter,system-ui,Segoe UI,Roboto,sans-serif;max-width:560px">
      <h2>Vos accès SmartEditTrack</h2>
      <p>Bonjour,</p>
      <p>Voici vos identifiants pour accéder à la plateforme :</p>
      <ul>
        <li><b>Identifiant</b> : <code>{uid}</code></li>
        <li><b>Mot de passe initial</b> : <code>{pwd}</code></li>
      </ul>
      <p>Connectez-vous ici : <a href="{login_url}">{login_url}</a></p>
      <p style="color:#475569;font-size:14px">Par sécurité, changez votre mot de passe après la première connexion.</p>
      <hr/>
      <p style="color:#94a3b8;font-size:12px">Email envoyé automatiquement – ne pas répondre.</p>
    </div>
    """

def send_credentials_email(to_email: str, user_id: str, temp_pwd: str, login_url: str = None) -> bool:
    """Envoie l'email. Retourne True si OK."""
    if not _valid_email(to_email):
        return False
    login_url = (login_url or _app_base_url()).strip()

    subject = "Vos accès à SmartEditTrack"
    html = _render_html(user_id, temp_pwd, login_url)

    # 1) RESEND (si dispo)
    apikey = os.getenv("RESEND_API_KEY", "").strip()
    from_addr = os.getenv("RESEND_FROM", "").strip()
    if apikey and requests and from_addr:
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {apikey}", "Content-Type": "application/json"},
                data=json.dumps({
                    "from": from_addr,        # ex: "SmartEditTrack <no-reply@tondomaine.tld>"
                    "to": [to_email],
                    "subject": subject,
                    "html": html
                }),
                timeout=20
            )
            return r.ok
        except Exception:
            pass

    # 2) SMTP fallback
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pwd  = os.getenv("SMTP_PASS", "")
    use_tls = os.getenv("SMTP_TLS", "true").lower() not in ("0","false","no")
    from_smtp = os.getenv("SMTP_FROM", f"SmartEditTrack <{user or 'no-reply@localhost'}>")

    if not host or not (user and pwd):
        return False

    msg = MIMEText(html, "html", "utf-8")
    # formataddr permet "Nom <mail@...>"
    if "<" in from_smtp and ">" in from_smtp:
        msg["From"] = from_smtp
    else:
        msg["From"] = formataddr(("SmartEditTrack", from_smtp))
    msg["To"] = to_email
    msg["Subject"] = subject

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=context)
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.login(user, pwd)
                s.send_message(msg)
        return True
    except Exception:
        return False
