"""Conversión de fotos RAW de cámara (CR2, NEF, ARW, DNG, ...) a JPEG — los
navegadores no pueden mostrar RAW directamente, así que para que un producto
subido en formato RAW se vea en la web hay que revelarlo a JPEG primero."""
import io

import rawpy
from PIL import Image

RAW_EXTENSIONS = {
    '.cr2', '.cr3', '.nef', '.nrw', '.arw', '.srf', '.sr2', '.raf', '.rw2',
    '.orf', '.dng', '.pef', '.srw', '.raw', '.kdc', '.mrw', '.x3f', '.3fr',
    '.erf', '.mef', '.mos', '.ptx', '.rwl', '.iiq',
}


class RawConversionError(Exception):
    pass


class InvalidImageError(Exception):
    pass


_FORMAT_TO_CONTENT_TYPE = {
    'JPEG': 'image/jpeg',
    'PNG': 'image/png',
    'WEBP': 'image/webp',
    'GIF': 'image/gif',
    'AVIF': 'image/avif',
}
_FORMAT_TO_EXT = {
    'JPEG': '.jpg',
    'PNG': '.png',
    'WEBP': '.webp',
    'GIF': '.gif',
    'AVIF': '.avif',
}


class InvalidVideoError(Exception):
    pass


def validate_video(file_bytes):
    """Verifica que ``file_bytes`` sea un video real reconocible (MP4/MOV/WebM)
    inspeccionando la firma binaria del archivo — no la extensión ni el
    content-type que haya declarado el cliente. Devuelve (extensión,
    content-type) según el contenedor detectado.

    No valida el códec interno (requeriría un parser completo o ffprobe, que
    no están disponibles aquí); el objetivo es descartar archivos que no son
    video en absoluto, igual que ``validate_image`` para fotos.
    """
    if len(file_bytes) < 12:
        raise InvalidVideoError("El archivo es demasiado pequeño para ser un video válido.")

    head = file_bytes[:12]
    # MP4/MOV/M4V comparten el contenedor ISO Base Media: tras 4 bytes de
    # tamaño de caja viene la firma ASCII 'ftyp'.
    if head[4:8] == b'ftyp':
        brand = head[8:12]
        if brand.startswith(b'qt'):
            return '.mov', 'video/quicktime'
        return '.mp4', 'video/mp4'
    # WebM/Matroska: cabecera EBML.
    if head[:4] == b'\x1a\x45\xdf\xa3':
        return '.webm', 'video/webm'

    raise InvalidVideoError("El archivo no es un video soportado (usa MP4, MOV o WebM).")


def validate_image(file_bytes):
    """Verifica que ``file_bytes`` sea una imagen real decodificable (no un
    archivo con extensión falsificada) y devuelve la extensión y content-type
    reales según el contenido, ignorando lo que haya declarado el cliente.

    Lanza ``InvalidImageError`` si los bytes no son una imagen soportada.
    """
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            img.verify()
        # verify() deja el objeto inutilizable para más operaciones; se
        # reabre para leer el formato de forma confiable tras la verificación.
        with Image.open(io.BytesIO(file_bytes)) as img:
            fmt = img.format
    except Exception as e:
        raise InvalidImageError(f"El archivo no es una imagen válida: {e}")

    if fmt not in _FORMAT_TO_CONTENT_TYPE:
        raise InvalidImageError(f"Formato de imagen no soportado: {fmt}")

    return _FORMAT_TO_EXT[fmt], _FORMAT_TO_CONTENT_TYPE[fmt]


MAX_UPLOAD_DIMENSION = 3500  # px — más que suficiente para cualquier pantalla,
# incluida una 4K a pantalla completa; una foto más grande que esto no aporta
# nada visible en la web, solo peso.
MAX_UPLOAD_BYTES = 9_500_000  # margen bajo el límite real de subida de
# Cloudinary en el plan gratis (10 MB exactos) — ver media_limits de la cuenta.


def optimize_image_for_upload(file_bytes, ext, content_type):
    """Redimensiona y/o recomprime la imagen solo si hace falta para caber
    bajo el límite de subida de Cloudinary, sin sacrificar calidad visible:
    Cloudinary igual reoptimiza todo en la entrega (f_auto,q_auto), así que
    subir un original de 20-40 MB de una cámara no mejora en nada lo que
    finalmente ve el visitante — solo hacía fallar la subida.

    Devuelve (bytes, extensión, content-type), iguales a los de entrada si
    ya cabía sin tocar nada.
    """
    if len(file_bytes) <= MAX_UPLOAD_BYTES:
        try:
            with Image.open(io.BytesIO(file_bytes)) as img:
                if max(img.size) <= MAX_UPLOAD_DIMENSION:
                    return file_bytes, ext, content_type
        except Exception:
            return file_bytes, ext, content_type

    with Image.open(io.BytesIO(file_bytes)) as img:
        img.load()
        fmt = img.format
        if max(img.size) > MAX_UPLOAD_DIMENSION:
            img.thumbnail((MAX_UPLOAD_DIMENSION, MAX_UPLOAD_DIMENSION), Image.LANCZOS)

        has_alpha = img.mode in ('RGBA', 'LA') and img.getextrema()[-1][0] < 255

        if fmt == 'PNG' and has_alpha:
            # No se puede pasar a JPEG sin perder la transparencia real —
            # se deja como PNG optimizado, aunque pese más.
            buf = io.BytesIO()
            img.save(buf, format='PNG', optimize=True)
            return buf.getvalue(), '.png', 'image/png'

        # Cualquier otro caso (incluido PNG sin transparencia real) se
        # recomprime como JPEG, bajando calidad de forma progresiva hasta
        # entrar en el límite.
        rgb = img.convert('RGB')
        quality = 92
        buf = io.BytesIO()
        rgb.save(buf, format='JPEG', quality=quality, optimize=True)
        while buf.tell() > MAX_UPLOAD_BYTES and quality > 55:
            quality -= 8
            buf = io.BytesIO()
            rgb.save(buf, format='JPEG', quality=quality, optimize=True)
        return buf.getvalue(), '.jpg', 'image/jpeg'


def convert_raw_to_jpeg(file_bytes, quality=92):
    """Revela un archivo RAW de cámara y lo devuelve como bytes JPEG."""
    try:
        with rawpy.imread(io.BytesIO(file_bytes)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
    except rawpy.LibRawError as e:
        raise RawConversionError(f"No se pudo leer el archivo RAW: {e}")

    image = Image.fromarray(rgb)
    buf = io.BytesIO()
    image.save(buf, format='JPEG', quality=quality)
    return buf.getvalue()
