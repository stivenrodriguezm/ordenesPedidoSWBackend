"""Agente ejecutor (Alan): cola persistente, privada, con pasos y registros verificables.

Flujo en la oficina (2026-10-14): quien le encarga la tarea (IA Lottus u otro agente)
va hasta Alan con un «Por favor…», Alan empieza de inmediato y, al terminar, va a la
oficina del solicitante a contarle el resultado. Lo que se dicen queda en su hilo del
equipo (equipo.py) y cada uno anota una lección según su papel.
"""
import json
import re
import threading
import unicodedata
from datetime import timedelta
from types import SimpleNamespace

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from ..models import ConversacionAsistente, CustomUser, MensajeAsistente, PerfilAsistente, TrabajoAgenteIA
from ..permissions import tiene_permiso_codigo
from ..servicios import auditar
from . import equipo
from .ejecutor_config import CLAVE


DECLARACION = {'name':'ejecutar_con_agente',
    'description':'Encargar la solicitud operativa actual del usuario al agente ejecutor de la Oficina. El ejecutor empieza de inmediato, ejecuta formularios reales y devuelve avance, errores y registros guardados. Nunca asigna la solicitud a una persona. No confundir encolar con terminar.',
    'parameters':{'type':'object','properties':{'objetivo':{'type':'string','description':'Lo que le pides al ejecutor, en una frase clara dirigida a él (se muestra en el chat del equipo). La ejecución utiliza la solicitud original del humano.'}},'required':['objetivo']}}


def lanzar(pk):
    """El ejecutor empieza en cuanto recibe la tarea; el motor queda como respaldo.
    procesar() toma el trabajo con un UPDATE atómico, así que nunca corre dos veces."""
    if settings.ASISTENTE_EN_SEGUNDO_PLANO:
        transaction.on_commit(lambda: threading.Thread(target=procesar, args=(pk,), daemon=True, name=f'ejecutor-{pk}').start())


def solicitante_de(t):
    """Clave del agente que encargó la tarea; None si el humano habló directo con el ejecutor."""
    perfil = t.origen.conversacion.perfil if t.origen_id else None
    return None if es_ejecutor(perfil) else equipo.clave(perfil)


def nombre_ejecutor(agente=None):
    agente = agente or PerfilAsistente.objects.filter(clave_sistema=CLAVE).first()
    return agente.nombre if agente else 'El agente ejecutor'


def es_ejecutor(perfil):
    return bool(perfil and perfil.clave_sistema == CLAVE)


def principal(t):
    """Los enlaces de continuaciones antiguas siguen apuntando al trabajo original."""
    vistos = set()
    while t and t.continuacion_de_id and t.pk not in vistos:
        vistos.add(t.pk)
        padre = TrabajoAgenteIA.objects.filter(pk=t.continuacion_de_id,usuario_id=t.usuario_id).first()
        if not padre:
            break
        t = padre
    return t


def contexto_humano(origen, vistos=None):
    """Recupera mensajes reales; la semilla del chat de ejecución no es otra orden."""
    vistos = set() if vistos is None else vistos
    if origen.conversacion_id in vistos or len(vistos) >= 10:
        return []
    vistos.add(origen.conversacion_id)
    padre = TrabajoAgenteIA.objects.filter(conversacion_id=origen.conversacion_id,
        usuario_id=origen.conversacion.usuario_id).select_related('origen__conversacion').first()
    anteriores = contexto_humano(padre.origen,vistos) if padre else []
    preguntas = list(origen.conversacion.mensajes.filter(rol='usuario',id__lt=origen.pk).order_by('id'))
    if padre and preguntas:
        preguntas = preguntas[1:]  # primer mensaje creado por procesar(), no por el humano
    return (anteriores+[{'mensaje_id':p.pk,'texto':p.texto} for p in preguntas])[-10:]


