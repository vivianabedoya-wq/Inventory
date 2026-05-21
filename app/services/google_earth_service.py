# app/services/supabase_io.py
from __future__ import annotations
from typing import Optional
from supabase import create_client

# ----- Client -----
def make_supabase(url: str, key: str):
    """Return a configured Supabase client."""
    return create_client(url, key)

# ----- Storage (bucket) -----
def storage_download_bytes(client, bucket: str, key: str) -> Optional[bytes]:
    """
    Download object from Storage. Returns bytes or None if not found.
    """
    resp = client.storage.from_(bucket).download(key)
    if isinstance(resp, dict) and resp.get("error"):
        return None
    return resp  # bytes

def storage_upload_bytes(client, bucket: str, key: str, data: bytes, upsert: bool = True) -> None:
    """
    Upload object to Storage. Some versions of storage3 require header values as str.
    """
    file_options = {
        # storage3 maps this to the x-upsert header; must be "true"/"false" (string), not bool
        "upsert": "true" if upsert else "false",
        # set explicit content-type for xlsx
        "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        # optional: cache control if you want
        # "cacheControl": "3600",
        # optional: metadata must be str values if you add it
        # "metadata": {"source": "google-earth-control"}
    }
    client.storage.from_(bucket).upload(key, data, file_options)


def storage_remove_object(client, bucket: str, key: str) -> None:
    client.storage.from_(bucket).remove([key])

def storage_signed_url(client, bucket: str, key: str, expires_sec: int = 900) -> str:
    out = client.storage.from_(bucket).create_signed_url(key, expires_sec)
    return out.get("signedURL", "")
