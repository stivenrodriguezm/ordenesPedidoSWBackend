"""Programación y resultados personales de la oficina IA."""
import re
from datetime import time

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import (AutomatizacionAsistente, CustomUser, EjecucionAutomatizacionIA, PerfilAsistente,
                     InteraccionOficina, CursoAcademia, TrabajoAgenteIA)
from ..servicios import ErrorNegocio, auditar, idempotente
from . import automatizaciones as tareas
from .programacion import BOGOTA, siguiente
from .views import _exigir

MAX_TAREAS = 50
MAX_ACTIVAS = 20


class Entrada(serializers.ModelSerializer):
    perfil = serializers.PrimaryKeyRelatedField(queryset=PerfilAsistente.objects.filter(activo=True), allow_null=True, required=False)
    nombre = serializers.CharField(max_length=80, min_length=3, trim_whitespace=True)
    instrucciones = serializers.CharField(max_length=4000, min_length=20, trim_whitespace=True)
    hora = serializers.TimeField(default=time(9), input_formats=['%H:%M', '%H:%M:%S'])
    dia_mes = serializers.IntegerField(min_value=1, max_value=31, required=False)

    class Meta:
        model = AutomatizacionAsistente
        fields = ['perfil', 'nombre', 'instrucciones', 'modelo', 'frecuencia', 'hora', 'dias_semana', 'dia_mes', 'fecha_unica', 'fecha_fin', 'activa', 'archivada']

    def validate_modelo(self, value):
        if value and value not in settings.GEMINI_MODELOS:
            raise serializers.ValidationError('Selecciona un modelo disponible.')
        return value

    def validate_dias_semana(self, value):
        if not isinstance(value, list) or len(value) > 7 or any(type(d) is not int or d not in range(7) for d in value):
            raise serializers.ValidationError('Selecciona días válidos de lunes a domingo.')
        return sorted(set(value))

    def validate(self, attrs):
        def valor(campo, defecto=None):
            return attrs.get(campo, getattr(self.instance, campo, defecto))
        frecuencia = valor('frecuencia', 'semanal')
        if frecuencia == 'semanal' and not valor('dias_semana', []):
            raise serializers.ValidationError({'dias_semana': 'Selecciona al menos un día.'})
        if frecuencia == 'una_vez' and not valor('fecha_unica'):
            raise serializers.ValidationError({'fecha_unica': 'Selecciona fecha y hora.'})
        if valor('activa', True) and not valor('archivada', False):
            perfil = valor('perfil')
            general = (perfil is None) if 'perfil' in attrs or not self.instance else self.instance.es_general
            if not general and (not perfil or not perfil.activo):
                raise serializers.ValidationError({'perfil': 'Selecciona un agente activo para reactivar la tarea.'})
            hoy = timezone.now().astimezone(BOGOTA).date()
            if valor('fecha_fin') and valor('fecha_fin') < hoy:
                raise serializers.ValidationError({'fecha_fin': 'La fecha límite ya pasó.'})
            if frecuencia == 'una_vez' and valor('fecha_unica') <= timezone.now():
                raise serializers.ValidationError({'fecha_unica': 'El horario debe estar en el futuro.'})
            if frecuencia == 'una_vez' and valor('fecha_fin') and valor('fecha_unica').astimezone(BOGOTA).date() > valor('fecha_fin'):
                raise serializers.ValidationError({'fecha_fin': 'La tarea está programada después de la fecha límite.'})
        return attrs


def _ejecucion(e, completa=False):
    return {'id': e.pk, 'automatizacion': e.automatizacion_id, 'nombre': e.nombre, 'perfil': e.perfil_id_original,
        'perfil_nombre': e.perfil_nombre, 'es_general': e.es_general, 'estado': e.estado, 'origen': e.origen,
        'programada_para': e.programada_para, 'creada': e.creada, 'iniciada': e.iniciada, 'finalizada': e.finalizada,
        'conversacion': e.conversacion_id, 'leida': e.leida, 'error': e.error, 'modelo': e.modelo_usado,
        'resultado': e.resultado if completa else e.resultado[:300]}


def _datos(qs):
    ultima = EjecucionAutomatizacionIA.objects.filter(automatizacion_id=OuterRef('pk')).order_by('-creada', '-id')
    lista = list(qs.select_related('perfil').annotate(ultima_id=Subquery(ultima.values('pk')[:1]),
        en_curso=Count('ejecuciones', filter=Q(ejecuciones__estado__in=['pendiente', 'ejecutando'])),
        sin_leer=Count('ejecuciones', filter=Q(ejecuciones__estado__in=['listo', 'error'], ejecuciones__leida=False))))
    ultimas = {e.pk:e for e in EjecucionAutomatizacionIA.objects.filter(pk__in=[a.ultima_id for a in lista if a.ultima_id])}
    return [{'id': a.pk, 'perfil': a.perfil_id, 'es_general': a.es_general, 'perfil_nombre': a.perfil_nombre,
        'agente_disponible': a.es_general or bool(a.perfil and a.perfil.activo), 'nombre': a.nombre,
        'instrucciones': a.instrucciones, 'modelo': a.modelo, 'frecuencia': a.frecuencia, 'hora': a.hora,
        'dias_semana': a.dias_semana, 'dia_mes': a.dia_mes, 'fecha_unica': a.fecha_unica, 'fecha_fin': a.fecha_fin,
        'activa': a.activa, 'archivada': a.archivada, 'proxima_ejecucion': a.proxima_ejecucion,
        'en_curso': a.en_curso, 'sin_leer': a.sin_leer,
        'ultima': _ejecucion(ultimas[a.ultima_id]) if a.ultima_id in ultimas else None} for a in lista]


