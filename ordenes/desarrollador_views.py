"""Agente Desarrollador (2026-10-28): API de la plataforma.

El usuario (solo superusuarios) pide una mejora; el servicio aparte del Desarrollador
(scripts/desarrollador/worker.py, en el VPS con su propio usuario del sistema) prepara el
plan con riesgos, espera la aprobación, implementa en una rama propia, corre las pruebas y
lo publica en la versión de pruebas. Ese servicio no toca la base de datos: lee y reporta
por el canal interno de abajo, autenticado con DESARROLLADOR_TOKEN.

Para no gastar conexiones a la base (límite por hora del hosting), la plataforma le avisa
al servicio cuando hay trabajo (POST local a /despertar) en vez de que el servicio consulte.
"""
import hmac
import logging

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from .models import TareaDesarrollo
from .servicios import auditar

log = logging.getLogger(__name__)

MAX_PEDIDO = 4000
MAX_EVENTOS = 200
CLAVE_LATIDO = 'desarrollador:latido'
# Lo que el servicio puede cambiar de estado (de → a). Las aprobaciones solo las da el usuario.
TRANSICIONES_SERVICIO = {
    'planificando': {'plan_listo', 'fallida'},
    'aprobada': {'implementando', 'fallida'},
    'implementando': {'en_pruebas', 'aplicada', 'fallida'},
    'deshaciendo': {'deshecha', 'aplicada'},  # aplicada otra vez si no se pudo deshacer
}
AVISOS = {'plan_listo': 'tiene el plan listo para que lo apruebes', 'en_pruebas': 'quedó lista en la versión de pruebas',
          'aplicada': 'quedó aplicada en la plataforma',
          'fallida': 'no se pudo completar'}


class SoloSuperusuario(BasePermission):
    message = 'Solo el administrador principal puede usar el Desarrollador.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class TokenServicio(BasePermission):
    """Canal interno del servicio Desarrollador (token compartido, comparación en tiempo constante)."""
    def has_permission(self, request, view):
        esperado = settings.DESARROLLADOR_TOKEN
        dado = request.headers.get('X-Desarrollador-Token', '')
        return bool(esperado) and hmac.compare_digest(esperado, dado)


PERMISOS = [IsAuthenticated, SoloSuperusuario]


def latido():
    return cache.get(CLAVE_LATIDO)


def despertar():
    """Le avisa al servicio que hay trabajo. Nunca falla la petición del usuario."""
    if not settings.DESARROLLADOR_TOKEN:
        return
    def _avisar():
        try:
            requests.post(f'{settings.DESARROLLADOR_WORKER_URL.rstrip("/")}/despertar',
                          headers={'X-Desarrollador-Token': settings.DESARROLLADOR_TOKEN}, timeout=2)
        except requests.RequestException:
            log.info('El servicio Desarrollador no respondió al aviso; tomará la tarea al arrancar.')
    transaction.on_commit(_avisar)


def evento(tarea, texto):
    tarea.eventos = [*tarea.eventos, {'t': timezone.now().isoformat(), 'texto': str(texto)[:500]}][-MAX_EVENTOS:]


def serializar(t, completo=True):
    datos = {'id': t.pk, 'pedido': t.pedido, 'estado': t.estado, 'estado_nombre': t.get_estado_display(),
             'riesgo': (t.plan or {}).get('riesgo', ''), 'resumen': (t.resultado or {}).get('resumen', ''),
             'vista_previa': t.vista_previa, 'creado': t.creado.isoformat(), 'actualizado': t.actualizado.isoformat()}
    if completo:
        datos.update({'ajustes': t.ajustes, 'plan': t.plan, 'resultado': t.resultado, 'diff': t.diff, 'error': t.error,
                      'eventos': t.eventos, 'modelo': t.modelo, 'tokens': t.tokens,
                      'aprobado_en': t.aprobado_en.isoformat() if t.aprobado_en else None})
    return datos


@api_view(['GET'])
@permission_classes(PERMISOS)
def estado(request):
    ultimo = latido()
    return Response({'configurado': bool(settings.DESARROLLADOR_TOKEN), 'servicio_activo': bool(ultimo), 'ultimo_latido': ultimo,
                     'pendientes': TareaDesarrollo.objects.filter(usuario=request.user, estado__in=['plan_listo', 'en_pruebas']).count()})


