# supa.py — helpers Storage (Supabase Python v2)
# ------------------------------------------------
# Fonctions utilitaires pour Supabase Storage :
# - get_client() : client unique (service role)
# - upload_file() / upload_bytes() : envoi (upsert)
# - download_to_file() : téléchargement
# - signed_url() : URL signée
# - delete_prefix() : suppression récursive d'un "dossier" (prefix)

from __future__ import annotations

import os
import mimetypes
from typing import List
from supabase import create_client, Client

# --------------------------------------------------------------------
# Configuration depuis les variables d'environnement
# --------------------------------------------------------------------
_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
# On privilégie la SERVICE_ROLE pour pouvoir supprimer en masse
_SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_ANON_KEY", "")
)
_BUCKET = os.environ.get("SUPABASE_BUCKET", "smartedittrack")

_client: Client | None = None


def get_client() -> Client:
    """Retourne un client Supabase unique (lazy)."""
    global _client
    if _client is None:
        if not _SUPABASE_URL or not _SUPABASE_KEY:
            raise RuntimeError("Supabase credentials missing (URL / KEY).")
        _client = create_client(_SUPABASE_URL, _SUPABASE_KEY)
    return _client


# --------------------------------------------------------------------
# Upload / Download
# --------------------------------------------------------------------
def upload_file(local_path: str, remote_path: str, content_type: str | None = None) -> str:
    """
    Envoie un fichier local vers Storage, en *upsert*.
    storage3 attend des headers string et le header 'x-upsert'.
    """
    ct = content_type or mimetypes.guess_type(local_path)[0] or "application/octet-stream"
    with open(local_path, "rb") as f:
        get_client().storage.from_(_BUCKET).upload(
            remote_path,
            f,
            {
                "content-type": ct,
                "x-upsert": "true",  # <= OBLIGATOIRE en string
            },
        )
    return remote_path


def upload_bytes(data: bytes, remote_path: str, content_type: str = "application/octet-stream") -> str:
    """Envoie un contenu mémoire vers Storage (upsert)."""
    get_client().storage.from_(_BUCKET).upload(
        remote_path,
        data,
        {
            "content-type": content_type,
            "x-upsert": "true",
        },
    )
    return remote_path


def download_to_file(remote_path: str, local_path: str) -> bool:
    """Télécharge un objet Storage vers un chemin local."""
    try:
        data = get_client().storage.from_(_BUCKET).download(remote_path)
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def signed_url(remote_path: str, expires_in: int = 7 * 24 * 3600) -> str:
    """Génère une URL signée (par défaut 7 jours)."""
    resp = get_client().storage.from_(_BUCKET).create_signed_url(remote_path, expires_in)
    # suivant la version, la clé peut s'appeler signed_url ou signedURL
    return resp.get("signed_url") or resp.get("signedURL") or ""


# --------------------------------------------------------------------
# Suppression récursive d'un "dossier" (prefix)
# --------------------------------------------------------------------
def _list_recursive(prefix: str) -> List[str]:
    """
    Liste *récursivement* tous les objets (fichiers) sous `prefix/`.
    Retourne des chemins relatifs au bucket.
    """
    store = get_client().storage.from_(_BUCKET)

    # normaliser le préfixe
    p = prefix.lstrip("/")
    if p and not p.endswith("/"):
        p += "/"

    files: List[str] = []
    stack: List[str] = [p]  # chemins "dossiers" à parcourir

    while stack:
        path = stack.pop()
        # list() retourne à la fois fichiers et "dossiers"
        items = store.list(path=path, limit=1000) or []
        for it in items:
            name = it.get("name") or ""
            full = f"{path}{name}" if path.endswith("/") else f"{path}/{name}"

            # Heuristique : si 'id' est None et pas de 'metadata', c'est un "dossier"
            is_folder = (it.get("id") is None) and (not it.get("metadata"))
            if is_folder:
                if not full.endswith("/"):
                    full += "/"
                stack.append(full)
            else:
                # C'est un fichier
                files.append(full)

    return files


def delete_prefix(prefix: str) -> bool:
    """
    Supprime récursivement tous les objets dont le chemin commence par `prefix`.
    Exemple : delete_prefix("copies/3a61/") -> True si au moins un objet supprimé.
    """
    store = get_client().storage.from_(_BUCKET)
    to_remove = _list_recursive(prefix)
    if not to_remove:
        return False
    # L'API accepte la suppression en lot
    store.remove(to_remove)
    return True
