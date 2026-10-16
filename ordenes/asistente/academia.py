"""Cursos privados, checkpoints y trabajos recuperables de la oficina virtual."""
import ipaddress
import json
import os
import subprocess
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from django.conf import settings
from django.db import connection, InterfaceError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from ..models import ConexionAcademia, CursoAcademia, CustomUser
from ..permissions import tiene_permiso_codigo
from . import perfiles

ACTIVOS = ['pendiente', 'trabajando', 'conexion']
DECLARACION = {
    'name': 'crear_curso',
    'description': 'Crea realmente un curso privado en la Academia Lottus y en Gemini Notebook, con investigación web, lecciones, ejercicios, evaluación y videos opcionales. Úsala SOLO cuando el usuario pide crear/hacer/generar un curso, capacitación o formación; no para consultar qué puedes hacer ni para una simple propuesta. La ejecución continúa en segundo plano, también en automatizaciones. No envíes datos internos del negocio.',
    'parameters': {'type': 'object', 'properties': {
        'modulos': {'type': 'integer', 'description': 'De 2 a 6 módulos; por defecto 3.'},
        'videos': {'type': 'boolean', 'description': 'Un video por módulo; por defecto true. Respeta lo pedido por el usuario.'},
        'investigar': {'type': 'boolean', 'description': 'Investigar fuentes públicas; true por defecto. Si piden usar solo los enlaces indicados, false.'},
    }},
}


def autorizado(usuario, perfil):
    request = SimpleNamespace(user=usuario)
    if not usuario.is_active or not tiene_permiso_codigo(request, 'USAR_ASISTENTE_IA'):
        return False
    if not perfil or not perfil.activo or 'formacion' not in perfil.areas:
        return False
    return tiene_permiso_codigo(request, 'GESTIONAR_PERFILES_IA') or perfiles.visible_para(perfil, usuario)


def raiz():
    return Path(getattr(settings, 'ACADEMIA_ROOT', settings.BASE_DIR / 'private_media' / 'academia'))


def storage(usuario_id):
    return raiz() / 'sesiones' / str(usuario_id) / 'storage_state.json'


def video_path(curso, indice):
    return raiz() / 'cursos' / str(curso.usuario_id) / str(curso.pk) / ('modulo-%s.mp4' % indice)


def runtime():
    return Path(getattr(settings, 'ACADEMIA_PYTHON', settings.BASE_DIR / '.cache' / 'notebook-runtime' / 'bin' / 'python'))


def operacion(usuario_id, op, **datos):
    if not runtime().is_file():
        raise ErrorAcademia('El conector de Google necesita instalarse en el servidor.', 'Configuracion')
    payload = {'storage': str(storage(usuario_id)), 'op': op, **datos}
    # La base remota cierra conexiones ociosas mientras Google investiga/genera.
    # No conservar una conexión de BD durante una operación externa larga.
    if not connection.in_atomic_block:
        connection.close()
    try:
        proc = subprocess.run([str(runtime()), str(Path(__file__).with_name('notebook_runner.py'))],
            input=json.dumps(payload), text=True, capture_output=True, timeout=180,
            env=dict(os.environ, NOTEBOOKLM_HOME=str(raiz() / 'sesiones' / str(usuario_id) / 'cli')))
    except subprocess.TimeoutExpired:
        raise ErrorAcademia('Google no respondió a tiempo. Conservamos el avance para retomarlo.', 'Timeout') from None
    try:
        result = json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise ErrorAcademia('El conector no respondió correctamente. Revisa su instalación.', 'Conector') from None
    if not result.get('ok'):
        raise ErrorAcademia(result.get('error', 'Google no confirmó el paso.'), result.get('tipo', 'Conector'))
    return result


class ErrorAcademia(Exception):
    def __init__(self, texto, tipo='Conector'):
        super().__init__(texto)
        self.tipo = tipo


def url_publica(value):
    try:
        p = urlsplit(value)
        host = (p.hostname or '').lower().rstrip('.')
        if p.scheme != 'https' or not host or p.username or p.password or (p.port not in (None, 443)):
            raise ValueError
        if '.' not in host or host == 'localhost' or host.endswith(('.local', '.internal', '.localhost', '.test')):
            raise ValueError
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError
        except ValueError as exc:
            if host.replace('.', '').isdigit() or ':' in host:
                raise exc
        return value
    except (ValueError, TypeError):
        raise serializers.ValidationError('Usa enlaces HTTPS públicos, sin contraseñas ni direcciones locales.') from None