def retomar(t, contexto=None):
    """Reanuda el mismo libro de pasos; nunca convierte el contexto en mensajes."""
    t = principal(t)
    with transaction.atomic():
        t = TrabajoAgenteIA.objects.select_for_update().get(pk=t.pk)
        if t.estado == 'ejecutando':
            return t
        if t.estado == 'pendiente':
            if contexto is not None:
                t.contexto_usuario = contexto[-10:]
                t.save(update_fields=['contexto_usuario'])
            return t
        if t.estado not in ('error','necesita_datos'):
            raise ValidationError('Solo se retoman ejecuciones que requieren revisión o datos.')
        if contexto is not None:
            t.contexto_usuario = contexto[-10:]
        t.estado,t.error,t.finalizado,t.resultado = 'pendiente','',None,''
        t.save(update_fields=['contexto_usuario','estado','error','finalizado','resultado'])
        if t.respuesta_id:
            MensajeAsistente.objects.filter(pk=t.respuesta_id).update(estado='procesando',texto='',error='')
    auditar(t.usuario,'asistente.agente_retomado',t,{'pasos_conservados':len(t.pasos)})
    solicitante = solicitante_de(t)
    if solicitante:
        equipo.decir(t.usuario,solicitante,equipo.clave(t.agente),'Ya tengo los datos que pediste. Por favor, retoma la tarea.','solicitud',t,t.conversacion)
    lanzar(t.pk)
    return t


def es_continuacion(texto):
    texto = unicodedata.normalize('NFKD',texto.casefold()).encode('ascii','ignore').decode()
    return bool(re.match(r'^\s*(?:complet\w*|contin\w*|retom\w*|reintent\w*|termin\w*|hazl\w*|es (?:solo )?una prueba|usa\b|inventa\w*)',texto))


def fallos_pendientes(escrituras):
    """Corregir los productos del mismo lote resuelve sus intentos fallidos anteriores."""
    ultimos = {}
    for i, h in enumerate(escrituras):
        args = h.get('args',{})
        clave = ('paso',args.get('paso',str(i)))
        if h.get('nombre') == 'registrar_ventas_con_productos':
            try:
                ventas = json.loads(args.get('ventas_json',''))
                if isinstance(ventas,list) and ventas:
                    destinos = [{'cliente':v.get('cliente',{}).get('id') or v.get('cliente',{}).get('cedula') or v.get('cliente',{}).get('nombre'),
                        'venta':{k:v.get('venta',{}).get(k) for k in ('id','fecha_venta','id_vendedor','sede')}} for v in ventas]
                    clave = ('lote',json.dumps(destinos,sort_keys=True))
            except (ValueError,TypeError,AttributeError):
                pass
        ultimos[clave] = h
    return any(h.get('error_operacion') for h in ultimos.values())


def consultar_estado(conversacion, texto):
    """Un seguimiento de estado nunca vuelve a ejecutar la orden anterior."""
    texto=unicodedata.normalize('NFKD',texto.casefold())
    texto=''.join(c for c in texto if not unicodedata.combining(c))
    texto=re.sub(r'[^a-z0-9 ]','',texto).strip()
    if not re.fullmatch(r'(?:y )?(?:(?:el )?resultados?|(?:cual es )?el estado|como va(?: la ejecucion| agente)?|ya terminaste|que hizo agente|hay resultados)',texto):
        return None
    return principal(TrabajoAgenteIA.objects.filter(usuario_id=conversacion.usuario_id).filter(
        Q(origen__conversacion=conversacion)|Q(conversacion=conversacion)).first())


def representar(t, completo=True):
    t = principal(t)
    datos = {'id':t.pk,'agente':{'id':t.agente_id,'nombre':nombre_ejecutor(t.agente) if t.agente_id else 'El agente ejecutor'},'estado':t.estado,
             'solicitud':t.solicitud[:240],'pasos_guardados':len(t.pasos),
             'creado':t.creado.isoformat(),'finalizado':t.finalizado.isoformat() if t.finalizado else None,
             'conversacion':t.conversacion_id}
    if completo:
        datos.update(resultado=t.resultado,error=t.error,pasos=[{'clave':p['clave'],'operacion':p['operacion'],'resultado':p['resultado']} for p in t.pasos])
        if t.estado == 'pendiente':
            from .automatizaciones import motor
            datos['motor'] = motor()
    return datos


