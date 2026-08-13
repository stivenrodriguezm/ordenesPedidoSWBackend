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
