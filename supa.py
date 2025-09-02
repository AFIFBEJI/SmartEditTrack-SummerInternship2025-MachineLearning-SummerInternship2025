# supa.py
import os
from supabase import create_client, Client

_URL   = os.environ.get("SUPABASE_URL", "").strip()
# en prod serveur on utilise la service_role (sinon anon à défaut)
_KEY   = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
_BUCKET = os.environ.get("SUPABASE_BUCKET", "smartedittrack")

_sb: Client | None = None

def sb() -> Client:
    global _sb
    if _sb is None:
        if not _URL or not _KEY:
            raise RuntimeError("Supabase: variables d'env manquantes")
        _sb = create_client(_URL, _KEY)
    return _sb

def upload_file(local_path: str, remote_path: str) -> None:
    """Upload avec upsert (remplace si existe)."""
    with open(local_path, "rb") as f:
        sb().storage.from_(_BUCKET).upload(remote_path, f, {"upsert": True})

def signed_url(remote_path: str, seconds: int = 3600) -> str:
    """URL signée temporaire pour consulter/télécharger."""
    res = sb().storage.from_(_BUCKET).create_signed_url(remote_path, seconds)
    # la clé s'appelle 'signed_url' dans supabase-py v2
    return res.get("signed_url") or res.get("signedURL") or ""
