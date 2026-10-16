"""Actividad de agentes basada en trabajos reales; avisos públicos sin datos privados.

Las iniciativas abren un diálogo privado con gerencia, como máximo una al día por
agente y administrador y sin repetir una pregunta pendiente. No gastan llamadas a
Gemini; el análisis comienza cuando el administrador responde o programa trabajo.
"""
from datetime import timedelta
import time
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from .models import (ConversacionAsistente, CustomUser, EjecucionAutomatizacionIA,
                     InteraccionOficina, MensajeAsistente, MiembroOficina, PerfilAsistente,
                     ZonaOficinaIA)
from .permissions import tiene_permiso_codigo
from .asistente import perfiles

_ultimo_impulso = -1e9


def actor(perfil):
    return f'ia-{perfil.pk}' if perfil else 'ia-general'


def registrar(perfil, destino, tipo, texto, conversacion=None, ejecucion=None):
    return InteraccionOficina.objects.create(actor=actor(perfil), destino=destino,
        tipo=tipo, texto=texto[:160], conversacion=conversacion, ejecucion=ejecucion)


def iniciar(perfil, conversacion, ejecucion=None, texto=None):
    registrar(perfil, actor(perfil), 'trabajo', texto or 'Analizando la tarea en su puesto', conversacion, ejecucion)


def entregar(perfil, conversacion, ejecucion=None, error=False):
    usuario = conversacion.usuario
    destino = f'persona-{usuario.pk}' if MiembroOficina.objects.filter(usuario=usuario, habilitado=True, zona__isnull=False).exists() else actor(perfil)
    registrar(perfil, destino, 'revision' if error else 'entrega',
        'Necesita orientación para continuar' if error else 'Entregando el resultado de su trabajo', conversacion, ejecucion)


def consultar_datos(perfil, nombre, args, conversacion, ejecucion=None):
    ambientes = {'resumen_ventas':'showroom', 'ventas_por_asesor':'showroom', 'tendencia_ventas':'showroom',
        'gestion_ventas':'showroom', 'detalle_venta':'showroom', 'saldos_por_cobrar':'finanzas',
        'finanzas':'finanzas', 'pedidos_proveedor':'operaciones', 'pedidos_tela':'operaciones', 'crear_curso':'entrenamiento',
        'consultar_pagina_web':'creativo', 'leer_codigo_pagina_web':'creativo', 'ver_imagen_pagina_web':'creativo'}
    ambientes.update({'consultar_formulario':'oficina','consultar_registros_plataforma':'oficina',
                       'ejecutar_operacion_plataforma':'oficina','registrar_ventas_con_productos':'showroom'})
    ambiente = ambientes.get(nombre)
    if nombre == 'consulta_datos':
        ambiente = {'ventas':'showroom','cobros':'finanzas','pedidos':'operaciones'}.get(args.get('dominio'))
    zona = ZonaOficinaIA.objects.filter(ambiente=ambiente).first() if ambiente else None
    if zona:
        # Una visita por área en cada trabajo; varias consultas no generan una cola infinita.
        destino = f'zona-{zona.pk}'
        if not InteraccionOficina.objects.filter(conversacion=conversacion, ejecucion=ejecucion, tipo='analisis', destino=destino).exists():
            registrar(perfil, destino, 'analisis', f'Consultando información de {zona.nombre}', conversacion, ejecucion)


def _administrador(usuario):
    return usuario.is_active and usuario.role == 'administrador' and tiene_permiso_codigo(SimpleNamespace(user=usuario), 'USAR_ASISTENTE_IA')


def pregunta_objetivo(perfil):
    if 'operaciones' in perfil.areas:
        return f'Mi objetivo es: {perfil.rol}. ¿Qué tarea o proceso debemos priorizar y quién será responsable de revisar el resultado?'
    if 'formacion' in perfil.areas:
        return '¿Qué habilidad del equipo debemos entrenar primero y cómo mediremos su avance? Puedo convertir tu prioridad en un curso o un plan de práctica.'
    if 'ventas' in perfil.areas:
        return '¿Qué meta comercial quieres priorizar y qué período debo comparar? Con tu orientación puedo analizar resultados y proponerte acciones concretas.'
    if any(a in perfil.areas for a in ['pedidos','inventario']):
        return '¿Qué entrega, proveedor o bloqueo operativo debemos revisar primero? Indícame la prioridad para preparar un análisis verificable.'
    if any(a in perfil.areas for a in ['finanzas','cobros']):
        return '¿Qué indicador financiero o gestión de cobro quieres revisar primero y para qué período? Necesito esa prioridad para orientar mi análisis.'
    return f'Mi objetivo es: {perfil.rol}. ¿Qué resultado concreto quieres que priorice y con qué criterio evaluarás mi aporte?'