def encolar(usuario, mensaje_id, perfil=None, objetivo=''):
    from . import perfiles
    if not usuario or not usuario.is_active or not tiene_permiso_codigo(SimpleNamespace(user=usuario),'USAR_ASISTENTE_IA'):
        raise PermissionDenied('No tienes permiso para usar IA.')
    if perfil and 'operaciones' not in perfil.areas:
        raise PermissionDenied('Este perfil no tiene operaciones habilitadas.')
    agente = PerfilAsistente.objects.filter(clave_sistema=CLAVE,activo=True).first()
    if not agente or 'operaciones' not in agente.areas or not perfiles.visible_para(agente,usuario):
        raise ValidationError(f'{nombre_ejecutor(agente)} no está disponible. Revisa su disponibilidad y permisos en Gestionar agentes.')
    with transaction.atomic():
        origen = MensajeAsistente.objects.select_for_update().select_related('conversacion').get(
            pk=mensaje_id,rol='asistente',conversacion__usuario=usuario)
        existente = TrabajoAgenteIA.objects.filter(origen=origen).first()
        if existente:
            return representar(existente)
        preguntas = contexto_humano(origen)
        if not preguntas:
            raise ValidationError('La solicitud original del usuario no está disponible.')
        anterior = TrabajoAgenteIA.objects.filter(usuario=usuario).filter(
            Q(conversacion=origen.conversacion)|Q(origen__conversacion=origen.conversacion)).first()
        chat_ejecucion = bool(anterior and anterior.conversacion_id == origen.conversacion_id)
        anterior = principal(anterior)
        if anterior and anterior.estado in ('error','necesita_datos','pendiente','ejecutando') and (
                chat_ejecucion or es_continuacion(preguntas[-1]['texto'])):
            return representar(retomar(anterior,preguntas))
        solicitud = preguntas[-1]['texto'][-6000:]
        t = TrabajoAgenteIA.objects.create(origen=origen,usuario=usuario,agente=agente,
            solicitud=solicitud,contexto_usuario=preguntas)
        from .. import vida_oficina
        if not es_ejecutor(perfil):
            # Quien encarga va hasta el ejecutor (donde esté) con un «Por favor…» corto.
            pedido = (objetivo or '').strip()[:1500] or solicitud[:1500]
            equipo.decir(usuario,equipo.clave(perfil),equipo.clave(agente),f'Por favor, {agente.nombre}: {pedido}','solicitud',t,origen.conversacion)
            vida_oficina.registrar(perfil,vida_oficina.actor(agente),'solicitud',equipo.aviso_corto(solicitud,agente.nombre),origen.conversacion)
        auditar(usuario,'asistente.agente_encolado',t,{'origen':origen.pk,'agente':agente.pk})
        lanzar(t.pk)
        return representar(t)


def recuperar_interrumpidos():
    # Pasos guardados permanecen registrados. Un reinicio nunca repite escrituras.
    ahora = timezone.now()
    ids = list(TrabajoAgenteIA.objects.filter(estado='ejecutando',iniciado__lt=ahora-timedelta(minutes=10)).values_list('id','respuesta_id'))
    for pk, respuesta in ids:
        TrabajoAgenteIA.objects.filter(pk=pk,estado='ejecutando').update(estado='error',finalizado=ahora,
            error='La ejecución se interrumpió. Los pasos guardados se conservan; puedes retomar desde su resultado.')
        if respuesta:
            MensajeAsistente.objects.filter(pk=respuesta,estado='procesando').update(estado='error',error='La ejecución se interrumpió; revisa sus pasos guardados.')


