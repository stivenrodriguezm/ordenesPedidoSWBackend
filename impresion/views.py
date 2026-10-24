from datetime import datetime, timezone as tz

from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, UserRateThrottle

from lottusPedidos.throttling import ApiUserRateThrottle
from . import servicios as s
from .models import Impresora, TrabajoImpresion as T


class LimiteTrabajos(UserRateThrottle):
    scope = 'impresion'


def _fecha(ts):
    return datetime.fromtimestamp(ts, tz.utc).isoformat() if ts else None


def _impresora(imp):
    return {'id': imp.pk, 'nombre': imp.nombre, 'ubicacion': imp.ubicacion,
            'en_linea': s.en_linea(imp.pk), 'ultima_conexion': _fecha(s.ultima_conexion(imp.pk))}


def _trabajo(t):
    return {'id': t.pk, 'titulo': t.titulo, 'copias': t.copias, 'estado': t.estado,
            'estado_nombre': t.get_estado_display(), 'detalle': t.detalle, 'creado': t.creado,
            'impresora': t.impresora_id}


@api_view(['GET'])
def impresoras(request):
    return Response([_impresora(i) for i in Impresora.objects.filter(activa=True)])


@api_view(['POST'])
@throttle_classes([ApiUserRateThrottle, LimiteTrabajos])
def crear_trabajo(request):
    d = request.data
    imp = Impresora.objects.filter(pk=d.get('impresora') if str(d.get('impresora', '')).isdigit() else None, activa=True).first()
    if imp is None:
        return Response({'error': 'La impresora no está disponible.'}, status=400)
    html = d.get('html')
    if not isinstance(html, str) or '<' not in html:
        return Response({'error': 'No llegó el documento a imprimir.'}, status=400)
    if len(html) > s.MAX_HTML:
        return Response({'error': 'El documento es demasiado grande para imprimirlo en la oficina.'}, status=400)
    try:
        copias = int(d.get('copias', 1))
    except (TypeError, ValueError):
        copias = 0
    if not 1 <= copias <= s.MAX_COPIAS:
        return Response({'error': f'Las copias van de 1 a {s.MAX_COPIAS}.'}, status=400)
    titulo = str(d.get('titulo') or 'Documento').strip()[:150] or 'Documento'
    trabajo = T.objects.create(impresora=imp, usuario=request.user, titulo=titulo, html=html, copias=copias)
    transaction.on_commit(lambda: s.avisar(imp.pk))
    return Response({**_trabajo(trabajo), 'en_linea': s.en_linea(imp.pk)}, status=201)


@api_view(['GET'])
def trabajo(request, pk):
    return Response(_trabajo(get_object_or_404(T, pk=pk, usuario=request.user)))


# ---------------------------------------------------------------------------
# Agente de la oficina: autenticado con el token de su impresora, sin usuario
# ni JWT, y sin el límite anónimo (consulta cada pocos segundos).
# ---------------------------------------------------------------------------

FALLOS_HORA = 30


def _agente(request):
    """Id de la impresora del agente, o una respuesta de error."""
    tipo, _, token = request.META.get('HTTP_AUTHORIZATION', '').partition(' ')
    if tipo != 'Impresora' or not token:
        return None, Response({'error': 'Falta el token de la impresora.'}, status=401)
    clave = 'impresion:fallos:' + BaseThrottle().get_ident(request)
    # Con demasiados intentos fallidos solo se aceptan tokens ya validados (en caché):
    # el agente legítimo sigue funcionando y los intentos no llegan a la base.
    imp = s.impresora_del_token(token.strip(), puede_consultar_base=(cache.get(clave) or 0) < FALLOS_HORA)
    if imp is None:
        try:
            cache.incr(clave)
        except ValueError:
            cache.set(clave, 1, 3600)
        return None, Response({'error': 'Token de impresora inválido.'}, status=401)
    return imp, None


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([])
def agente_siguiente(request):
    imp, error = _agente(request)
    if error:
        return error
    t = s.siguiente_trabajo(imp)
    if t is None:
        return Response(status=204)
    return Response({'id': t.pk, 'titulo': t.titulo, 'copias': t.copias, 'html': t.html})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([])
def agente_reportar(request, pk):
    imp, error = _agente(request)
    if error:
        return error
    if not s.reportar(imp, pk, request.data.get('estado'), str(request.data.get('detalle') or '')):
        return Response({'error': 'El trabajo no está en un estado que permita ese cambio.'}, status=409)
    return Response({'ok': True})
