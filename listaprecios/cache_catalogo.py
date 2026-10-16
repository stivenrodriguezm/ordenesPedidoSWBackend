"""Caché del catálogo de vendedor (2026-10-15).

Armar el catálogo son 8 consultas a la base remota (~1 s). Se guarda ya serializado y se
descarta en cuanto cambia cualquier dato de la lista de precios: cada guardado o borrado de
un modelo de esta app (salvo las cotizaciones) cambia la versión al confirmarse la
transacción, y las actualizaciones masivas llaman a `invalidar()`. Caduca igual a los 10
minutos por si algo cambiara por fuera (consola, SQL).
"""
import time

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save

CLAVE_VERSION = 'lp:catalogo:version'
DURACION = 600
SIN_EFECTO = {'Cotizacion', 'LineaCotizacion'}


def version():
    actual = cache.get(CLAVE_VERSION)
    if actual is None:
        actual = time.time_ns()
        cache.set(CLAVE_VERSION, actual, None)
    return actual


def invalidar():
    # Después del commit: antes, otra consulta podría guardar en caché los datos viejos.
    transaction.on_commit(lambda: cache.set(CLAVE_VERSION, time.time_ns(), None))


def obtener(nombre, construir):
    clave = f'lp:{nombre}:{version()}'
    datos = cache.get(clave)
    if datos is None:
        datos = construir()
        cache.set(clave, datos, DURACION)
    return datos


def _al_cambiar(sender, **kwargs):
    if ((sender._meta.app_label == 'listaprecios' and sender.__name__ not in SIN_EFECTO)
            or sender._meta.label in {'ordenes.Referencia', 'ordenes.Proveedor', 'suministros.Categoria', 'suministros.Subcategoria'}):
        invalidar()


def _al_clasificar(action, **kwargs):
    if action in {'post_add', 'post_remove', 'post_clear'}:
        invalidar()


def conectar():
    post_save.connect(_al_cambiar, dispatch_uid='lp-catalogo-save')
    post_delete.connect(_al_cambiar, dispatch_uid='lp-catalogo-delete')
    from ordenes.models import Referencia
    for campo in ('categorias', 'subcategorias'):
        m2m_changed.connect(_al_clasificar, sender=getattr(Referencia, campo).through, dispatch_uid=f'lp-referencia-{campo}')