@api_view(['GET', 'POST'])
@permission_classes(PERMISOS)
def tareas(request):
    if request.method == 'GET':
        return Response([serializar(t, completo=False) for t in TareaDesarrollo.objects.filter(usuario=request.user)[:50]])
    pedido = str(request.data.get('pedido') or '').strip()
    if len(pedido) < 10:
        return Response({'pedido': 'Describe la mejora con un poco más de detalle.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(pedido) > MAX_PEDIDO:
        return Response({'pedido': f'Usa máximo {MAX_PEDIDO} caracteres; divide los pedidos grandes.'}, status=status.HTTP_400_BAD_REQUEST)
    t = TareaDesarrollo(usuario=request.user, pedido=pedido)
    evento(t, 'Pedido recibido. Preparando el plan.')
    t.save()
    auditar(request.user, 'desarrollador.pedido', t, {'pedido': pedido[:300]})
    despertar()
    return Response(serializar(t), status=status.HTTP_201_CREATED)


def _mia(request, pk):
    return get_object_or_404(TareaDesarrollo.objects.select_for_update(), pk=pk, usuario=request.user)


# Se borran solo las tareas cerradas: las activas siguen trabajando y las aplicadas aún se pueden deshacer.
BORRABLES = ('plan_listo', 'fallida', 'descartada', 'deshecha')


@api_view(['GET', 'DELETE'])
@permission_classes(PERMISOS)
def detalle(request, pk):
    t = get_object_or_404(TareaDesarrollo, pk=pk, usuario=request.user)
    if request.method == 'DELETE':
        if t.estado not in BORRABLES:
            return Response({'error': 'Esta tarea no se puede borrar ahora (está en curso o aplicada).'}, status=status.HTTP_409_CONFLICT)
        auditar(request.user, 'desarrollador.borrada', t, {'estado': t.estado})
        t.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(serializar(t))


@api_view(['POST'])
@permission_classes(PERMISOS)
@transaction.atomic
def aprobar(request, pk):
    t = _mia(request, pk)
    if t.estado != 'plan_listo':
        return Response({'error': 'Solo se aprueba un plan listo.'}, status=status.HTTP_409_CONFLICT)
    t.estado, t.aprobado_en = 'aprobada', timezone.now()
    evento(t, f'Plan aprobado por {request.user.first_name or request.user.username}.')
    t.save()
    auditar(request.user, 'desarrollador.aprobada', t, {'riesgo': t.plan.get('riesgo')})
    despertar()
    return Response(serializar(t))


@api_view(['POST'])
@permission_classes(PERMISOS)
@transaction.atomic
def ajustar(request, pk):
    t = _mia(request, pk)
    texto = str(request.data.get('texto') or '').strip()
    if t.estado != 'plan_listo':
        return Response({'error': 'Solo se ajusta un plan listo.'}, status=status.HTTP_409_CONFLICT)
    if not texto or len(texto) > 2000:
        return Response({'texto': 'Escribe qué ajustar (máximo 2000 caracteres).'}, status=status.HTTP_400_BAD_REQUEST)
    t.ajustes = [*t.ajustes, texto]
    t.estado = 'planificando'
    evento(t, 'Pediste ajustes al plan. Preparándolo de nuevo.')
    t.save()
    despertar()
    return Response(serializar(t))


@api_view(['POST'])
@permission_classes(PERMISOS)
@transaction.atomic
def descartar(request, pk):
    t = _mia(request, pk)
    if t.estado not in ('plan_listo', 'en_pruebas', 'fallida'):
        return Response({'error': 'Esta tarea no se puede descartar ahora.'}, status=status.HTTP_409_CONFLICT)
    # Si ya estaba en pruebas, el servicio vuelve la versión de pruebas a la de producción.
    if t.estado == 'en_pruebas':
        t.resultado = {**t.resultado, 'restaurar_pruebas': True}
    t.estado = 'descartada'
    evento(t, 'Descartada por el usuario.')
    t.save()
    auditar(request.user, 'desarrollador.descartada', t, {})
    despertar()
    return Response(serializar(t))


@api_view(['POST'])
@permission_classes(PERMISOS)
@transaction.atomic
def deshacer(request, pk):
    t = _mia(request, pk)
    if t.estado != 'aplicada':
        return Response({'error': 'Solo se deshace un cambio aplicado.'}, status=status.HTTP_409_CONFLICT)
    t.estado, t.error = 'deshaciendo', ''
    evento(t, 'Deshacer pedido por el usuario.')
    t.save()
    auditar(request.user, 'desarrollador.deshacer', t, {})
    despertar()
    return Response(serializar(t))


@api_view(['POST'])
@permission_classes(PERMISOS)
@transaction.atomic
def reintentar(request, pk):
    t = _mia(request, pk)
    if t.estado != 'fallida':
        return Response({'error': 'Solo se reintenta una tarea que falló.'}, status=status.HTTP_409_CONFLICT)
    t.estado, t.error = ('aprobada' if t.aprobado_en else 'planificando'), ''
    evento(t, 'Reintento pedido por el usuario.')
    t.save()
    despertar()
    return Response(serializar(t))


# --- Canal interno del servicio -------------------------------------------------------

@api_view(['POST'])
@authentication_classes([])
@permission_classes([TokenServicio])
def interno_latido(request):
    cache.set(CLAVE_LATIDO, timezone.now().isoformat(), 600)
    return Response({'ok': True})


@api_view(['GET'])
@authentication_classes([])
@permission_classes([TokenServicio])
def interno_pendientes(request):
    """Trabajo para el servicio: planes por preparar, implementaciones aprobadas, cambios por deshacer y
    descartes que deben devolver la versión de pruebas a producción."""
    trabajo = list(TareaDesarrollo.objects.filter(estado__in=TareaDesarrollo.ACTIVOS).order_by('id')[:20])
    trabajo += [t for t in TareaDesarrollo.objects.filter(estado='descartada').order_by('-id')[:20] if t.resultado.get('restaurar_pruebas')]
    return Response([{**serializar(t), 'usuario': t.usuario.first_name or t.usuario.username} for t in trabajo])


@api_view(['GET', 'PATCH'])
@authentication_classes([])
@permission_classes([TokenServicio])
@transaction.atomic
def interno_tarea(request, pk):
    t = get_object_or_404(TareaDesarrollo.objects.select_for_update(), pk=pk)
    if request.method == 'GET':
        return Response({**serializar(t), 'usuario': t.usuario.first_name or t.usuario.username})
    d = request.data
    anterior = t.estado
    nuevo = d.get('estado')
    if nuevo and nuevo != anterior:
        permitido = TRANSICIONES_SERVICIO.get(anterior, set())
        if nuevo not in permitido:
            return Response({'error': f'Transición no permitida: {anterior} → {nuevo}.'}, status=status.HTTP_409_CONFLICT)
        t.estado = nuevo
    for campo in ('plan', 'resultado'):
        if isinstance(d.get(campo), dict):
            setattr(t, campo, {**getattr(t, campo), **d[campo]})
    for campo, maximo in (('diff', 400000), ('vista_previa', 300), ('error', 8000), ('modelo', 60)):
        if campo in d:
            setattr(t, campo, str(d[campo] or '')[:maximo])
    if isinstance(d.get('tokens_suma'), int) and d['tokens_suma'] > 0:
        t.tokens += d['tokens_suma']
    for texto in (d.get('eventos') or [])[:30]:
        evento(t, texto)
    t.save()
    if t.estado != anterior and t.estado in AVISOS:
        transaction.on_commit(lambda: avisar(t))
    return Response(serializar(t))


def avisar(t):
    """Aviso por correo al usuario cuando hay algo que revisar (nunca falla la tarea)."""
    correo = t.usuario.email
    if not correo:
        return
    try:
        send_mail(f'Desarrollador IA · Tarea #{t.pk} {AVISOS[t.estado]}',
                  f'La tarea #{t.pk} «{t.pedido[:200]}» {AVISOS[t.estado]}.\n\nRevísala en IA Lottus → Desarrollador.',
                  None, [correo], fail_silently=True)
    except Exception:  # noqa: BLE001 — el aviso nunca interrumpe la tarea
        log.exception('No se pudo enviar el aviso del Desarrollador')
