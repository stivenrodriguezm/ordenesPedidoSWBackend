"""Oficina humana: invitación explícita, comunicación y coordinación sin IA.

Seleccionar una persona no amplía sus permisos comerciales. Los chats privados
no son visibles para el responsable salvo que participe en ellos.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (ConfiguracionOficina, MiembroOficina, MensajeOficina, TrabajoOficina,
                     ComentarioTrabajoOficina, CustomUser, ZonaOficinaIA, PerfilAsistente, Venta)
from .permissions import tiene_permiso_codigo, ventas_visibles, filtro_ventas_propias
from .servicios import ErrorNegocio, auditar

CAPACIDADES = {'gerencia':3,'showroom':7,'entrenamiento':1,'social':3}
ABIERTOS = ['pendiente','en_curso','bloqueada']


def acceso_oficina(usuario):
    if not usuario.is_active:
        return False
    return usuario.role == 'administrador' or MiembroOficina.objects.filter(usuario=usuario,habilitado=True).exists()


def _contexto(request, miembro=False, gestionar=False):
    if not request.user.is_active:
        raise PermissionDenied('Tu usuario está inactivo.')
    config = ConfiguracionOficina.objects.select_related('responsable').filter(pk=1).first()
    gestor = request.user.pk == config.responsable_id if config else request.user.role == 'administrador'
    persona = MiembroOficina.objects.filter(usuario=request.user,habilitado=True).first()
    if gestionar and not gestor:
        raise PermissionDenied('Solo el responsable de la oficina puede gestionar personas.')
    if miembro and not (persona or gestor):
        raise PermissionDenied('Aún no estás incluido en el equipo de esta oficina.')
    if not (persona or gestor or tiene_permiso_codigo(request,'USAR_ASISTENTE_IA')):
        raise PermissionDenied('No tienes acceso a la oficina.')
    return config, gestor, persona


def _bloquear(request):
    # Mismo orden en todas las escrituras; retirar un participante invalida
    # las operaciones que estuvieran esperando antes de escribir datos.
    config=ConfiguracionOficina.objects.select_for_update().filter(pk=1).first()
    if not config:raise ValidationError('Primero configura el equipo humano de la oficina.')
    usuario=CustomUser.objects.select_for_update().get(pk=request.user.pk)
    if not usuario.is_active:raise PermissionDenied('Tu usuario está inactivo.')
    request.user=usuario
    return _contexto(request,miembro=True)


def _usuario(u):
    return {'id':u.pk,'nombre':u.get_full_name().strip() or u.username,'rol':u.get_role_display()}


def _miembros():
    return MiembroOficina.objects.filter(habilitado=True,usuario__is_active=True).select_related('usuario','zona').order_by('usuario__first_name','usuario_id')


def _destino(config, pk):
    if config and pk == config.responsable_id and config.responsable.is_active:
        return config.responsable
    return get_object_or_404(CustomUser,pk=pk,is_active=True,membresia_oficina__habilitado=True)


def _venta_permitida(request, ids):
    if not tiene_permiso_codigo(request,'VER_VENTAS'):
        return set()
    return set(ventas_visibles(request).filter(pk__in=ids).values_list('pk',flat=True))


def _offset(request):
    try:
        n=int(request.query_params.get('offset',0))
    except (TypeError,ValueError):
        raise ValidationError('Paginación inválida.')
    if not 0 <= n <= 10000:
        raise ValidationError('Paginación inválida.')
    return n


def _estricto(datos, permitidos):
    if set(datos)-set(permitidos):
        raise ValidationError('Hay campos que no se pueden modificar en esta operación.')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def estado(request):
    config, gestor, yo = _contexto(request)
    equipo = list(_miembros()) if gestor or yo else []
    ids=[m.usuario_id for m in equipo]
    trabajos=TrabajoOficina.objects.filter(estado__in=ABIERTOS)
    if not gestor:
        trabajos=trabajos.filter(Q(creador=request.user)|Q(responsable=request.user))
    pendientes=dict(trabajos.values('responsable_id').annotate(n=Count('pk')).values_list('responsable_id','n'))
    actividades={}
    for t in trabajos.order_by('-actualizado','-id').values('responsable_id','id','titulo','estado','prioridad','fecha_limite'):
        lista=actividades.setdefault(t['responsable_id'],[])
        if len(lista)<3:lista.append({k:v for k,v in t.items() if k!='responsable_id'})
    ahora=timezone.now()
    # Mensajes privados sin leer por remitente: la oficina los muestra sobre quien escribió.
    sin_leer=dict(MensajeOficina.objects.filter(destinatario=request.user,archivado=False,leido_en__isnull=True)
                  .values('autor_id').annotate(n=Count('pk')).values_list('autor_id','n')) if gestor or yo else {}
    destacados={m.autor_id:m for m in MensajeOficina.objects.filter(autor_id__in=ids,destinatario__isnull=True,archivado=False,destacado_hasta__gt=ahora).select_related('autor').order_by('id')}
    personas=[]
    for m in equipo:
        d={**_usuario(m.usuario),'zona':m.zona_id,'puesto':m.puesto,'estado':m.estado,'nota_estado':m.nota_estado,
           'en_oficina':bool(m.ultima_presencia and m.ultima_presencia > ahora-timedelta(minutes=2)),
           'pendientes':pendientes.get(m.usuario_id,0) if gestor or m.usuario_id==request.user.pk else None,
           'trabajos':actividades.get(m.usuario_id,[]) if gestor or m.usuario_id==request.user.pk else [],
           'ultima_presencia':m.ultima_presencia,
           'destacado':_mensaje(destacados[m.usuario_id]) if m.usuario_id in destacados else None,
           'mensajes_para_mi':sin_leer.get(m.usuario_id,0)}
        personas.append(d)
    from .coordinacion import gerentes
    return Response({'yo':_usuario(request.user),'responsable':_usuario(config.responsable) if config else None,
        'gerentes':[_usuario(u) for u in gerentes()],
        'puede_gestionar':gestor,'participa':bool(yo or (config and gestor)),'puede_usar_ia':tiene_permiso_codigo(request,'USAR_ASISTENTE_IA'),
        'revision':config.revision if config else 0,'personas':personas,
        'zonas':list(ZonaOficinaIA.objects.values('id','nombre','descripcion','ambiente')),
        'mis_pendientes':trabajos.filter(responsable=request.user).count() if gestor or yo else 0,
        'mensajes_sin_leer':sum(sin_leer.values()),
        # Remitentes fuera del plano (p. ej. el responsable sin puesto): para avisar igual.
        'mensajes_de':[{'id':pk,'cantidad':n} for pk,n in sin_leer.items()]})


class PersonaEntrada(serializers.Serializer):
    usuario=serializers.IntegerField(min_value=1)
    zona=serializers.IntegerField(min_value=1,allow_null=True,required=False,default=None)
    puesto=serializers.IntegerField(min_value=0,max_value=6,allow_null=True,required=False,default=None)


class EquipoEntrada(serializers.Serializer):
    revision=serializers.IntegerField(min_value=0)
    personas=PersonaEntrada(many=True,allow_empty=True)


@api_view(['GET','PUT'])
@permission_classes([IsAuthenticated])
def equipo(request):
    config, _, _ = _contexto(request,gestionar=True)
    if request.method=='GET':
        return Response({'revision':config.revision if config else 0,'responsable':_usuario(config.responsable) if config else None,'personas':[
            {**_usuario(u),'seleccionado':bool(getattr(u,'membresia_oficina',None) and u.membresia_oficina.habilitado),
             'zona':getattr(getattr(u,'membresia_oficina',None),'zona_id',None),
             'puesto':getattr(getattr(u,'membresia_oficina',None),'puesto',None)}
            for u in CustomUser.objects.filter(is_active=True).select_related('membresia_oficina').order_by('first_name','id')]})
    _estricto(request.data,['revision','personas'])
    s=EquipoEntrada(data=request.data);s.is_valid(raise_exception=True)
    datos=s.validated_data;personas=datos['personas']
    if len(personas)>80 or len({p['usuario'] for p in personas})!=len(personas):
        raise ValidationError('Selecciona hasta 80 usuarios distintos.')
    if CustomUser.objects.filter(pk__in=[p['usuario'] for p in personas],is_active=True).count()!=len(personas):
        raise ValidationError('Solo se pueden incluir usuarios activos existentes.')
    zonas={z.pk:z for z in ZonaOficinaIA.objects.all()}
    reservados={}
    general=next((z for z in zonas.values() if z.ambiente=='gerencia'),next(iter(zonas.values()),None))
    for perfil in PerfilAsistente.objects.filter(activo=True,zona__isnull=False):
        reservados[perfil.zona_id]=reservados.get(perfil.zona_id,0)+1
    if general:reservados[general.pk]=reservados.get(general.pk,0)+1
    ocupados={z:set(range(min(reservados.get(z,0),CAPACIDADES.get(v.ambiente,2)))) for z,v in zonas.items()}
    # Asignaciones explícitas primero; el automático respeta los puestos elegidos.
    for p in sorted(personas,key=lambda p:p['puesto'] is None):
        zona=zonas.get(p['zona']) if p['zona'] else None
        if p['zona'] and not zona:raise ValidationError('La zona elegida no existe.')
        if not zona:
            if p['puesto'] is not None:raise ValidationError('Un puesto requiere una zona.')
            continue
        capacidad=CAPACIDADES.get(zona.ambiente,2)
        if p['puesto'] is None:p['puesto']=next((n for n in range(capacidad) if n not in ocupados[zona.pk]),None)
        if p['puesto'] is None or p['puesto']>=capacidad or p['puesto'] in ocupados[zona.pk]:
            raise ValidationError(f'No queda libre ese puesto en {zona.nombre}. Elige otro o deja a la persona sin ubicación.')
        ocupados[zona.pk].add(p['puesto'])
    with transaction.atomic():
        ConfiguracionOficina.objects.get_or_create(pk=1,defaults={'responsable':request.user,'revision':0})
        config=ConfiguracionOficina.objects.select_for_update().get(pk=1)
        if config.responsable_id!=request.user.pk:raise PermissionDenied('La oficina ya tiene otro responsable.')
        if config.revision!=datos['revision']:raise ErrorNegocio('El equipo cambió. Recarga antes de guardar.',409)
        usuarios=list(CustomUser.objects.select_for_update().filter(pk__in=[request.user.pk]+[p['usuario'] for p in personas]))
        if any(not u.is_active for u in usuarios):raise ValidationError('Solo se pueden incluir usuarios activos existentes.')
        # Eliminar las reservas antiguas antes de reubicar: permite intercambiar puestos.
        MiembroOficina.objects.update(habilitado=False,puesto=None,ultima_presencia=None)
        for p in personas:
            MiembroOficina.objects.update_or_create(usuario_id=p['usuario'],defaults={'habilitado':True,'zona_id':p['zona'],'puesto':p['puesto']})
        config.revision+=1;config.save(update_fields=['revision'])
        auditar(request.user,'oficina.equipo',config,{'usuarios':[p['usuario'] for p in personas]})
    return Response({'revision':config.revision})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def presencia(request):
    _,_,yo=_contexto(request,miembro=True)
    if not yo:return Response({'en_oficina':False})
    _estricto(request.data,['estado','nota_estado'])
    datos={}
    if 'estado' in request.data:
        if request.data['estado'] not in ['disponible','ocupado','ausente']:raise ValidationError('Estado inválido.')
        datos['estado']=request.data['estado']
    if 'nota_estado' in request.data:
        texto=request.data['nota_estado']
        if not isinstance(texto,str) or len(texto)>100:raise ValidationError('La nota admite hasta 100 caracteres.')
        datos['nota_estado']=texto.strip()
    with transaction.atomic():
        _bloquear(request)
        MiembroOficina.objects.filter(pk=yo.pk,habilitado=True).update(ultima_presencia=timezone.now(),**datos)
    return Response({'en_oficina':True})


def _mensaje(m):
    return {'id':m.pk,'autor':_usuario(m.autor),'destinatario':m.destinatario_id,'texto':m.texto,
        'destacado_hasta':m.destacado_hasta,'leido_en':m.leido_en,'creado':m.creado,'archivado':m.archivado}


class MensajeEntrada(serializers.Serializer):
    texto=serializers.CharField(max_length=2000,trim_whitespace=True)
    destinatario=serializers.IntegerField(min_value=1,allow_null=True,required=False,default=None)
    destacar=serializers.BooleanField(required=False,default=False)
    horas=serializers.ChoiceField(choices=[1,4,24],required=False,default=24)


@api_view(['GET','POST'])
@permission_classes([IsAuthenticated])
def mensajes(request):
    config,_,_=_contexto(request,miembro=True)
    if request.method=='GET':
        qs=MensajeOficina.objects.filter(archivado=False).select_related('autor')
        para=request.query_params.get('para','equipo')
        if para=='equipo':qs=qs.filter(destinatario__isnull=True)
        else:
            try:pk=int(para)
            except (TypeError,ValueError):raise ValidationError('Destinatario inválido.')
            qs=qs.filter(Q(autor=request.user,destinatario_id=pk)|Q(autor_id=pk,destinatario=request.user))
        offset=_offset(request);items=list(qs[offset:offset+51])
        return Response({'resultados':[_mensaje(m) for m in items[:50]],'hay_mas':len(items)>50})
    _estricto(request.data,['texto','destinatario','destacar','horas'])
    s=MensajeEntrada(data=request.data);s.is_valid(raise_exception=True);d=s.validated_data
    destino=_destino(config,d['destinatario']) if d['destinatario'] else None
    if destino and destino.pk==request.user.pk:raise ValidationError('Para anotar algo propio, crea una tarea personal.')
    if destino and d['destacar']:raise ValidationError('Solo los mensajes al equipo se destacan públicamente en la oficina.')
    with transaction.atomic():
        _bloquear(request)
        if destino:destino=_destino(config,destino.pk)
        if MensajeOficina.objects.filter(autor=request.user,creado__gt=timezone.now()-timedelta(hours=1)).count()>=120:
            raise ErrorNegocio('Alcanzaste 120 mensajes en una hora. Intenta más tarde.',429)
        hasta=timezone.now()+timedelta(hours=d['horas']) if d['destacar'] else None
        if hasta:MensajeOficina.objects.filter(autor=request.user,destacado_hasta__isnull=False).update(destacado_hasta=None)
        m=MensajeOficina.objects.create(autor=request.user,destinatario=destino,texto=d['texto'],destacado_hasta=hasta)
    return Response(_mensaje(m),status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def conversaciones(request):
    """Bandeja de chats: el tablón del equipo y cada conversación privada que ha tenido el
    usuario, con el último mensaje y los no leídos (las más recientes primero)."""
    _contexto(request,miembro=True)
    yo=request.user
    privados=MensajeOficina.objects.filter(Q(autor=yo,destinatario__isnull=False)|Q(destinatario=yo),archivado=False)
    ultimos={}
    for m in privados.select_related('autor','destinatario').order_by('-id')[:2000]:
        otro=m.destinatario if m.autor_id==yo.pk else m.autor
        ultimos.setdefault(otro.pk,(otro,m))
    sin_leer=dict(privados.filter(destinatario=yo,leido_en__isnull=True).values('autor_id').annotate(n=Count('pk')).values_list('autor_id','n'))
    chats=[{'para':str(pk),'persona':_usuario(otro),'ultimo':_mensaje(m),'sin_leer':sin_leer.get(pk,0)}
           for pk,(otro,m) in ultimos.items()]
    equipo=MensajeOficina.objects.filter(destinatario__isnull=True,archivado=False).select_related('autor').order_by('-id').first()
    chats.append({'para':'equipo','persona':None,'ultimo':_mensaje(equipo) if equipo else None,'sin_leer':0})
    chats.sort(key=lambda c:c['ultimo']['id'] if c['ultimo'] else 0,reverse=True)
    return Response({'resultados':chats})


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def mensaje(request,pk):
    _,gestor,_=_contexto(request,miembro=True)
    _estricto(request.data,['archivado','destacar','horas'])
    with transaction.atomic():
        _bloquear(request)
        m=get_object_or_404(MensajeOficina.objects.select_for_update().select_related('autor'),pk=pk)
        if not (m.autor_id==request.user.pk or (gestor and m.destinatario_id is None)):
            raise PermissionDenied('Solo puedes cambiar tus mensajes.')
        if 'archivado' in request.data:
            campo=serializers.BooleanField();m.archivado=campo.run_validation(request.data['archivado'])
        if 'destacar' in request.data:
            if m.autor_id!=request.user.pk or m.destinatario_id is not None or m.archivado:
                raise ValidationError('Solo puedes destacar tus mensajes visibles del equipo.')
            marcar=serializers.BooleanField().run_validation(request.data['destacar'])
            horas=serializers.ChoiceField(choices=[1,4,24]).run_validation(request.data.get('horas',24))
            MensajeOficina.objects.filter(autor=request.user).exclude(pk=m.pk).update(destacado_hasta=None)
            m.destacado_hasta=timezone.now()+timedelta(hours=horas) if marcar else None
        if m.archivado:m.destacado_hasta=None
        m.save(update_fields=['archivado','destacado_hasta'])
    return Response(_mensaje(m))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def leer_mensajes(request):
    _contexto(request,miembro=True)
    s=serializers.ListField(child=serializers.IntegerField(min_value=1),max_length=50)
    ids=s.run_validation(request.data.get('ids',[]))
    with transaction.atomic():
        _bloquear(request)
        n=MensajeOficina.objects.filter(pk__in=ids,destinatario=request.user,leido_en__isnull=True).update(leido_en=timezone.now())
    return Response({'marcados':n})


def _trabajos(request,gestor):
    qs=TrabajoOficina.objects.select_related('creador','responsable')
    return qs if gestor else qs.filter(Q(creador=request.user)|Q(responsable=request.user))


def _trabajo(t,permitidas):
    return {'id':t.pk,'tipo':t.tipo,'creador':_usuario(t.creador),'responsable':_usuario(t.responsable),'titulo':t.titulo,
        'descripcion':t.descripcion,'prioridad':t.prioridad,'estado':t.estado,'fecha_limite':t.fecha_limite,
        'venta':t.venta_id if t.venta_id in permitidas else None,'revision':t.revision,'creado':t.creado,'actualizado':t.actualizado}


class TrabajoEntrada(serializers.Serializer):
    tipo=serializers.ChoiceField(choices=['tarea','solicitud'])
    titulo=serializers.CharField(max_length=140,trim_whitespace=True)
    descripcion=serializers.CharField(max_length=3000,required=False,allow_blank=True,default='')
    responsable=serializers.IntegerField(min_value=1,required=False,allow_null=True,default=None)
    prioridad=serializers.ChoiceField(choices=['normal','alta'],required=False,default='normal')
    fecha_limite=serializers.DateField(required=False,allow_null=True,default=None)
    venta=serializers.IntegerField(min_value=1,required=False,allow_null=True,default=None)


def _validar_venta(request,venta,usuario):
    if venta is None:return
    destino=SimpleNamespace(user=usuario)
    if venta not in _venta_permitida(request,[venta]) or venta not in _venta_permitida(destino,[venta]):
        raise ValidationError('La venta debe ser visible para ti y para quien recibe la tarea.')


@api_view(['GET','POST'])
@permission_classes([IsAuthenticated])
def trabajos(request):
    config,gestor,_=_contexto(request,miembro=True)
    if request.method=='GET':
        qs=_trabajos(request,gestor)
        persona=request.query_params.get('persona')
        if persona:
            try:pk=int(persona)
            except (TypeError,ValueError):raise ValidationError('Persona inválida.')
            qs=qs.filter(Q(creador_id=pk)|Q(responsable_id=pk))
        offset=_offset(request);items=list(qs[offset:offset+51]);items50=items[:50]
        permitidas=_venta_permitida(request,[t.venta_id for t in items50 if t.venta_id])
        return Response({'resultados':[_trabajo(t,permitidas) for t in items50],'hay_mas':len(items)>50})
    _estricto(request.data,TrabajoEntrada().fields)
    s=TrabajoEntrada(data=request.data);s.is_valid(raise_exception=True);d=s.validated_data
    if not config:raise ValidationError('Primero configura el equipo humano de la oficina.')
    from .coordinacion import gerentes
    destinatarios = gerentes()
    if d['tipo']=='solicitud':
        if d['responsable'] and destinatarios.exists():
            responsable=get_object_or_404(destinatarios,pk=d['responsable'])
        else:responsable=config.responsable
    else:responsable=_destino(config,d['responsable'] or request.user.pk)
    if d['tipo']=='tarea' and responsable.pk!=request.user.pk and not gestor:
        raise PermissionDenied('Solo el responsable asigna tareas a otras personas. Puedes crear una tarea propia o una solicitud.')
    _validar_venta(request,d['venta'],responsable)
    with transaction.atomic():
        _bloquear(request)
        responsable=_destino(config,responsable.pk)
        _validar_venta(request,d['venta'],responsable)
        if TrabajoOficina.objects.filter(creador=request.user,estado__in=ABIERTOS).count()>=100:
            raise ValidationError('Tienes 100 trabajos abiertos. Cierra algunos antes de crear otro.')
        t=TrabajoOficina.objects.create(creador=request.user,responsable=responsable,tipo=d['tipo'],titulo=d['titulo'],
            descripcion=d['descripcion'],prioridad=d['prioridad'],fecha_limite=d['fecha_limite'],venta_id=d['venta'])
        if t.creador_id!=t.responsable_id and destinatarios.filter(pk=t.responsable_id).exists():
            from .models import InteraccionOficina
            InteraccionOficina.objects.create(actor=f'persona-{t.creador_id}',destino=f'persona-{t.responsable_id}',
                tipo='solicitud',texto='Traigo una solicitud de trabajo',trabajo=t)
        auditar(request.user,'oficina.trabajo.crear',t,{'tipo':t.tipo,'responsable':t.responsable_id})
    return Response(_trabajo(t,_venta_permitida(request,[t.venta_id])),status=201)


@api_view(['GET','PATCH'])
@permission_classes([IsAuthenticated])
def trabajo(request,pk):
    config,gestor,_=_contexto(request,miembro=True)
    if request.method=='PATCH':
        _estricto(request.data,['revision','estado','responsable'])
        revision=serializers.IntegerField(min_value=1).run_validation(request.data.get('revision'))
        with transaction.atomic():
            _bloquear(request)
            t=get_object_or_404(_trabajos(request,gestor).select_for_update(),pk=pk)
            if revision!=t.revision:raise ErrorNegocio('Este trabajo cambió. Recárgalo antes de guardar.',409)
            antes=t.estado
            if 'responsable' in request.data:
                if not gestor or t.tipo!='tarea':raise PermissionDenied('Solo el responsable de oficina reasigna tareas.')
                id_destino=serializers.IntegerField(min_value=1).run_validation(request.data['responsable'])
                u=_destino(config,id_destino);_validar_venta(request,t.venta_id,u);t.responsable=u
            if 'estado' in request.data:
                nuevo=serializers.ChoiceField(choices=[s[0] for s in TrabajoOficina._meta.get_field('estado').choices]).run_validation(request.data['estado'])
                ejecutor=gestor or t.responsable_id==request.user.pk
                if not ejecutor and not (t.creador_id==request.user.pk and (nuevo=='cancelada' or (nuevo=='pendiente' and t.estado in ['hecha','cancelada']))):
                    raise PermissionDenied('Solo quien atiende el trabajo cambia su avance; puedes cancelar tu solicitud.')
                if t.estado in ['hecha','cancelada'] and nuevo not in [t.estado,'pendiente']:
                    raise ValidationError('Primero reabre el trabajo como pendiente.')
                if nuevo=='pendiente' and t.estado in ['hecha','cancelada'] and not (gestor or t.creador_id==request.user.pk):
                    raise PermissionDenied('Solo el responsable de oficina o el creador reabre el trabajo.')
                t.estado=nuevo
            t.revision+=1;t.actualizado=timezone.now()
            if antes!=t.estado:t.entregado_en=t.actualizado if t.estado=='hecha' else None
            t.save(update_fields=['estado','responsable','revision','actualizado','entregado_en'])
            if antes!=t.estado:
                ComentarioTrabajoOficina.objects.create(trabajo=t,autor=request.user,texto=f'{antes} → {t.estado}',es_cambio_estado=True)
                from .coordinacion import gerentes
                if t.estado=='hecha' and t.creador_id!=request.user.pk and gerentes().filter(pk=request.user.pk).exists():
                    from .models import InteraccionOficina
                    InteraccionOficina.objects.create(actor=f'persona-{request.user.pk}',destino=f'persona-{t.creador_id}',
                        tipo='entrega',texto='Tu trabajo solicitado está entregado',trabajo=t)
            auditar(request.user,'oficina.trabajo.actualizar',t,{'estado':t.estado,'responsable':t.responsable_id})
    else:t=get_object_or_404(_trabajos(request,gestor),pk=pk)
    datos=_trabajo(t,_venta_permitida(request,[t.venta_id]))
    comentarios=list(t.comentarios.select_related('autor').order_by('-id')[:100]);comentarios.reverse()
    datos['comentarios']=[{'id':c.pk,'autor':_usuario(c.autor),'texto':c.texto,'creado':c.creado,'es_cambio_estado':c.es_cambio_estado} for c in comentarios]
    datos['hay_mas_comentarios']=t.comentarios.count()>100
    return Response(datos)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def comentar(request,pk):
    _,gestor,_=_contexto(request,miembro=True)
    _estricto(request.data,['texto'])
    texto=serializers.CharField(max_length=2000,trim_whitespace=True).run_validation(request.data.get('texto'))
    with transaction.atomic():
        _bloquear(request)
        t=get_object_or_404(_trabajos(request,gestor).select_for_update(),pk=pk)
        ComentarioTrabajoOficina.objects.create(trabajo=t,autor=request.user,texto=texto)
        t.revision+=1;t.actualizado=timezone.now();t.save(update_fields=['revision','actualizado'])
    return Response({'id':t.pk,'revision':t.revision},status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ventas_persona(request,pk):
    config,gestor,_=_contexto(request,miembro=True)
    if pk!=request.user.pk and not gestor:raise PermissionDenied('El resumen de otra persona es para el responsable de la oficina.')
    u=_destino(config,pk)
    if not tiene_permiso_codigo(request,'VER_VENTAS'):return Response({'disponible':False})
    qs=ventas_visibles(request).filter(filtro_ventas_propias(u)).distinct().exclude(estado=Venta.ESTADO_ANULADA)
    pendientes=qs.filter(estado=Venta.ESTADO_PENDIENTE)
    return Response({'disponible':True,'persona':_usuario(u),'pendientes_entrega':pendientes.count(),
        'pendientes_gestion':pendientes.filter(estado_pedidos=False).count(),
        'sin_desglose_confirmado':pendientes.filter(productos_confirmados=False).count(),
        'compromiso_proximo':pendientes.filter(fecha_entrega__range=[timezone.localdate(),timezone.localdate()+timedelta(days=7)]).count(),
        'ventas':list(pendientes.order_by('fecha_entrega','id').values('id','fecha_entrega','estado_pedidos','productos_confirmados')[:12])})