class CursoEntrada(serializers.Serializer):
    clave = serializers.UUIDField()
    titulo = serializers.CharField(max_length=160, required=False, allow_blank=True)
    solicitud = serializers.CharField(min_length=12, max_length=4000)
    audiencia = serializers.CharField(max_length=200, default='Equipo de Lottus')
    numero_modulos = serializers.IntegerField(min_value=2, max_value=6, default=3)
    con_videos = serializers.BooleanField(default=True)
    investigar = serializers.BooleanField(default=True)
    urls = serializers.ListField(child=serializers.URLField(max_length=1500), max_length=8, default=list)

    def validate_urls(self, value):
        return list(dict.fromkeys(url_publica(u) for u in value))

    def validate(self, attrs):
        if not attrs['investigar'] and not attrs['urls']:
            raise serializers.ValidationError('Añade una fuente o activa la investigación del coach.')
        return attrs


def crear(usuario, perfil, datos, mensaje=None):
    if not autorizado(usuario, perfil):
        raise PermissionDenied('Este agente no tiene habilitada la formación o ya no tienes acceso a él.')
    entrada = CursoEntrada(data=datos)
    entrada.is_valid(raise_exception=True)
    values = entrada.validated_data
    with transaction.atomic():
        CustomUser.objects.select_for_update().get(pk=usuario.pk)
        previo = CursoAcademia.objects.filter(clave=values['clave']).first()
        if previo:
            if previo.usuario_id != usuario.pk:
                raise PermissionDenied('La solicitud pertenece a otra persona.')
            return previo
        if mensaje:
            previo = CursoAcademia.objects.filter(mensaje=mensaje).first()
            if previo:
                return previo
        if CursoAcademia.objects.filter(usuario=usuario, estado__in=ACTIVOS).count() >= 3:
            raise serializers.ValidationError('Puedes tener hasta tres cursos en preparación. Espera a que termine alguno.')
        if CursoAcademia.objects.filter(usuario=usuario, creado__gte=timezone.now()-timedelta(hours=24)).count() >= 10:
            raise serializers.ValidationError('Ya solicitaste diez cursos en las últimas 24 horas. Puedes continuar mañana.')
        connected = ConexionAcademia.objects.filter(usuario=usuario, estado='conectada').exists() and storage(usuario.pk).is_file()
        values['titulo'] = values.get('titulo') or values['solicitud'][:160]
        return CursoAcademia.objects.create(usuario=usuario, perfil=perfil, mensaje=mensaje,
            estado='pendiente' if connected else 'conexion',
            detalle='El coach comenzará en unos segundos' if connected else 'Conecta Google para comenzar', **values)


def crear_desde_chat(usuario, perfil, mensaje_id, args):
    from ..models import MensajeAsistente
    respuesta = MensajeAsistente.objects.select_related('conversacion').get(pk=mensaje_id, conversacion__usuario=usuario)
    pregunta = respuesta.conversacion.mensajes.filter(rol='usuario', id__lt=mensaje_id).order_by('-id').first()
    if not pregunta:
        raise serializers.ValidationError('No se encontró la solicitud original del curso.')
    # Solo viaja el texto que el humano escribió; nunca historial, memorias ni consultas financieras.
    import re
    import unicodedata
    texto = ''.join(c for c in unicodedata.normalize('NFD', pregunta.texto.lower()) if unicodedata.category(c) != 'Mn')
    pide = (re.search(r'\b(curso|cursos|capacitacion|formacion|entrenamiento)\b', texto) and
            re.search(r'\b(crea\w*|haz\w*|hac\w*|prepar\w*|disen\w*|arm\w*|gener\w*|elabor\w*|quiero|necesito|program\w*)\b', texto))
    niega = re.search(r'\b(no|nunca)\s+(?:\w+\s+){0,2}(crees|crear|crea|hagas|hacer|generes|generar|prepares|preparar)\b', texto)
    if not pide or niega:
        raise serializers.ValidationError('Pídele explícitamente al coach que cree un curso para iniciar la preparación.')
    enlaces = re.findall(r'https://[^\s<>]+', pregunta.texto)
    curso = crear(usuario, perfil, {'clave': uuid.uuid5(uuid.NAMESPACE_URL, 'lottus-curso-mensaje:%s' % mensaje_id),
        'solicitud': pregunta.texto, 'numero_modulos': args.get('modulos', 3),
        'con_videos': args.get('videos', True), 'investigar': args.get('investigar', True), 'urls': [u.rstrip('.,)') for u in enlaces][:8]}, mensaje=respuesta)
    return {'curso_id': curso.pk, 'titulo': curso.titulo, 'estado': curso.estado,
        'abrir': '/IA?curso=%s' % curso.pk,
        'detalle': 'El curso quedó guardado. Abre la Academia para seguirlo; necesita conectar Google si aún no lo hiciste. No afirmes que las lecciones o videos están listos.'}


