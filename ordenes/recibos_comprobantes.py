"""Recibos de caja (2026-10-28): número automático y fotos de los comprobantes de pago.

- Número automático: serie propia desde 10100, de uno en uno, bajo bloqueo de su contador
  (ConsecutivoDocumento 'recibo_caja_automatico'). Si un número ya se usó a mano, se salta.
  Los recibos manuales siguen con el número que escribe el usuario.
- Fotos: el cliente envía pantallazos o fotos del pago. El navegador ya las reduce antes de
  subirlas; aquí se vuelven a comprimir siempre (JPEG, lado mayor 2000 px) para que ninguna
  foto se rechace por tamaño, y se guardan en Cloudinary (carpeta recibos_caja/).
"""
import io
import uuid

from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageOps

from .models import ConsecutivoDocumento, ReciboCaja
from .servicios import siguiente_consecutivo

SERIE_AUTOMATICA = 'recibo_caja_automatico'
PRIMER_NUMERO_AUTOMATICO = 10100
MAX_BYTES_ORIGINAL = 40 * 1024 * 1024  # el navegador ya comprime; esto solo frena abusos
LADO_MAXIMO = 2000
MAX_BYTES_FINAL = 1_500_000
MAX_FOTOS = 10


class ComprobanteInvalido(Exception):
    pass


def siguiente_numero_automatico():
    """Toma el siguiente número de la serie automática (llamar dentro de una transacción)."""
    while True:
        numero = siguiente_consecutivo(SERIE_AUTOMATICA, PRIMER_NUMERO_AUTOMATICO)
        if not ReciboCaja.objects.filter(pk=numero).exists():
            return numero


def proximo_numero_automatico():
    """Vista previa del número que tomaría el próximo recibo automático (no lo reserva)."""
    contador = ConsecutivoDocumento.objects.filter(serie=SERIE_AUTOMATICA).first()
    numero = max((contador.ultimo + 1) if contador else 0, PRIMER_NUMERO_AUTOMATICO)
    while ReciboCaja.objects.filter(pk=numero).exists():
        numero += 1
    return numero


def comprimir_comprobante(datos):
    """Devuelve los bytes JPEG de la foto, girada según su EXIF, con el lado mayor de
    hasta 2000 px y bajo ~1,5 MB. Lanza ComprobanteInvalido si no es una imagen."""
    try:
        with Image.open(io.BytesIO(datos)) as img:
            img.verify()
        img = Image.open(io.BytesIO(datos))
        img.load()
    except Exception:
        raise ComprobanteInvalido('El archivo no es una imagen válida (usa JPG, PNG o WEBP).')
    img = ImageOps.exif_transpose(img)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        fondo = Image.new('RGB', img.size, (255, 255, 255))  # pantallazos con transparencia
        fondo.paste(img, mask=img.split()[-1])
        img = fondo
    else:
        img = img.convert('RGB')
    img.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.LANCZOS)
    calidad = 85
    while True:
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=calidad, optimize=True)
        if buf.tell() <= MAX_BYTES_FINAL or calidad <= 45:
            return buf.getvalue()
        calidad -= 10


def subir_comprobante(archivo):
    """Comprime y sube la foto a Cloudinary; devuelve su URL."""
    from paginaweb.cloudinary_client import upload_to_cloudinary
    if archivo.size > MAX_BYTES_ORIGINAL:
        raise ComprobanteInvalido('La foto supera los 40 MB.')
    datos = comprimir_comprobante(archivo.read())
    nombre = f"recibos_caja/{timezone.localtime().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
    return upload_to_cloudinary(datos, nombre, 'image/jpeg')


def urls_validas(urls):
    """Solo URLs de fotos subidas por la plataforma (Cloudinary de la cuenta, carpeta recibos_caja)."""
    if urls in (None, ''):
        return []
    if not isinstance(urls, list):
        raise ComprobanteInvalido('Formato de fotos inválido.')
    if len(urls) > MAX_FOTOS:
        raise ComprobanteInvalido(f'Máximo {MAX_FOTOS} fotos por recibo.')
    prefijo = f'https://res.cloudinary.com/{settings.CLOUDINARY_CLOUD_NAME}/'
    limpias = []
    for url in urls:
        if not isinstance(url, str) or not url.startswith(prefijo) or '/recibos_caja/' not in url or len(url) > 500:
            raise ComprobanteInvalido('Una de las fotos no se subió desde la plataforma. Vuelve a adjuntarla.')
        if url not in limpias:
            limpias.append(url)
    return limpias
