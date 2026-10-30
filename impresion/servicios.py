"""Cola de impresión remota. El agente de la oficina consulta cada pocos segundos, así que
esa consulta no toca la base (límite de conexiones/hora del hosting): el token, el latido
y el aviso de «hay trabajo» viven en la caché en disco compartida por los workers; la base
solo se consulta cuando hay aviso o cada REVISION_SEG por si la caché se perdió."""
import hashlib
import secrets
import time
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import Impresora, TrabajoImpresion as T

EN_LINEA_SEG = 60       # el agente consulta cada ~3 s: un minuto sin noticias = desconectado
REVISION_SEG = 300      # sin aviso, la base se revisa igual cada 5 minutos
TOKEN_SEG = 3600
VENCE_HORAS = 12        # lo que no se imprimió en ese plazo ya no sale (evita hojas viejas sorpresa)
SIN_CONFIRMAR_MIN = 10  # tomado por el agente y nunca confirmado
MAX_HTML = 3_000_000
MAX_COPIAS = 10

SIGUE = {T.PROCESANDO: {T.ENVIADO, T.IMPRESO, T.ERROR}, T.ENVIADO: {T.IMPRESO, T.ERROR}}


def _k(*partes):
    return 'impresion:' + ':'.join(str(p) for p in partes)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def nuevo_token():
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def olvidar_token(token_hash):
    cache.delete(_k('token', token_hash))


def impresora_del_token(token, puede_consultar_base=True):
    """Id de la impresora activa dueña del token, o None."""
    if not token or len(token) > 200:
        return None
    h = hash_token(token)
    imp = cache.get(_k('token', h))
    if imp is None:
        if not puede_consultar_base:
            return None
        imp = Impresora.objects.filter(token_hash=h, activa=True).values_list('pk', flat=True).first() or 0
        cache.set(_k('token', h), imp, TOKEN_SEG if imp else 600)
    return imp or None


def ultima_conexion(imp_id):
    return cache.get(_k('latido', imp_id))


def en_linea(imp_id):
    ts = ultima_conexion(imp_id)
    return bool(ts) and time.time() - ts < EN_LINEA_SEG


def registrar_impresora_encontrada(imp_id, encontrada):
    """Lo que informa el agente en cada consulta (solo caché: esa consulta no toca la base)."""
    cache.set(_k('encontrada', imp_id), bool(encontrada), EN_LINEA_SEG)


def impresora_encontrada(imp_id):
    """True o False según el agente; None si no ha informado (agente viejo o desconectado)."""
    return cache.get(_k('encontrada', imp_id))


def avisar(imp_id):
    cache.set(_k('pendiente', imp_id), 1, None)


def siguiente_trabajo(imp_id):
    """Registra el latido y entrega (marcándolo «procesando») el próximo trabajo en cola."""
    ahora = time.time()
    cache.set(_k('latido', imp_id), ahora, 86400)
    if not cache.get(_k('pendiente', imp_id)) and ahora - (cache.get(_k('revisado', imp_id)) or 0) < REVISION_SEG:
        return None
    # Se borra antes de consultar: lo que llegue mientras tanto vuelve a avisar.
    cache.delete(_k('pendiente', imp_id))
    cache.set(_k('revisado', imp_id), ahora, None)
    momento = timezone.now()
    trabajos = T.objects.filter(impresora_id=imp_id)
    trabajos.filter(estado=T.PENDIENTE, creado__lt=momento - timedelta(hours=VENCE_HORAS)).update(
        estado=T.ERROR, actualizado=momento,
        detalle='Venció sin imprimirse: la computadora de la oficina no estuvo conectada.')
    trabajos.filter(estado=T.PROCESANDO, actualizado__lt=momento - timedelta(minutes=SIN_CONFIRMAR_MIN)).update(
        estado=T.ERROR, actualizado=momento, detalle='La computadora de la oficina no confirmó la impresión.')
    for pk in trabajos.filter(estado=T.PENDIENTE).values_list('pk', flat=True)[:3]:
        if T.objects.filter(pk=pk, estado=T.PENDIENTE).update(estado=T.PROCESANDO, actualizado=momento):
            avisar(imp_id)  # puede haber más en cola
            return T.objects.get(pk=pk)
    return None


def reportar(imp_id, pk, estado, detalle=''):
    """El agente informa cómo va un trabajo suyo. False si no corresponde."""
    trabajo = T.objects.filter(pk=pk, impresora_id=imp_id).first()
    if trabajo is None or estado not in SIGUE.get(trabajo.estado, ()):
        return False
    trabajo.estado = estado
    trabajo.detalle = (detalle or '')[:255]
    trabajo.save(update_fields=['estado', 'detalle', 'actualizado'])
    return True
