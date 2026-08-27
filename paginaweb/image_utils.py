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
