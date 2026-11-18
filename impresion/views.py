from datetime import datetime, timezone as tz

from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, UserRateThrottle

from lottusPedidos.throttling import ApiUserRateThrottle
from ordenes.permissions import IsAdministradorRole
from ordenes.servicios import auditar
from . import servicios as s
from .models import Impresora, TrabajoImpresion as T


class LimiteTrabajos(UserRateThrottle):
    scope = 'impresion'


def _fecha(ts):
    return datetime.fromtimestamp(ts, tz.utc).isoformat() if ts else None


def _impresora(imp):
    return {'id': imp.pk, 'nombre': imp.nombre, 'ubicacion': imp.ubicacion,
            'en_linea': s.en_linea(imp.pk), 'ultima_conexion': _fecha(s.ultima_conexion(imp.pk)),
            # En línea es la computadora; esto dice si ella ve la impresora.
            'impresora_encontrada': s.impresora_encontrada(imp.pk), 'admite_anexos': s.admite_anexos(imp.pk)}


def _trabajo(t):
    return {'id': t.pk, 'titulo': t.titulo, 'copias': t.copias, 'estado': t.estado,
            'estado_nombre': t.get_estado_display(), 'detalle': t.detalle, 'creado': t.creado,
            'impresora': t.impresora_id, 'doble_cara': t.doble_cara}


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
    # (2026-11-18) En la oficina todo sale en carta (lo fija el documento) y a doble cara.
    trabajo = T.objects.create(impresora=imp, usuario=request.user, titulo=titulo, html=html, copias=copias, doble_cara=True)
    transaction.on_commit(lambda: s.avisar(imp.pk))
    return Response({**_trabajo(trabajo), 'en_linea': s.en_linea(imp.pk)}, status=201)


@api_view(['GET'])
def trabajo(request, pk):
    return Response(_trabajo(get_object_or_404(T, pk=pk, usuario=request.user)))


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdministradorRole])
def conectar_computadora(request):
    """(2026-11-18) El instalador de la computadora de la oficina entra con un administrador
    y recibe el token de su impresora: renueva el de la impresora activa (la anterior
    computadora deja de imprimir) o, si no hay ninguna, la crea. Con varias, hay que elegir."""
    d = request.data
    equipo = str(d.get('equipo') or '').strip()[:80]
    with transaction.atomic():
        activas = list(Impresora.objects.select_for_update().filter(activa=True))
        elegida = str(d.get('impresora') or '')
        if elegida:
            imp = next((i for i in activas if str(i.pk) == elegida), None)
            if imp is None:
                return Response({'error': 'Esa impresora no existe o está desactivada.'}, status=400)
        elif len(activas) > 1:
            return Response({'error': 'Hay varias impresoras de oficina: elige cuál conectar.',
                             'impresoras': [{'id': i.pk, 'nombre': i.nombre, 'ubicacion': i.ubicacion} for i in activas]},
                            status=409)
        else:
            imp = activas[0] if activas else None
        token, h = s.nuevo_token()
        if imp is None:
            nombre = str(d.get('nombre') or '').strip()[:80] or 'Ricoh oficina'
            imp = Impresora.objects.create(nombre=nombre, ubicacion='Oficina principal', token_hash=h)
            nueva = True
        else:
            anterior = imp.token_hash
            imp.token_hash = h
            imp.save(update_fields=['token_hash'])
            transaction.on_commit(lambda: s.olvidar_token(anterior))
            nueva = False
        auditar(request.user, 'impresion.computadora_conectada', imp, {'equipo': equipo, 'nueva': nueva})
    return Response({'impresora': imp.pk, 'nombre': imp.nombre, 'ubicacion': imp.ubicacion, 'token': token},
                    status=201 if nueva else 200)


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
    if 'impresora_ok' in request.data:
        s.registrar_impresora_encontrada(imp, request.data['impresora_ok'])
    s.registrar_capacidades(imp, request.data.get('admite_pdf'), request.data.get('admite_doble_cara'))
    t = s.siguiente_trabajo(imp, admite_pdf=s.admite_anexos(imp))
    if t is None:
        return Response(status=204)
    return Response({'id': t.pk, 'titulo': t.titulo, 'copias': t.copias, 'html': t.html, 'pdf': t.pdf, 'doble_cara': t.doble_cara})


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