def datos_curso(curso, completo=False):
    out = {'id': curso.pk, 'titulo': curso.titulo, 'estado': curso.estado, 'etapa': curso.etapa,
        'detalle': curso.detalle, 'avance': curso.avance, 'error': curso.error,
        'audiencia': curso.audiencia, 'numero_modulos': curso.numero_modulos, 'con_videos': curso.con_videos,
        'coach': curso.perfil.nombre if curso.perfil else 'Coach no disponible', 'perfil': curso.perfil_id,
        'creado': curso.creado.isoformat(), 'actualizado': curso.actualizado.isoformat(),
        'notebook_url': 'https://notebooklm.google.com/notebook/%s' % curso.datos['notebook'] if curso.datos.get('notebook') else None,
        'ambiguo': bool(curso.datos.get('video_solicitando'))}
    if completo:
        out.update(solicitud=curso.solicitud, resumen=curso.resumen, fuentes=curso.fuentes, eventos=curso.eventos,
            modulos=[{**m, 'video_disponible': video_path(curso, i).is_file(),
                      'video_url': '/asistente/academia/cursos/%s/videos/%s/' % (curso.pk, i) if video_path(curso, i).is_file() else None}
                     for i, m in enumerate(curso.modulos)])
    return out


def guardar(curso, **changes):
    changes['actualizado'] = timezone.now()
    cambios = actualizar(CursoAcademia.objects.filter(pk=curso.pk, reserva=curso.reserva, estado__in=ACTIVOS), **changes)
    if not cambios:
        raise ErrorAcademia('La tarea cambió mientras el coach trabajaba.', 'Reserva')
    for k, v in changes.items():
        setattr(curso, k, v)


def actualizar(qs, **changes):
    # Solo repetir escrituras idempotentes en la BD, nunca llamadas a Google.
    for intento in range(2):
        try:
            return qs.update(**changes)
        except (OperationalError, InterfaceError):
            if intento or connection.in_atomic_block:
                raise
            connection.close()


def avanzar(curso, etapa, detalle, avance, **changes):
    evento = {'etapa': etapa, 'detalle': detalle, 'fecha': timezone.now().isoformat()}
    guardar(curso, etapa=etapa, detalle=detalle, avance=avance, eventos=[*curso.eventos, evento][-60:], **changes)


