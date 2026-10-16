import threading
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import ConexionAcademia, CursoAcademia, CustomUser, PerfilAsistente
from ..servicios import auditar
from . import academia
from .views import _exigir


class AcademiaThrottle(SimpleRateThrottle):
    # La consulta de progreso no consume el contador diario de toda la oficina.
    scope = 'academia'
    def get_rate(self):
        return '60/min'

    def get_cache_key(self, request, view):
        lectura = request.method == 'GET'
        self.num_requests, self.duration = self.parse_rate('60/min' if lectura else '10/min')
        return self.cache_format % {'scope': 'academia_lectura' if lectura else 'academia_acciones', 'ident': request.user.pk}


def chrome_permitido(request):
    return (request.user.role == 'administrador' and settings.DEBUG and
            request.user.pk == getattr(settings, 'ACADEMIA_CHROME_USUARIO_ID', 0) and
            request.META.get('REMOTE_ADDR') in ('127.0.0.1', '::1'))


def estado_conexion(request):
    c = ConexionAcademia.objects.filter(usuario=request.user).first()
    latido = cache.get('academia-motor')
    return {'estado': c.estado if c else 'desconectada', 'cuenta': c.cuenta if c else '',
        'error': c.error if c else '', 'puede_conectar_chrome': chrome_permitido(request),
        'conector_instalado': academia.runtime().is_file(),
        'motor_activo': bool(latido and timezone.now().timestamp()-latido < 60)}


def conectar(usuario_id, accion, cuenta=''):
    try:
        user = CustomUser.objects.get(pk=usuario_id)
        if not user.is_active:
            return
        academia.raiz().mkdir(parents=True, exist_ok=True, mode=0o700)
        resultado = academia.operacion(usuario_id, 'conectar_chrome' if accion == 'chrome' else 'verificar', **({'cuenta': cuenta} if accion == 'chrome' else {}))
        ConexionAcademia.objects.filter(usuario_id=usuario_id, estado='conectando').update(
            estado='conectada', cuenta=resultado['cuenta'], error='', actualizado=timezone.now())
        CursoAcademia.objects.filter(usuario_id=usuario_id, estado='conexion').update(
            estado='pendiente', error='', detalle='Conexión lista; retomando el curso', proxima_revision=timezone.now())
    except academia.ErrorAcademia as exc:
        ConexionAcademia.objects.filter(usuario_id=usuario_id, estado='conectando').update(
            estado='vencida', error=str(exc)[:400], actualizado=timezone.now())
    except Exception:
        ConexionAcademia.objects.filter(usuario_id=usuario_id, estado='conectando').update(
            estado='vencida', error='No se pudo conectar Google. Revisa tu sesión y vuelve a intentar.', actualizado=timezone.now())
    finally:
        connection.close()


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes([AcademiaThrottle])
def conexion(request):
    if request.method != 'DELETE':
        _exigir(request)
    if request.method == 'GET':
        c = ConexionAcademia.objects.filter(usuario=request.user, estado='conectando', actualizado__lt=timezone.now()-timedelta(minutes=4))
        c.update(estado='vencida', error='La conexión se interrumpió. Vuelve a intentar.')
        return Response(estado_conexion(request))
    with transaction.atomic():
        CustomUser.objects.select_for_update().get(pk=request.user.pk)
        if CursoAcademia.objects.filter(usuario=request.user, reservado_hasta__gt=timezone.now()).exists():
            return Response({'error': 'El coach está utilizando Google. Espera a que termine este paso.'}, status=409)
        c, _ = ConexionAcademia.objects.get_or_create(usuario=request.user)
        if c.estado == 'conectando':
            return Response({'error': 'La conexión está en curso.'}, status=409)
        if request.method == 'DELETE':
            # Desvincula solo la plataforma, sin borrar cuadernos de Google.
            import shutil
            directorio = academia.storage(request.user.pk).parent
            if directorio.exists():
                shutil.rmtree(directorio)
            c.estado, c.cuenta, c.error = 'desconectada', '', ''
            c.save()
            CursoAcademia.objects.filter(usuario=request.user, estado__in=academia.ACTIVOS).update(
                estado='conexion', detalle='Google desconectado; esperando una nueva conexión')
            auditar(request.user, 'academia.desconectar', c, {})
            return Response(estado_conexion(request))
        accion = request.data.get('accion')
        if accion not in ('chrome', 'verificar'):
            raise serializers.ValidationError('Selecciona una conexión válida.')
        if accion == 'chrome' and (not chrome_permitido(request) or request.data.get('consentimiento') is not True):
            raise PermissionDenied('La conexión a Chrome requiere consentimiento del propietario y acceso local autorizado.')
        cuenta = serializers.EmailField().run_validation(request.data.get('cuenta')) if accion == 'chrome' else ''
        if accion == 'verificar' and not academia.storage(request.user.pk).is_file():
            return Response({'error': 'Primero conecta una sesión de Google en este servidor.'}, status=400)
        c.estado, c.error = 'conectando', ''
        c.save()
        auditar(request.user, 'academia.conectar', c, {'metodo': accion})
        transaction.on_commit(lambda: threading.Thread(target=conectar, args=(request.user.pk, accion, cuenta), daemon=True).start())
    return Response(estado_conexion(request), status=202)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([AcademiaThrottle])
