# supa.py — helpers Storage (Supabase Python v2)
import os, mimetypes
from supabase import create_client, Client

_client: Client | None = None

def _get() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"].rstrip("/")
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]  # service_role (secret)
        _client = create_client(url, key)
    return _client

def upload_file(local_path: str, remote_path: str, content_type: str | None = None):
    """
    Envoie un fichier sur Storage (upsert=True).
    ⚠️ storage3 attend des headers string et le header 'x-upsert'.
    """
    bucket = os.environ.get("SUPABASE_BUCKET", "smartedittrack")
    ct = content_type or mimetypes.guess_type(local_path)[0] or "application/octet-stream"
    with open(local_path, "rb") as f:
        _get().storage.from_(bucket).upload(
            remote_path,
            f,
            {  # headers attendus par storage3
                "content-type": ct,
                "x-upsert": "true",   # <- string, pas bool
            },
        )

def upload_bytes(data: bytes, remote_path: str, content_type: str = "application/octet-stream"):
    bucket = os.environ.get("SUPABASE_BUCKET", "smartedittrack")
    _get().storage.from_(bucket).upload(
        remote_path,
        data,
        {
            "content-type": content_type,
            "x-upsert": "true",   # <- string, pas bool
        },
    )

def download_to_file(remote_path: str, local_path: str) -> bool:
    """Télécharge un objet Storage vers un chemin local."""
    bucket = os.environ.get("SUPABASE_BUCKET", "smartedittrack")
    try:
        data = _get().storage.from_(bucket).download(remote_path)
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False

def signed_url(remote_path: str, expires_in: int = 7 * 24 * 3600) -> str:
    """URL signée (par défaut 7 jours)."""
    bucket = os.environ.get("SUPABASE_BUCKET", "smartedittrack")
    resp = _get().storage.from_(bucket).create_signed_url(remote_path, expires_in)
    return resp.get("signed_url") or resp.get("signedURL") or ""