def _limite(usuario, excepto=None, activa=False):
    CustomUser.objects.select_for_update().get(pk=usuario.pk)
    qs = AutomatizacionAsistente.objects.filter(usuario=usuario, archivada=False)
    if excepto:
        qs = qs.exclude(pk=excepto)
    if not excepto and qs.count() >= MAX_TAREAS:
        raise ErrorNegocio('Puedes conservar hasta 50 automatizaciones sin archivar.')
    if activa and qs.filter(activa=True).count() >= MAX_ACTIVAS:
        raise ErrorNegocio('Puedes tener hasta 20 automatizaciones activas. Pausa alguna para activar otra.')


@idempotente('asistente.automatizacion_creada')
def _crear(request):
    entrada = Entrada(data=request.data)
    entrada.is_valid(raise_exception=True)
    with transaction.atomic():
        _limite(request.user, activa=entrada.validated_data.get('activa', True) and not entrada.validated_data.get('archivada'))
        perfil = entrada.validated_data.get('perfil')
        a = entrada.save(usuario=request.user, es_general=perfil is None, perfil_nombre=perfil.nombre if perfil else 'IA Lottus')
        if a.archivada:
            a.activa = False
        a.proxima_ejecucion = siguiente(a, timezone.now())
        if a.activa and a.proxima_ejecucion is None:
            raise serializers.ValidationError({'fecha_fin': 'No queda ningún horario futuro dentro del período elegido.'})
        a.save(update_fields=['proxima_ejecucion', 'activa'])
        auditar(request.user, 'asistente.automatizacion_creada', a, {'perfil': a.perfil_id, 'frecuencia': a.frecuencia})
        return Response(_datos(AutomatizacionAsistente.objects.filter(pk=a.pk))[0], status=201)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def lista(request):
    _exigir(request, gestionar=request.method == 'POST')
    if request.method == 'POST':
        return _crear(request)
    qs = AutomatizacionAsistente.objects.filter(usuario=request.user)
    if request.query_params.get('archivadas') != '1':
        qs = qs.filter(archivada=False)
    perfil = request.query_params.get('perfil')
    if perfil == 'general':
        qs = qs.filter(es_general=True)
    elif perfil:
        try:
            qs = qs.filter(perfil_id=int(perfil), es_general=False)
        except ValueError:
            raise ErrorNegocio('Agente inválido.')
    return Response({'automatizaciones': _datos(qs), 'motor': tareas.motor(),
        'puede_programar': tareas.puede_programar(request.user), 'limites': {'activas': MAX_ACTIVAS, 'conservadas': MAX_TAREAS}})


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def detalle(request, pk):
    _exigir(request, gestionar=request.method != 'GET')
    if request.method == 'GET':
        a = get_object_or_404(AutomatizacionAsistente, pk=pk, usuario=request.user)
        return Response(_datos(AutomatizacionAsistente.objects.filter(pk=a.pk))[0])
    with transaction.atomic():
        # El límite de tareas también debe serializar altas y restauraciones.
        CustomUser.objects.select_for_update().get(pk=request.user.pk)
        a = get_object_or_404(AutomatizacionAsistente.objects.select_for_update(), pk=pk, usuario=request.user)
        datos = request.data.copy()
        if a.archivada and datos.get('archivada') is False:
            datos['activa'] = False
        entrada = Entrada(a, data=datos, partial=True)
        entrada.is_valid(raise_exception=True)
        campos = entrada.validated_data
        if a.archivada and campos.get('archivada') is False:
            # Restaurar siempre pausada; el usuario decide cuándo activar.
            campos['activa'] = False
            if AutomatizacionAsistente.objects.filter(usuario=request.user, archivada=False).count() >= MAX_TAREAS:
                raise ErrorNegocio('Archiva otra tarea antes de restaurar esta.')
        activa = campos.get('activa', a.activa) and not campos.get('archivada', a.archivada)
        _limite(request.user, excepto=a.pk, activa=activa)
        a = entrada.save()
        if 'perfil' in campos:
            a.es_general = a.perfil is None
            a.perfil_nombre = a.perfil.nombre if a.perfil else 'IA Lottus'
        if a.archivada:
            a.activa = False
        if set(campos) & {'frecuencia', 'hora', 'dias_semana', 'dia_mes', 'fecha_unica', 'fecha_fin', 'activa', 'archivada'}:
            a.proxima_ejecucion = siguiente(a, timezone.now())
            if a.activa and a.proxima_ejecucion is None:
                raise serializers.ValidationError({'fecha_fin': 'No queda ningún horario futuro dentro del período elegido.'})
        a.save()
        auditar(request.user, 'asistente.automatizacion_editada', a, {'campos': sorted(campos)})
    return Response(_datos(AutomatizacionAsistente.objects.filter(pk=pk))[0])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ejecutar_ahora(request, pk):
    _exigir(request, gestionar=True)
    clave = request.headers.get('Idempotency-Key', '')
    if not re.fullmatch(r'[A-Za-z0-9._:-]{8,100}', clave):
        raise ErrorNegocio('La ejecución necesita una clave de intento válida. Actualiza la página e intenta de nuevo.')
    # Reintento HTTP recupera la misma ejecución, incluso si el motor la terminó.
    e = tareas.reservar(pk, usuario_id=request.user.pk, clave=clave)
    return Response(_ejecucion(e), status=202)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def historial(request, pk):
    _exigir(request)
    a = get_object_or_404(AutomatizacionAsistente, pk=pk, usuario=request.user)
    try:
        offset = int(request.query_params.get('offset', 0))
        if offset < 0:
            raise ValueError
    except ValueError:
        raise ErrorNegocio('Paginación inválida.')
    resultados = list(a.ejecuciones.all()[offset:offset+31])
    return Response({'resultados': [_ejecucion(e) for e in resultados[:30]],
        'siguiente': offset+30 if len(resultados) > 30 else None})


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def ejecucion(request, pk):
    _exigir(request)
    e = get_object_or_404(EjecucionAutomatizacionIA, pk=pk, automatizacion__usuario=request.user)
    if request.method == 'PATCH':
        if request.data.get('leida') is not True:
            raise ErrorNegocio('Solo puedes marcar esta ejecución como leída.')
        e.leida = True
        e.save(update_fields=['leida'])
    return Response(_ejecucion(e, completa=True))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def actividad(request):
    _exigir(request)
    tareas_propias = _datos(AutomatizacionAsistente.objects.filter(usuario=request.user, archivada=False))
    pendientes = list(EjecucionAutomatizacionIA.objects.filter(automatizacion__usuario=request.user,
        estado__in=['listo', 'error'], leida=False).order_by('-creada', '-id')[:100])
    en_curso = list(EjecucionAutomatizacionIA.objects.filter(automatizacion__usuario=request.user,
        estado__in=['pendiente', 'ejecutando']).order_by('creada', 'id')[:50])
    # El plano compartido conoce el estado, nunca el contenido de otra persona.
    visibles = [p.pk for p in PerfilAsistente.objects.filter(activo=True) if tareas_perfil_visible(p, request.user)]
    trabajando = list(EjecucionAutomatizacionIA.objects.filter(estado='ejecutando').filter(
        Q(perfil_id_original__in=visibles)|Q(es_general=True)).values('perfil_id_original','es_general').distinct())
    trabajando_agente = list(TrabajoAgenteIA.objects.filter(estado='ejecutando',agente_id__in=visibles).values_list('agente_id',flat=True).distinct())
    dialogos = InteraccionOficina.objects.filter(tipo='dialogo', conversacion__usuario=request.user,
        conversacion__perfil_id__in=visibles).select_related('conversacion__perfil').order_by('-id')[:30]
    iniciativas = [{'id':e.pk, 'perfil':e.conversacion.perfil_id, 'conversacion':e.conversacion_id,
        'creado':e.creado, 'texto':e.conversacion.mensajes.filter(rol='asistente').values_list('texto',flat=True).first()}
        for e in dialogos if not e.conversacion.mensajes.filter(rol='usuario').exists()]
    cursos = [{'id':c.pk, 'perfil':c.perfil_id, 'estado':c.estado, 'detalle':c.detalle, 'avance':c.avance, 'titulo':c.titulo}
        for c in CursoAcademia.objects.filter(usuario=request.user, estado__in=['pendiente','trabajando','generando','esperando_video'])[:10]]
    return Response({'motor': tareas.motor(), 'puede_programar': tareas.puede_programar(request.user),
        'automatizaciones': tareas_propias, 'pendientes': [_ejecucion(e) for e in pendientes],
        'en_curso': [_ejecucion(e) for e in en_curso], 'iniciativas':iniciativas, 'cursos':cursos,
        'trabajando': [{'perfil':None if x['es_general'] else x['perfil_id_original']} for x in trabajando]+[{'perfil':pk} for pk in trabajando_agente]})


def tareas_perfil_visible(perfil, usuario):
    from .perfiles import visible_para
    return visible_para(perfil, usuario)
