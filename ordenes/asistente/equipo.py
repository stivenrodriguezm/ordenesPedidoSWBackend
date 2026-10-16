"""Conversaciones entre agentes de la oficina (2026-10-14).

IA Lottus le encarga a Alan (el ejecutor) los cambios que pide el usuario, Alan le
responde al terminar, los colegas se consultan entre sí y los líderes entregan su
informe de área. Todo queda en hilos por pareja de agentes, privados del usuario cuya
solicitud los originó (como sus chats).

Al cerrar cada tarea, ejecutor y solicitante anotan una lección según su papel. Las
lecciones son notas de «Lo aprendido» (origen 'equipo'): el usuario las ve y las
puede desactivar, y entran en las instrucciones de las siguientes respuestas.
"""
import json
import logging
import re
import unicodedata

from django.db.models import Count, Max

from ..models import AprendizajeAsistente, CustomUser, MensajeEquipoIA, PerfilAsistente
from . import perfiles

log = logging.getLogger(__name__)

GENERAL = 'ia-general'
NOMBRE_GENERAL = 'IA Lottus'
MAX_TEXTO = 4000
MAX_LECCIONES = 15  # lecciones del equipo activas por agente y usuario
CLAVE_VALIDA = re.compile(r'^ia-(?:general|\d+)$')


def clave(perfil):
    return f'ia-{perfil.pk}' if perfil else GENERAL


def _perfil(clave_agente, cache=None):
    if clave_agente == GENERAL:
        return None
    pk = int(clave_agente[3:])
    if cache is not None:
        if pk not in cache:
            cache[pk] = PerfilAsistente.objects.filter(pk=pk).first()
        return cache[pk]
    return PerfilAsistente.objects.filter(pk=pk).first()


def nombre(clave_agente, cache=None):
    if clave_agente == GENERAL:
        return NOMBRE_GENERAL
    p = _perfil(clave_agente, cache)
    return p.nombre if p else 'Agente retirado'


def decir(usuario, de, para, texto, tipo, trabajo=None, conversacion=None):
    """Un mensaje del hilo entre dos agentes. Nunca falla la tarea que lo origina."""
    texto = (texto or '').strip()
    if not usuario or not texto or de == para:
        return None
    try:
        return MensajeEquipoIA.objects.create(usuario=usuario, de=de, para=para, tipo=tipo, texto=texto[:MAX_TEXTO],
                                              trabajo=trabajo, conversacion=conversacion)
    except Exception:
        log.exception('No se pudo guardar el mensaje del equipo IA')
        return None


# --- Aviso corto en la oficina ------------------------------------------------------
# El plano es visible para todo el equipo: el globo dice qué tipo de cambio es, nunca
# el contenido (clientes, montos), que solo queda en el hilo privado.

_VERBOS = [
    (r'\b(?:crea|creame|registra|agrega|agregale|anade|guarda|ingresa|carga|haz)\b', 'registra'),
    (r'\b(?:modifica|cambia|cambiale|edita|actualiza|corrige|ajusta|resta|restale|suma|sumale|pon|ponle|asigna|marca)\b', 'actualiza'),
    (r'\b(?:elimina|borra|anula|cancela|quita)\b', 'anula'),
]
_OBJETOS = [
    ('pedido de tela', 'este pedido de tela'), ('pedidos de tela', 'estos pedidos de tela'),
    ('recibo', 'este recibo de caja'), ('comprobante', 'este comprobante de egreso'),
    ('factura', 'esta factura'), ('remision', 'esta remisión'), ('ventas', 'estas ventas'), ('venta', 'esta venta'),
    ('cliente', 'este cliente'), ('pedido', 'este pedido'), ('tela', 'esta tela'), ('inventario', 'este inventario'),
    ('caja', 'este movimiento de caja'), ('producto', 'este producto'), ('proveedor', 'este proveedor'),
    ('usuario', 'este usuario'), ('tarea', 'esta tarea'),
]