def procesar(pk):
    from . import gemini, operaciones
    from .. import vida_oficina
    token = None
    t = None
    try:
        with transaction.atomic():
            if not TrabajoAgenteIA.objects.filter(pk=pk,estado='pendiente',continuacion_de__isnull=True).update(estado='ejecutando',iniciado=timezone.now(),error=''):
                return False
            t = TrabajoAgenteIA.objects.select_related('agente','origen__conversacion').get(pk=pk)
            usuario = CustomUser.objects.get(pk=t.usuario_id)
            token = operaciones.trabajo_actual.set(pk)
            operaciones.contexto()
            if not t.conversacion_id:
                c = ConversacionAsistente.objects.create(usuario=usuario,perfil=t.agente,titulo=('Ejecución · '+t.origen.conversacion.titulo)[:120])
                MensajeAsistente.objects.create(conversacion=c,rol='usuario',texto=t.solicitud)
                m = MensajeAsistente.objects.create(conversacion=c,rol='asistente',estado='procesando')
                t.conversacion,t.respuesta = c,m
                t.save(update_fields=['conversacion','respuesta'])
            else:
                MensajeAsistente.objects.filter(pk=t.respuesta_id).update(estado='procesando',error='')
        solicitante = solicitante_de(t)
        if solicitante:
            equipo.decir(usuario,equipo.clave(t.agente),solicitante,
                'Retomo la tarea desde donde quedó.' if t.pasos else '¡Entendido! Empiezo ahora mismo.','avance',t,t.conversacion)
        vida_oficina.iniciar(t.agente,t.conversacion,texto='¡Entendido! Trabajando en la tarea' if solicitante else None)
        contexto = t.contexto_usuario or contexto_humano(t.origen)
        solicitud = 'Solicitud operativa original: '+t.solicitud
        solicitud += '\nIntervenciones reales del humano, en orden. Aplica sus aclaraciones a la solicitud original: '+json.dumps(contexto,ensure_ascii=False)
        previos=TrabajoAgenteIA.objects.filter(usuario_id=t.usuario_id).filter(
            Q(origen__conversacion=t.origen.conversacion)|Q(conversacion=t.origen.conversacion)).filter(continuacion_de__isnull=True).exclude(pk=t.pk)[:3]
        registrados=[{'id':p.pk,'estado':p.estado,'pasos_guardados':p.pasos} for p in previos]
        if registrados:
            solicitud += '\n\nReferencia de ejecuciones anteriores verificadas. No repitas sus operaciones salvo nueva orden expresa: '+json.dumps(registrados,ensure_ascii=False,default=str)
        if t.pasos:
            solicitud += '\n\nPasos ya guardados de ESTA ejecución. No los repitas: '+json.dumps(t.pasos,ensure_ascii=False,default=str)
        consultas = []
        def avance(nombre,args):
            consultas.append({'nombre':nombre})
            MensajeAsistente.objects.filter(pk=t.respuesta_id).update(herramientas=consultas)
            vida_oficina.consultar_datos(t.agente,nombre,args,t.conversacion)
            if nombre in operaciones.FUNCIONES:
                vida_oficina.registrar(t.agente,vida_oficina.actor(t.agente),'trabajo','Ejecutando y verificando operaciones',t.conversacion)
        r = gemini.responder([{'rol':'usuario','texto':solicitud}],usuario,avance,perfil=t.agente,mensaje_id=t.respuesta_id)
        t.refresh_from_db()
        escrituras = [h for h in r['herramientas'] if h.get('nombre') in ['ejecutar_operacion_plataforma','registrar_ventas_con_productos']]
        # El estado y los registros proceden de la ejecución, no de promesas del modelo.
        faltan = any(h.get('nombre')=='solicitar_datos_operacion' for h in r['herramientas'])
        fallos = fallos_pendientes(escrituras)
        estado = 'error' if fallos else 'necesita_datos' if faltan or (not t.pasos and (escrituras or not r['herramientas'])) else 'listo'
        if not t.pasos and re.match(r'^\s*(?:agrega|crea|registra|guarda|modifica|edita|actualiza)\b',t.solicitud,re.IGNORECASE):
            estado = 'error' if fallos else 'necesita_datos'
            r['texto'] = 'La operación todavía no se ha guardado. '+r['texto']
        if escrituras and not t.pasos:
            r['texto'] = 'No se guardó ninguna operación. '+r['texto']
        elif not t.pasos and all(h.get('nombre') in operaciones.FUNCIONES for h in r['herramientas']):
            r['texto'] += '\n\nNo se modificaron registros de la plataforma.'
        if t.pasos:
            r['texto'] += '\n\nResultado verificado: '+str(len(t.pasos))+' paso(s) guardado(s). Los registros y enlaces están en el detalle de ejecución.'
        TrabajoAgenteIA.objects.filter(pk=pk,estado='ejecutando').update(estado=estado,resultado=r['texto'],finalizado=timezone.now(),
            error='Una operación no pudo guardarse. Revisa el detalle antes de continuar.' if fallos else '')
        MensajeAsistente.objects.filter(pk=t.respuesta_id).update(estado='listo',texto=r['texto'],herramientas=r['herramientas'],modelo=r['modelo'],tokens=r['tokens'] or None)
        auditar(usuario,'asistente.agente_terminado',t,{'estado':estado,'pasos':len(t.pasos)})
        if solicitante:
            t.refresh_from_db()
            informar(t,solicitante,usuario)
        else:
            vida_oficina.entregar(t.agente,t.conversacion)
        return True
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception('Error en trabajo de Agente %s',pk)
        texto = str(getattr(exc,'detail',exc))[:500] if isinstance(exc,(PermissionDenied,ValidationError,gemini.ErrorAsistente)) else 'No se pudo completar la operación. Revisa los pasos guardados antes de retomar.'
        TrabajoAgenteIA.objects.filter(pk=pk,estado='ejecutando').update(estado='error',error=texto,finalizado=timezone.now())
        if t and t.respuesta_id:
            MensajeAsistente.objects.filter(pk=t.respuesta_id).update(estado='error',error=texto)
            solicitante = solicitante_de(t)
            if solicitante:
                t.refresh_from_db()
                informar(t,solicitante,t.usuario,retro=False)
            else:
                vida_oficina.entregar(t.agente,t.conversacion,error=True)
        return False
    finally:
        if token is not None:
            operaciones.trabajo_actual.reset(token)
        connection.close()