def paso(curso):
    if not autorizado(curso.usuario, curso.perfil):
        raise ErrorAcademia('El coach está pausado, fue eliminado o ya no tienes acceso. Revisa sus permisos.', 'Permisos')
    conexion = ConexionAcademia.objects.filter(usuario=curso.usuario, estado='conectada').first()
    if not conexion or not storage(curso.usuario_id).is_file():
        guardar(curso, estado='conexion', detalle='Conecta Google para continuar')
        return
    d = dict(curso.datos)
    if d.get('google_cuenta') and d['google_cuenta'] != conexion.cuenta:
        raise ErrorAcademia('Este curso pertenece a otra cuenta de Google. Conecta la cuenta que lo creó o solicita un curso nuevo.', 'Cuenta')
    def call(op, **payload):
        return operacion(curso.usuario_id, op, fuente_ids=[s['id'] for s in curso.fuentes], **({'cuenta_esperada': conexion.cuenta} if '@' in conexion.cuenta else {}), **({'notebook': d['notebook']} if d.get('notebook') else {}), **payload)
    if not d.get('notebook'):
        nuevo = call('cuaderno', titulo='LOTTUS · %s · Curso %s' % (curso.titulo[:100], curso.pk))
        d['notebook'] = nuevo['notebook']
        d['google_cuenta'] = conexion.cuenta
        avanzar(curso, 'fuentes', 'Cuaderno creado; reuniendo fuentes', 8, datos=d)
        return
    if d.get('url_indice', 0) < len(curso.urls):
        i = d.get('url_indice', 0)
        r = call('fuente', url=curso.urls[i])
        d['url_indice'] = i+1
        guardar(curso, datos=d, fuentes=r['fuentes'], detalle='Leyendo las fuentes que elegiste')
        return
    if curso.investigar and not d.get('investigacion'):
        consulta = ('Fuentes primarias, documentación oficial y guías educativas confiables sobre: ' + curso.solicitud)[:3500]
        r = call('investigar', consulta=consulta)
        d['investigacion'] = r['investigacion']
        avanzar(curso, 'fuentes', 'El coach está buscando referencias para el curso', 12, datos=d)
        return
    if curso.investigar and 'descubiertas' not in d:
        r = call('investigacion_estado', investigacion=d['investigacion'])
        if r['estado'] == 'in_progress':
            return
        if r['estado'] != 'completed' or not r['fuentes']:
            raise ErrorAcademia('La búsqueda de Google no encontró fuentes utilizables. Añade enlaces de referencia en un nuevo curso o revisa el cuaderno.', 'Fuentes')
        d['descubiertas'] = [s for s in r['fuentes'] if url_publica(s['url'])]
        guardar(curso, datos=d, detalle='Referencias encontradas; preparando su lectura')
        return
    if d.get('fuente_indice', 0) < len(d.get('descubiertas', [])):
        i = d.get('fuente_indice', 0)
        r = call('fuente', url=d['descubiertas'][i]['url'], opcional=True)
        d['fuente_indice'] = i+1
        motivos = {s['url']: s.get('motivo', '') for s in d['descubiertas']}
        fuentes = [{**s, 'motivo': motivos.get(s['url'], '')} for s in r['fuentes']]
        detalle = 'Leyendo referencia %s de %s' % (i+1, len(d['descubiertas']))
        if r.get('omitida'):
            detalle = 'Una referencia no está disponible; continuando con las demás'
            d['omitidas'] = [*d.get('omitidas', []), d['descubiertas'][i]['url']]
            avanzar(curso, 'fuentes', detalle, 15+int(10*(i+1)/len(d['descubiertas'])), datos=d, fuentes=fuentes)
        else:
            guardar(curso, datos=d, fuentes=fuentes, avance=15+int(10*(i+1)/len(d['descubiertas'])), detalle=detalle)
        return
    if not curso.fuentes:
        raise ErrorAcademia('No hay fuentes legibles para fundamentar el curso.', 'Fuentes')
    if not curso.modulos:
        r = call('plan', solicitud=curso.solicitud, audiencia=curso.audiencia, modulos=curso.numero_modulos)['plan']
        avanzar(curso, 'lecciones', 'Programa diseñado; escribiendo las lecciones', 30, titulo=r.get('titulo', curso.titulo)[:160],
            resumen=r.get('resumen', '')[:10000], modulos=r['modulos'])
        return
    for i, m in enumerate(curso.modulos):
        if not m.get('contenido') or m.get('contenido_version') != 2:
            r = call('leccion', solicitud=curso.solicitud, audiencia=curso.audiencia, titulo=m['titulo'], objetivo=m['objetivo'])
            m['contenido'] = r['contenido']
            m['referencias'] = r.get('referencias', [])
            m['contenido_version'] = 2
            avanzar(curso, 'lecciones', 'Lección %s de %s escrita' % (i+1, len(curso.modulos)), max(curso.avance, 30+int(20*(i+1)/len(curso.modulos))), modulos=curso.modulos)
            return
    for i, m in enumerate(curso.modulos):
        if not m.get('preguntas'):
            m['preguntas'] = call('evaluacion', titulo=m['titulo'])['preguntas']
            avanzar(curso, 'evaluacion', 'Evaluación del módulo %s preparada' % (i+1), 50+int(10*(i+1)/len(curso.modulos)), modulos=curso.modulos)
            return
    if curso.con_videos:
        for i, m in enumerate(curso.modulos):
            if video_path(curso, i).is_file():
                continue
            if not m.get('video_id'):
                if d.get('video_solicitando'):
                    raise ErrorAcademia('Google no devolvió el identificador del video solicitado. Revisa el cuaderno antes de vincularlo para evitar generarlo dos veces.', 'Ambiguo')
                # Checkpoint PREVIO a la mutación: una caída no origina otro video.
                d['video_solicitando'] = {'modulo': i, 'fecha': timezone.now().isoformat()}
                guardar(curso, datos=d, etapa='videos', detalle='Solicitando video del módulo %s' % (i+1))
                r = call('video', titulo=m['titulo'], objetivo=m['objetivo'], audiencia=curso.audiencia)
                if r.get('rechazado'):
                    d.pop('video_solicitando', None)
                    guardar(curso, datos=d)
                    raise ErrorAcademia('Google no aceptó el video. Revisa los límites de tu cuenta antes de retomar.', 'Video')
                m['video_id'] = r['video']
                d.pop('video_solicitando', None)
                avanzar(curso, 'videos', 'Google está generando el video %s de %s' % (i+1, len(curso.modulos)), 65+int(30*i/len(curso.modulos)), datos=d, modulos=curso.modulos)
                return
            r = call('video_estado', video=m['video_id'])
            m['video_estado'] = r['estado']
            guardar(curso, modulos=curso.modulos)
            if r['estado'] in ('pending', 'in_progress', 'processing'):
                return
            if r['estado'] != 'completed':
                raise ErrorAcademia('Google no completó el video del módulo %s. Revisa el cuaderno o termina el curso sin videos.' % (i+1), 'Video')
            r = call('descargar', video=m['video_id'], archivo=str(video_path(curso, i)))
            if not r.get('descargado'):
                raise ErrorAcademia('El video no se descargó completamente.', 'Video')
            avanzar(curso, 'videos', 'Video del módulo %s disponible' % (i+1), 65+int(30*(i+1)/len(curso.modulos)))
            return
    avanzar(curso, 'listo', 'Tu curso está listo para aprender', 100, estado='listo', error='')


