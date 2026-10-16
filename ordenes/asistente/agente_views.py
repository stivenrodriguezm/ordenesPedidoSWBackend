from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from ..models import TrabajoAgenteIA, MensajeAsistente
from . import agente
from .views import _exigir


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def trabajos(request):
    _exigir(request)
    qs = TrabajoAgenteIA.objects.filter(usuario=request.user,continuacion_de__isnull=True).select_related('agente')[:30]
    return Response({'trabajos':[agente.representar(t,False) for t in qs]})


@api_view(['GET','POST'])
@permission_classes([IsAuthenticated])
def trabajo(request,pk):
    _exigir(request)
    t = get_object_or_404(TrabajoAgenteIA,pk=pk,usuario=request.user)
    t = agente.principal(t)
    if request.method == 'POST':
        if request.data.get('accion') != 'retomar' or t.estado not in ('error','necesita_datos'):
            raise ValidationError('Solo se retoman ejecuciones que requieren revisión o datos.')
        cambios = request.data.get('datos_adicionales','')
        if not isinstance(cambios,str) or len(cambios)>4000:
            raise ValidationError('Los datos adicionales deben ser texto de hasta 4.000 caracteres.')
        from django.db import transaction
        with transaction.atomic():
            t = TrabajoAgenteIA.objects.select_for_update().get(pk=t.pk)
            if t.estado not in ('error','necesita_datos'):
                raise ValidationError('Esta ejecución ya cambió de estado.')
            contexto = t.contexto_usuario or agente.contexto_humano(t.origen)
            if cambios.strip():
                c = t.conversacion or t.origen.conversacion
                m = MensajeAsistente.objects.create(conversacion=c,rol='usuario',texto=cambios.strip())
                contexto = contexto+[{'mensaje_id':m.pk,'texto':m.texto}]
            t = agente.retomar(t,contexto)
    return Response(agente.representar(t))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def equipo_hilos(request):
    """Conversaciones entre agentes originadas por las solicitudes de este usuario."""
    _exigir(request)
    from ..permissions import tiene_permiso_codigo
    from . import equipo
    return Response({'hilos': equipo.hilos(request.user, tiene_permiso_codigo(request, 'GESTIONAR_PERFILES_IA'))})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def equipo_hilo(request, clave):
    _exigir(request)
    from django.http import Http404
    from ..permissions import tiene_permiso_codigo
    from . import equipo
    datos = equipo.mensajes(request.user, clave, tiene_permiso_codigo(request, 'GESTIONAR_PERFILES_IA'))
    if datos is None:
        raise Http404
    return Response(datos)