AVISOS_FIN = {'listo':'{s}, la tarea se ejecutó con éxito.','necesita_datos':'{s}, necesito unos datos para terminar la tarea.',
              'error':'{s}, la tarea necesita revisión.'}


def informar(t, solicitante, usuario, retro=True):
    """El ejecutor va a la oficina de quien le encargó la tarea y le cuenta el resultado."""
    from .. import vida_oficina
    nombre_sol, yo = equipo.nombre(solicitante), equipo.clave(t.agente)
    estado = t.estado if t.estado in AVISOS_FIN else 'error'
    vida_oficina.registrar(t.agente,solicitante,'entrega' if estado=='listo' else 'revision',
                           AVISOS_FIN[estado].format(s=nombre_sol),t.conversacion)
    detalle = (t.resultado or t.error or '').strip()
    encabezado = {'listo':'Listo, la tarea se ejecutó con éxito.','necesita_datos':'Necesito unos datos para terminar.',
                  'error':'La tarea necesita revisión.'}[estado]
    equipo.decir(usuario,yo,solicitante,encabezado+('\n\n'+detalle if detalle else ''),'resultado',t,t.conversacion)
    persona = (getattr(usuario,'first_name','') or '').strip() or 'el usuario'
    respuesta = {'listo':f'¡Gracias, {t.agente.nombre}! Le confirmo el resultado a {persona}.',
                 'necesita_datos':f'Entendido. Le pido esos datos a {persona} y retomamos.',
                 'error':f'Entendido. Reviso con {persona} el paso que falló antes de retomar.'}[estado]
    equipo.decir(usuario,solicitante,yo,respuesta,'respuesta',t,t.conversacion)
    if retro:
        try:
            equipo.retrospectiva(t,solicitante)
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Retrospectiva fallida en la ejecución %s',t.pk,exc_info=True)

