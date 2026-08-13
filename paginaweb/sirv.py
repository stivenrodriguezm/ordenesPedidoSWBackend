"""Cliente mínimo para la REST API de Sirv (https://api.sirv.com) — usado para
subir imágenes de Gestión Web (productos, fotos de asesores) al CDN de Sirv
en vez de guardarlas en disco local."""
import time

import requests
from django.conf import settings

SIRV_API_BASE = "https://api.sirv.com/v2"

# Cache del token en memoria del proceso — Sirv los emite con ~20 min de vida.
_token_cache = {"token": None, "expires_at": 0}


class SirvUploadError(Exception):
    pass


def _get_sirv_token():
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    if not settings.SIRV_CLIENT_ID or not settings.SIRV_CLIENT_SECRET:
        raise SirvUploadError("SIRV_CLIENT_ID / SIRV_CLIENT_SECRET no están configurados.")

    try:
        resp = requests.post(
            f"{SIRV_API_BASE}/token",
            json={"clientId": settings.SIRV_CLIENT_ID, "clientSecret": settings.SIRV_CLIENT_SECRET},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        raise SirvUploadError(f"No se pudo conectar con Sirv para autenticar: {e}")
    if not resp.ok:
        raise SirvUploadError(f"No se pudo autenticar con Sirv ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    _token_cache["token"] = data["token"]
    # Margen de seguridad de 60s antes de que expire de verdad.
    _token_cache["expires_at"] = now + data.get("expiresIn", 1200) - 60
    return _token_cache["token"]


def upload_to_sirv(file_bytes, filename, content_type=None):
    """Sube un archivo a Sirv y devuelve su URL pública en lottus.sirv.com.

    filename: ruta destino dentro del "filesystem" de Sirv, ej. 'paginaweb/foo.jpg'.
    """
    token = _get_sirv_token()
    path = "/" + filename.lstrip("/")

    try:
        resp = requests.post(
            f"{SIRV_API_BASE}/files/upload",
            params={"filename": path},
            data=file_bytes,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type or "application/octet-stream",
            },
            # Fotos en alta resolución pueden pesar varias decenas de MB — con
            # una conexión lenta la subida a Sirv puede tardar más que unos
            # pocos segundos, así que este timeout es generoso a propósito.
            timeout=90,
        )
    except requests.exceptions.RequestException as e:
        raise SirvUploadError(f"No se pudo conectar con Sirv para subir el archivo: {e}")
    if not resp.ok:
        raise SirvUploadError(f"Sirv rechazó la subida ({resp.status_code}): {resp.text[:200]}")

    return f"https://{settings.SIRV_PUBLIC_DOMAIN}{path}"