def _plano(texto):
    texto = unicodedata.normalize('NFKD', (texto or '').casefold())
    return ''.join(c for c in texto if not unicodedata.combining(c))


def aviso_corto(solicitud, destinatario):
    t = _plano(solicitud)
    verbo = next((v for patron, v in _VERBOS if re.search(patron, t)), None)
    objeto = next((o for palabra, o in _OBJETOS if re.search(r'\b' + palabra + r'\b', t)), None)
    if verbo and objeto:
        return f'Por favor, {destinatario}, {verbo} {objeto}.'[:160]
    if objeto:
        return f'Por favor, {destinatario}, ayúdame con {objeto}.'[:160]
    return f'Por favor, {destinatario}, ejecuta este cambio en la plataforma.'[:160]


# --- Hilos ------------------------------------------------------------------------

def _orden(clave_agente):
    return (0, 0) if clave_agente == GENERAL else (1, int(clave_agente[3:]))


def clave_hilo(a, b):
    return '~'.join(sorted([a, b], key=_orden))


def _participante(clave_agente, cache):
    p = None if clave_agente == GENERAL else _perfil(clave_agente, cache)
    return {'clave': clave_agente, 'nombre': nombre(clave_agente, cache), 'perfil': perfiles.resumen_perfil(p)}


def _visible(clave_agente, usuario, cache, gestiona):
    if clave_agente == GENERAL:
        return gestiona or perfiles.visible_para(None, usuario)
    p = _perfil(clave_agente, cache)
    # Un agente eliminado conserva su historial; uno vigente respeta la visibilidad por rol.
    return p is None or gestiona or perfiles.visible_para(p, usuario)


def hilos(usuario, gestiona=False):
    filas = MensajeEquipoIA.objects.filter(usuario=usuario).values('de', 'para').annotate(ultimo=Max('id'), total=Count('id'))
    grupos = {}
    for f in filas:
        k = clave_hilo(f['de'], f['para'])
        g = grupos.setdefault(k, {'ultimo': 0, 'total': 0})
        g['ultimo'] = max(g['ultimo'], f['ultimo'])
        g['total'] += f['total']
    ultimos = {m.pk: m for m in MensajeEquipoIA.objects.filter(pk__in=[g['ultimo'] for g in grupos.values()]).select_related('trabajo')}
    cache, salida = {}, []
    for k, g in grupos.items():
        a, b = k.split('~')
        if not (_visible(a, usuario, cache, gestiona) and _visible(b, usuario, cache, gestiona)):
            continue
        m = ultimos[g['ultimo']]
        salida.append({'clave': k, 'participantes': [_participante(a, cache), _participante(b, cache)], 'total': g['total'],
                       'ultimo': {'id': m.pk, 'de': m.de, 'nombre': nombre(m.de, cache), 'texto': m.texto[:160], 'tipo': m.tipo,
                                  'creado': m.creado.isoformat()},
                       'activo': bool(m.trabajo and m.trabajo.estado in ('pendiente', 'ejecutando'))})
    salida.sort(key=lambda h: h['ultimo']['id'], reverse=True)
    return salida


def mensajes(usuario, k, gestiona=False):
    partes = k.split('~')
    if len(partes) != 2 or not all(CLAVE_VALIDA.match(p) for p in partes) or partes[0] == partes[1]:
        return None
    a, b = partes
    cache = {}
    if not (_visible(a, usuario, cache, gestiona) and _visible(b, usuario, cache, gestiona)):
        return None
    qs = (MensajeEquipoIA.objects.filter(usuario=usuario, de__in=[a, b], para__in=[a, b])
          .select_related('trabajo').order_by('-id')[:200])
    from .agente import representar
    lista = []
    for m in reversed(list(qs)):
        lista.append({'id': m.pk, 'de': m.de, 'para': m.para, 'nombre': nombre(m.de, cache), 'tipo': m.tipo, 'texto': m.texto,
                      'creado': m.creado.isoformat(), 'conversacion': m.conversacion_id,
                      'trabajo': representar(m.trabajo, False) if m.trabajo else None})
    return {'clave': clave_hilo(a, b), 'participantes': [_participante(a, cache), _participante(b, cache)], 'mensajes': lista}