def ejecutar_un_paso():
    now = timezone.now()
    candidata = CursoAcademia.objects.filter(estado__in=['pendiente', 'trabajando'], proxima_revision__lte=now).filter(
        Q(reservado_hasta__isnull=True) | Q(reservado_hasta__lt=now)).order_by('proxima_revision', 'id').values('pk', 'usuario_id').first()
    if not candidata:
        return False
    with transaction.atomic():
        # Misma jerarquía de locks que conectar/desconectar: usuario → curso.
        # Una sesión no se sustituye ni se elimina durante una operación de Google.
        CustomUser.objects.select_for_update().get(pk=candidata['usuario_id'])
        curso = CursoAcademia.objects.select_for_update().filter(pk=candidata['pk'], estado__in=['pendiente', 'trabajando'], proxima_revision__lte=now).filter(
            Q(reservado_hasta__isnull=True) | Q(reservado_hasta__lt=now)).first()
        if not curso:
            return False
        if ConexionAcademia.objects.filter(usuario_id=curso.usuario_id, estado='conectando').exists() or CursoAcademia.objects.filter(
                usuario_id=curso.usuario_id, reservado_hasta__gt=now).exclude(pk=curso.pk).exists():
            return False
        curso.reserva = uuid.uuid4()
        curso.reservado_hasta = now+timedelta(minutes=4)
        curso.estado = 'trabajando'
        curso.save(update_fields=['reserva', 'reservado_hasta', 'estado'])
    try:
        paso(curso)
    except ErrorAcademia as exc:
        if exc.tipo == 'AuthError':
            ConexionAcademia.objects.filter(usuario=curso.usuario).update(estado='vencida', error=str(exc))
            guardar(curso, estado='conexion', error=str(exc), detalle='Vuelve a conectar Google')
        else:
            guardar(curso, estado='error', error=str(exc)[:500], detalle='El coach necesita tu atención')
    except Exception:
        # Nunca volcar respuestas del conector, cookies ni URL firmadas en logs.
        guardar(curso, estado='error', error='No se pudo completar el paso. Conservamos el avance; puedes retomar el curso.', detalle='Preparación interrumpida')
    finally:
        actualizar(CursoAcademia.objects.filter(pk=curso.pk, reserva=curso.reserva), reservado_hasta=None, reserva=None,
            proxima_revision=timezone.now()+timedelta(seconds=15 if curso.etapa=='videos' else 2))
    return True
