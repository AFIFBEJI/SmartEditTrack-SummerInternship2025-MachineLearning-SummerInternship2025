# mailer.py — Envoi d'emails (Resend OU SMTP, avec fallback 587 -> 2525)
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

def _smtp_try_send(msg: MIMEText, host: str, port: int, user: str, pwd: str, use_tls: bool) -> bool:
    try:
        if use_tls:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.login(user, pwd)
                s.send_message(msg)
        return True
    except Exception as e:
        # log non bloquant pour Render logs
        print(f"[MAIL] SMTP send failed on {host}:{port} tls={use_tls} -> {e}")
        return False

def send_credentials_email(to_email: str, user_id: str, temp_pwd: str, login_url: str = None) -> bool:
    """Envoie l'email. Retourne True si OK (Resend ou SMTP)."""
    if not _valid_email(to_email):
        return False
    login_url = (login_url or _app_base_url()).strip()

    subject = "Vos accès à SmartEditTrack"
    html = _render_html(user_id, temp_pwd, login_url)

    # 1) RESEND si dispo (optionnel)
    apikey = os.getenv("RESEND_API_KEY", "").strip()
    from_resend = os.getenv("RESEND_FROM", "").strip()
    if apikey and requests and from_resend:
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {apikey}", "Content-Type": "application/json"},
                data=json.dumps({"from": from_resend, "to": [to_email], "subject": subject, "html": html}),
                timeout=20
            )
            if r.ok:
                return True
            print(f"[MAIL] Resend error: {r.status_code} {r.text}")
        except Exception as e:
            print(f"[MAIL] Resend exception: {e}")

    # 2) SMTP (Mailtrap Sandbox)
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    pwd  = os.getenv("SMTP_PASS", "").strip()
    use_tls = os.getenv("SMTP_TLS", "true").lower() not in ("0","false","no")
    from_smtp = os.getenv("SMTP_FROM", f"SmartEditTrack <{user or 'no-reply@localhost'}>").strip()

    if not host or not user or not pwd:
        print("[MAIL] Missing SMTP vars.")
        return False

    msg = MIMEText(html, "html", "utf-8")
    if "<" in from_smtp and ">" in from_smtp:
        msg["From"] = from_smtp
    else:
        msg["From"] = formataddr(("SmartEditTrack", from_smtp))
    msg["To"] = to_email
    msg["Subject"] = subject

    # ordre d’essai : port configuré puis 2525, avec TLS identique
    if _smtp_try_send(msg, host, port, user, pwd, use_tls):
        return True
    # Fallback classique Mailtrap
    if port != 2525 and _smtp_try_send(msg, host, 2525, user, pwd, True):
        return True
    # Dernier essai sans TLS (rarement utile)
    if _smtp_try_send(msg, host, port, user, pwd, False):
        return True

    return False
