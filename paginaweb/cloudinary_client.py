"""Cliente mínimo para la API de subida de Cloudinary (https://cloudinary.com)
— usado por Gestión Web para subir imágenes y videos de productos/asesores.

A diferencia de Sirv (que sirve el archivo tal cual se subió), Cloudinary
optimiza automáticamente formato y calidad en la URL de entrega (f_auto,
q_auto): sirve WebP/AVIF a los navegadores que lo soportan y recodifica el
video a un bitrate razonable, sin que nosotros tengamos que convertir nada
antes de subir.
"""
import hashlib
import time

import requests
from django.conf import settings

CLOUDINARY_API_BASE = "https://api.cloudinary.com/v1_1"


class CloudinaryUploadError(Exception):
    pass


def _sign(params, api_secret):
    # Cloudinary firma concatenando los parámetros (menos file/api_key/
    # cloud_name/resource_type) ordenados alfabéticamente como query string,
    # seguido del api_secret sin separador, y hasheando todo con SHA-1.
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1((to_sign + api_secret).encode("utf-8")).hexdigest()


def _insert_transformation(secure_url, transformation):
    # secure_url luce como .../<resource_type>/upload/v169.../folder/id.ext —
    # insertamos la transformación justo después de "/upload/".
    marker = "/upload/"
    idx = secure_url.find(marker)
    if idx == -1:
        return secure_url
    cut = idx + len(marker)
    return f"{secure_url[:cut]}{transformation}/{secure_url[cut:]}"


def upload_to_cloudinary(file_bytes, filename, content_type=None):
    """Sube un archivo (imagen o video) a Cloudinary y devuelve su URL pública
    de entrega, ya con f_auto,q_auto aplicado para que cada visitante reciba
    el formato/calidad más liviano que su navegador soporte.

    filename: ruta lógica del archivo, ej. 'paginaweb/20260902_..._abc123.jpg'
    (se usa como public_id dentro de una carpeta 'paginaweb' en Cloudinary).
    """
    if not settings.CLOUDINARY_CLOUD_NAME or not settings.CLOUDINARY_API_KEY or not settings.CLOUDINARY_API_SECRET:
        raise CloudinaryUploadError("CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET no están configurados.")

    path = filename.lstrip("/")
    folder, _, base = path.rpartition("/")
    public_id_base = base.rsplit(".", 1)[0] if "." in base else base
    public_id = f"{folder}/{public_id_base}" if folder else public_id_base

    timestamp = int(time.time())
    params_to_sign = {"timestamp": timestamp, "public_id": public_id}
    signature = _sign(params_to_sign, settings.CLOUDINARY_API_SECRET)

    data = {
        "timestamp": timestamp,
        "public_id": public_id,
        "api_key": settings.CLOUDINARY_API_KEY,
        "signature": signature,
    }
    files = {"file": (base, file_bytes, content_type or "application/octet-stream")}

    try:
        resp = requests.post(
            f"{CLOUDINARY_API_BASE}/{settings.CLOUDINARY_CLOUD_NAME}/auto/upload",
            data=data,
            files=files,
            # Fotos en alta resolución y videos (hasta 100 MB) con conexión
            # lenta pueden tardar bastante más que unos pocos segundos.
            timeout=180,
        )
    except requests.exceptions.RequestException as e:
        raise CloudinaryUploadError(f"No se pudo conectar con Cloudinary para subir el archivo: {e}")
    if not resp.ok:
        raise CloudinaryUploadError(f"Cloudinary rechazó la subida ({resp.status_code}): {resp.text[:300]}")

    body = resp.json()
    secure_url = body.get("secure_url")
    if not secure_url:
        raise CloudinaryUploadError(f"Respuesta inesperada de Cloudinary: {resp.text[:300]}")

    return _insert_transformation(secure_url, "f_auto,q_auto")