def abrir_dialogo(usuario, perfil, pregunta):
    if not _administrador(usuario) or not perfil or not perfil.activo or not perfiles.visible_para(perfil, usuario):
        return {'error':'La orientación está disponible entre agentes activos y su administrador.'}
    with transaction.atomic():
        # Serializa también entre motores. Los diálogos son privados del destinatario.
        CustomUser.objects.select_for_update().get(pk=usuario.pk)
        existentes = InteraccionOficina.objects.filter(tipo='dialogo', actor=actor(perfil), conversacion__usuario=usuario).select_related('conversacion').order_by('-id')
        ultimo = existentes.first()
        if ultimo and not ultimo.conversacion.mensajes.filter(rol='usuario').exists():
            return {'pendiente':True,'conversacion':ultimo.conversacion_id,'nota':'Ya hay una pregunta esperando tu orientación.'}
        if ultimo and ultimo.creado > timezone.now()-timedelta(days=1):
            return {'pendiente':False,'conversacion':ultimo.conversacion_id,'nota':'Este agente ya abrió un diálogo hoy.'}
        c = ConversacionAsistente.objects.create(usuario=usuario, perfil=perfil, titulo=f'Iniciativa · {perfil.nombre}'[:120])
        MensajeAsistente.objects.create(conversacion=c, rol='asistente', texto=pregunta[:1200])
        registrar(perfil, f'persona-{usuario.pk}', 'dialogo', 'Tiene una pregunta para su administrador', c)
        return {'pendiente':True,'conversacion':c.pk,'nota':'La pregunta quedó en el chat privado del administrador; aún no hay respuesta.'}


def impulsar(limite=1, forzar=False):
    """Una iniciativa por ciclo, solo durante la presencia reciente de un administrador."""
    global _ultimo_impulso
    if not forzar and time.monotonic()-_ultimo_impulso < 60:
        return 0
    _ultimo_impulso = time.monotonic()
    miembros = MiembroOficina.objects.filter(habilitado=True, usuario__is_active=True,
        usuario__role='administrador', zona__isnull=False, ultima_presencia__gte=timezone.now()-timedelta(minutes=2)).select_related('usuario')
    creados = 0
    for m in miembros:
        for perfil in PerfilAsistente.objects.filter(activo=True, zona__isnull=False).order_by('id'):
            if not _administrador(m.usuario) or not perfiles.visible_para(perfil, m.usuario):
                continue
            if EjecucionAutomatizacionIA.objects.filter(perfil_id_original=perfil.pk, estado__in=['pendiente','ejecutando']).exists():
                continue
            anterior = InteraccionOficina.objects.filter(tipo='dialogo', actor=actor(perfil), conversacion__usuario=m.usuario).order_by('-id').first()
            if anterior and (anterior.creado > timezone.now()-timedelta(days=1) or not anterior.conversacion.mensajes.filter(rol='usuario').exists()):
                continue
            abrir_dialogo(m.usuario, perfil, pregunta_objetivo(perfil))
            creados += 1
            if creados >= limite:
                return creados
    return creados


DECLARACIONES = [
    {'name':'consultar_agente_oficina', 'description':'Pedir criterio a otro agente activo visible. Solo responde sobre la pregunta y las áreas compartidas; no consulta chats privados ni ejecuta acciones.',
     'parameters':{'type':'object','properties':{'agente_id':{'type':'integer'},'pregunta':{'type':'string'}},'required':['agente_id','pregunta']}},
    {'name':'pedir_orientacion_administrador', 'description':'Abrir una pregunta privada a tu administrador actual cuando falta una prioridad o decisión humana. No inventes su respuesta: queda pendiente hasta que responda.',
     'parameters':{'type':'object','properties':{'pregunta':{'type':'string'}},'required':['pregunta']}},
]


def colaborar(nombre, args, usuario, perfil, mensaje_id, modelo, segundos):
    if nombre not in ['consultar_agente_oficina','pedir_orientacion_administrador']:
        return {'error':'Herramienta de colaboración desconocida.'}
    if not _administrador(usuario) or not perfil or not perfil.activo:
        return {'error':'La colaboración de agentes está disponible para administradores.'}
    c = ConversacionAsistente.objects.filter(mensajes__pk=mensaje_id, usuario=usuario, perfil=perfil).first()
    pregunta = args.get('pregunta')
    if not c or not isinstance(pregunta,str) or not 10 <= len(pregunta.strip()) <= 1200:
        return {'error':'Indica una pregunta entre 10 y 1200 caracteres.'}
    if nombre == 'pedir_orientacion_administrador':
        return abrir_dialogo(usuario, perfil, pregunta.strip())
    try:
        pk = int(args.get('agente_id'))
    except (TypeError, ValueError):
        return {'error':'Selecciona un agente existente.'}
    colega = PerfilAsistente.objects.filter(pk=pk, activo=True).first()
    if not colega or colega.pk == perfil.pk or not perfiles.visible_para(colega,usuario):
        return {'error':'El colega no está disponible.'}
    compartidas = set(perfil.areas) & set(colega.areas)
    # No adjunta instrucciones, documentos ni resultados privados del remitente.
    # Una consulta de criterio, sin herramientas, conserva los límites de ambos perfiles.
    if not InteraccionOficina.objects.filter(conversacion=c, actor=actor(perfil), destino=actor(colega), tipo='consulta').exists():
        ejecucion=c.ejecuciones_ia.filter(respuesta_id=mensaje_id).first()
        registrar(perfil, actor(colega), 'consulta', 'Consultando una posibilidad con su colega', c, ejecucion)
    from .asistente import equipo, gemini
    equipo.decir(usuario, actor(perfil), actor(colega), pregunta.strip(), 'consulta', conversacion=c)
    try:
        texto = gemini.analizar_evidencia('Responde como colega a esta pregunta. No tienes resultados operativos adjuntos; '
            'no inventes cifras ni acciones realizadas. Señala qué evidencia hace falta.\n'+pregunta, usuario, colega, modelo, min(25,segundos))
    except gemini.ErrorAsistente as exc:
        return {'error':str(exc)}
    equipo.decir(usuario, actor(colega), actor(perfil), texto['texto'], 'respuesta', conversacion=c)
    return {'agente':colega.nombre,'criterio':texto['texto'],'areas_compartidas':sorted(compartidas)}
