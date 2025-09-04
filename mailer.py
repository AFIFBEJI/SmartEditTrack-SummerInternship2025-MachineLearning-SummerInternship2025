# mailer.py — Envoi d'emails (Resend OU SMTP, avec fallback SSL/TLS)
import os, re, smtplib, ssl, json
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr, make_msgid

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

def _smtp_try_send(msg: MIMEText, host: str, port: int, user: str, pwd: str, use_tls: bool, use_ssl: bool=False) -> bool:
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                s.login(user, pwd)
                s.send_message(msg)
        else:
            if use_tls:
                ctx = ssl.create_default_context()
                with smtplib.SMTP(host, port, timeout=20) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.ehlo()
                    s.login(user, pwd)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as s:
                    s.ehlo()
                    s.login(user, pwd)
                    s.send_message(msg)
        return True
    except Exception as e:
        print(f"[MAIL] SMTP send failed on {host}:{port} tls={use_tls} ssl={use_ssl} -> {e}")
        return False


def send_credentials_email(to_email: str, user_id: str, temp_pwd: str, login_url: str | None = None) -> bool:
    if not _valid_email(to_email):
        print("[MAIL] Invalid recipient email.")
        return False

    login_url = (login_url or _app_base_url()).strip()
    subject = "Vos accès à SmartEditTrack"
    html = _render_html(user_id, temp_pwd, login_url)

    # 1) Resend (optionnel)
    apikey = os.getenv("RESEND_API_KEY", "").strip()
    from_resend = os.getenv("RESEND_FROM", "").strip()
    if apikey and requests and from_resend:
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {apikey}", "Content-Type": "application/json"},
                data=json.dumps({"from": from_resend, "to": [to_email], "subject": subject, "html": html}),
                timeout=20,
            )
            if r.ok:
                return True
            print(f"[MAIL] Resend error: {r.status_code} {r.text}")
        except Exception as e:
            print(f"[MAIL] Resend exception: {e}")

    # 2) SMTP Mailtrap
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    pwd  = os.getenv("SMTP_PASS", "").strip()
    from_raw = os.getenv("SMTP_FROM", "").strip()
    try:
        port_cfg = int(os.getenv("SMTP_PORT", "465").strip() or "465")
    except Exception:
        port_cfg = 465

    if not host or not user or not pwd:
        print(f"[MAIL] Missing SMTP vars. host={bool(host)} user={bool(user)} pass={bool(pwd)}")
        return False

    name, addr = parseaddr(from_raw)
    if not _valid_email(addr):
        addr = "no-reply@smartedittrack.test"
    name = name or "SmartEditTrack"

    msg = MIMEText(html, "html", "utf-8")
    msg["From"] = formataddr((name, addr))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=addr.split("@")[-1])

    # Essais (dans cet ordre) :
    attempts = [
        (host, 465, False, True),           # SSL direct (recommandé)
        (host, 587, True,  False),          # STARTTLS standard
        (host, 2525, True, False),          # STARTTLS Mailtrap
        (host, port_cfg, False, False),     # port configuré sans TLS (secours)
    ]
    for h, p, tls, ssl_on in attempts:
        if _smtp_try_send(msg, h, p, user, pwd, tls, use_ssl=ssl_on):
            return True

    return False