# --- Aprendizaje por tarea ------------------------------------------------------------

def guardar_leccion(usuario, perfil, texto, pregunta=''):
    texto = (texto or '').strip()[:400]
    if len(texto) < 15:
        return None
    existentes = AprendizajeAsistente.objects.filter(usuario=usuario, perfil=perfil, origen='equipo')
    if existentes.filter(texto__iexact=texto).exists():
        return None
    a = AprendizajeAsistente.objects.create(usuario=usuario, perfil=perfil, tipo='nota', texto=texto,
                                            pregunta=(pregunta or '')[:300], origen='equipo')
    # Solo las más recientes siguen activas: el agente mejora sin acumular ruido.
    viejas = list(existentes.filter(activo=True).order_by('-creado', '-id').values_list('pk', flat=True)[MAX_LECCIONES:])
    if viejas:
        AprendizajeAsistente.objects.filter(pk__in=viejas).update(activo=False)
    return a


def _json(texto):
    texto = re.sub(r'^```(?:json)?|```$', '', (texto or '').strip(), flags=re.MULTILINE).strip()
    inicio, fin = texto.find('{'), texto.rfind('}')
    if inicio < 0 or fin <= inicio:
        return {}
    try:
        datos = json.loads(texto[inicio:fin + 1])
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def retrospectiva(t, solicitante):
    """Al cerrar la tarea: una lección para cada agente según su papel (una sola consulta)."""
    from . import gemini
    ejecutor = t.agente
    if not ejecutor or not gemini.configurado():
        return
    usuario = CustomUser.objects.get(pk=t.usuario_id)
    pasos = [{'operacion': p.get('operacion'), 'resultado': str(p.get('resultado'))[:300]} for p in (t.pasos or [])][:12]
    nombre_solicitante = nombre(solicitante)
    prompt = (
        'Retrospectiva breve de una tarea entre agentes de la oficina LOTTUS.\n'
        f'Solicitante: {nombre_solicitante}. Ejecutor: {ejecutor.nombre} (papel: {ejecutor.rol}).\n'
        f'Solicitud original del usuario: {t.solicitud[:1500]}\n'
        f'Estado final: {t.estado}. Error: {t.error or "ninguno"}.\n'
        f'Pasos guardados: {json.dumps(pasos, ensure_ascii=False, default=str)}\n'
        f'Respuesta del ejecutor: {(t.resultado or "")[:1500]}\n\n'
        'Devuelve SOLO un JSON con las claves "ejecutor" y "solicitante". Cada valor es UNA lección concreta '
        '(máximo 220 caracteres) que ese agente aplicará en tareas parecidas según su papel: el ejecutor, cómo '
        'ejecutar mejor; el solicitante, cómo pedir o delegar mejor (qué datos reunir antes de encargar). '
        'Generaliza: sin nombres de clientes, teléfonos, cédulas ni montos. Si no hay nada nuevo que aprender, usa "".')
    try:
        r = gemini.analizar_evidencia(prompt, usuario, ejecutor, None, 25)
    except Exception:
        log.warning('Sin retrospectiva para la ejecución %s', t.pk, exc_info=True)
        return
    datos = _json(r.get('texto'))
    propio, ajeno = str(datos.get('ejecutor') or '').strip(), str(datos.get('solicitante') or '').strip()
    yo = clave(ejecutor)
    if propio and guardar_leccion(usuario, ejecutor, propio, t.solicitud):
        decir(usuario, yo, solicitante, f'Aprendí algo de esta tarea: {propio}', 'aprendizaje', t, t.conversacion)
    if ajeno and guardar_leccion(usuario, _perfil(solicitante), ajeno, t.solicitud):
        decir(usuario, solicitante, yo, f'Anotado. Para la próxima: {ajeno}', 'aprendizaje', t, t.conversacion)