def cursos(request):
    _exigir(request)
    if request.method == 'GET':
        return Response({'cursos': [academia.datos_curso(c) for c in CursoAcademia.objects.filter(usuario=request.user).select_related('perfil')[:100]],
                         'conexion': estado_conexion(request)})
    try:
        perfil_id = int(request.data.get('perfil'))
    except (ValueError, TypeError):
        raise serializers.ValidationError('Selecciona un coach válido.') from None
    perfil = get_object_or_404(PerfilAsistente, pk=perfil_id)
    curso = academia.crear(request.user, perfil, request.data)
    auditar(request.user, 'academia.crear_curso', curso, {'perfil': perfil.pk, 'modulos': curso.numero_modulos, 'videos': curso.con_videos})
    return Response(academia.datos_curso(curso, completo=True), status=202)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([AcademiaThrottle])
def curso(request, pk):
    _exigir(request)
    with transaction.atomic():
        c = get_object_or_404(CursoAcademia.objects.select_for_update().select_related('perfil'), pk=pk, usuario=request.user)
        if request.method == 'POST':
            accion = request.data.get('accion')
            if accion not in ('retomar', 'cancelar', 'sin_videos', 'vincular_video'):
                raise serializers.ValidationError('Acción de curso no válida.')
            if c.reservado_hasta and c.reservado_hasta > timezone.now():
                return Response({'error': 'El coach está terminando un paso. Intenta de nuevo en unos segundos.'}, status=409)
            if accion == 'cancelar':
                c.estado, c.detalle = 'cancelado', 'Preparación detenida; conservamos el material creado'
            else:
                if c.estado == 'listo':
                    raise serializers.ValidationError('El curso ya está completo.')
                if not academia.autorizado(request.user, c.perfil):
                    raise PermissionDenied('Este coach ya no está disponible para ti.')
                if accion == 'vincular_video':
                    pendiente = c.datos.get('video_solicitando')
                    try:
                        video = str(uuid.UUID(request.data.get('video_id', '')))
                    except (ValueError, AttributeError, TypeError):
                        raise serializers.ValidationError('Introduce el identificador del video del cuaderno.') from None
                    if not pendiente:
                        raise serializers.ValidationError('No hay un video pendiente de vincular.')
                    c.modulos[pendiente['modulo']]['video_id'] = video
                    c.datos.pop('video_solicitando', None)
                if accion == 'sin_videos':
                    c.con_videos = False
                    c.datos.pop('video_solicitando', None)
                if c.datos.get('video_solicitando'):
                    raise serializers.ValidationError('Revisa y vincula el video en Google o continúa sin videos para evitar duplicados.')
                if CursoAcademia.objects.filter(usuario=request.user, estado__in=academia.ACTIVOS).exclude(pk=c.pk).count() >= 3:
                    raise serializers.ValidationError('Ya tienes tres cursos en preparación.')
                conectada = ConexionAcademia.objects.filter(usuario=request.user, estado='conectada').exists()
                c.estado = 'pendiente' if conectada else 'conexion'
                c.detalle, c.error, c.proxima_revision = 'Retomando el material guardado', '', timezone.now()
            c.save()
            auditar(request.user, 'academia.%s' % accion, c, {})
    return Response(academia.datos_curso(c, completo=True))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([AcademiaThrottle])
def video(request, pk, indice):
    _exigir(request)
    c = get_object_or_404(CursoAcademia, pk=pk, usuario=request.user)
    path = academia.video_path(c, indice)
    if not 0 <= indice < len(c.modulos) or not path.is_file():
        from django.http import Http404
        raise Http404
    response = FileResponse(path.open('rb'), content_type='video/mp4', filename='lottus-curso-%s-modulo-%s.mp4' % (pk, indice+1))
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
