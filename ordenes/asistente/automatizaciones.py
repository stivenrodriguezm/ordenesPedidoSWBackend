"""Cola persistente de tareas de lectura de IA. No depende de peticiones ni de pestañas."""
from datetime import timedelta
from types import SimpleNamespace

from django.db import connection, transaction, OperationalError
from django.utils import timezone

from ..models import (AutomatizacionAsistente, ConversacionAsistente, CustomUser,
                      EjecucionAutomatizacionIA, MensajeAsistente, MotorAutomatizacionesIA, PerfilAsistente)
from ..permissions import tiene_permiso_codigo
from ..servicios import ErrorNegocio, auditar
from .programacion import siguiente

EXPIRA_TRABAJO = timedelta(minutes=5)
EXPIRA_COLA = timedelta(minutes=30)
LIMITE_HORA = 40


def puede_programar(usuario):
    request = SimpleNamespace(user=usuario)
    return (usuario.is_active and tiene_permiso_codigo(request, 'USAR_ASISTENTE_IA')
            and tiene_permiso_codigo(request, 'GESTIONAR_PERFILES_IA'))


def latido():
    MotorAutomatizacionesIA.objects.update_or_create(nombre='principal', defaults={'ultimo_latido': timezone.now()})


def motor():
    visto = MotorAutomatizacionesIA.objects.filter(nombre='principal').values_list('ultimo_latido', flat=True).first()
    return {'activo': bool(visto and visto >= timezone.now() - EXPIRA_TRABAJO),
            'ultimo_latido': visto.isoformat() if visto else None, 'zona_horaria': 'America/Bogota'}


def reservar(pk, usuario_id=None, clave=None, ahora=None):
    """Bloqueo por automatización: una única ejecución activa y una franja/clave única."""
    ahora = ahora or timezone.now()
    with transaction.atomic():
        qs = AutomatizacionAsistente.objects.select_for_update()
        if usuario_id is not None:
            qs = qs.filter(usuario_id=usuario_id)
        a = qs.filter(pk=pk).first()
        if not a:
            raise ErrorNegocio('Automatización no encontrada.', estado=404)
        manual = usuario_id is not None
        if manual:
            existente = a.ejecuciones.filter(clave=f'manual:{clave}').first()
            if existente:
                return existente
        if a.archivada:
            if manual:
                raise ErrorNegocio('Restaura la automatización antes de ejecutarla.', estado=409)
            return None
        if not manual and (not a.activa or not a.proxima_ejecucion or a.proxima_ejecucion > ahora):
            return None
        if a.ejecuciones.filter(estado__in=['pendiente', 'ejecutando']).exists():
            if manual:
                raise ErrorNegocio('Esta automatización ya tiene una ejecución en curso.', estado=409)
            return None
        fecha = ahora if manual else a.proxima_ejecucion
        e = a.ejecuciones.create(clave=f'manual:{clave}' if manual else f'horario:{fecha.isoformat()}',
            origen='manual' if manual else 'programada', programada_para=fecha, nombre=a.nombre,
            instrucciones=a.instrucciones, modelo_solicitado=a.modelo, perfil_id_original=a.perfil_id,
            perfil_nombre=a.perfil_nombre, es_general=a.es_general)
        if not manual:
            # Si el motor estuvo apagado, ejecuta una vez lo pendiente; no reproduce
            # toda la cola histórica ni gasta múltiples análisis del mismo atraso.
            a.proxima_ejecucion = None if a.frecuencia == 'una_vez' else siguiente(a, ahora)
            if a.proxima_ejecucion is None:
                a.activa = False
            a.save(update_fields=['proxima_ejecucion', 'activa', 'actualizada'])
        auditar(a.usuario, 'asistente.automatizacion_encolada', e, {'origen': e.origen, 'automatizacion': a.pk})
        return e


def encolar_vencidas(limite=20):
    ids = list(AutomatizacionAsistente.objects.filter(activa=True, archivada=False,
        proxima_ejecucion__lte=timezone.now()).order_by('proxima_ejecucion', 'id').values_list('pk', flat=True)[:limite])
    return [e.pk for pk in ids if (e := reservar(pk)) is not None]


def recuperar_interrumpidas():
    ahora = timezone.now()
    viejas = list(EjecucionAutomatizacionIA.objects.filter(estado='ejecutando', iniciada__lt=ahora-EXPIRA_TRABAJO).values_list('pk', 'respuesta_id'))
    for pk, respuesta_id in viejas:
        texto = 'La ejecución se interrumpió o agotó el tiempo. Puedes ejecutarla de nuevo; no se reintentó automáticamente.'
        with transaction.atomic():
            actualizado = EjecucionAutomatizacionIA.objects.filter(pk=pk, estado='ejecutando', iniciada__lt=ahora-EXPIRA_TRABAJO).update(estado='error', error=texto, finalizada=ahora)
            if actualizado and respuesta_id:
                MensajeAsistente.objects.filter(pk=respuesta_id, estado='procesando').update(estado='error', error=texto)
    EjecucionAutomatizacionIA.objects.filter(estado='pendiente', creada__lt=ahora-EXPIRA_COLA).update(
        estado='error', error='La tarea no pudo iniciar en 30 minutos. Comprueba que el motor esté activo y vuelve a ejecutarla.', finalizada=ahora)


def _terminar(pk, **campos):
    # No sobrescribir el resultado de una recuperación por interrupción.
    for intento in range(2):
        try:
            return EjecucionAutomatizacionIA.objects.filter(pk=pk, estado='ejecutando').update(finalizada=timezone.now(), **campos)
        except OperationalError:
            if intento or connection.in_atomic_block:
                raise
            connection.close()


def ejecutar(pk):
    """Reclama con comparación de estado; termina fuera de la transacción de reserva."""
    from .views import _procesar
    e = None
    try:
        with transaction.atomic():
            tomado = EjecucionAutomatizacionIA.objects.filter(pk=pk, estado='pendiente').update(estado='ejecutando', iniciada=timezone.now())
        if not tomado:
            return False
        e = EjecucionAutomatizacionIA.objects.select_related('automatizacion').get(pk=pk)
        usuario = CustomUser.objects.get(pk=e.automatizacion.usuario_id)
        if not puede_programar(usuario):
            raise ErrorNegocio('El responsable ya no tiene permisos para ejecutar automatizaciones de IA.')
        perfil = PerfilAsistente.objects.filter(pk=e.perfil_id_original, activo=True).first() if not e.es_general else None
        if not e.es_general and not perfil:
            raise ErrorNegocio('El agente está pausado o fue eliminado. Revisa el agente de esta automatización.')
        with transaction.atomic():
            # Serializa el consumo de las tareas de un mismo responsable.
            CustomUser.objects.select_for_update().get(pk=usuario.pk)
            if MensajeAsistente.objects.filter(conversacion__usuario=usuario, rol='usuario', creado__gte=timezone.now()-timedelta(hours=1)).count() >= LIMITE_HORA:
                raise ErrorNegocio('Llegaste al límite compartido de 40 preguntas y automatizaciones por hora. Puedes ejecutar esta tarea más tarde.')
            conv = ConversacionAsistente.objects.create(usuario=usuario, perfil=perfil, titulo=f'Automatización · {e.nombre}'[:120])
            MensajeAsistente.objects.create(conversacion=conv, rol='usuario', texto=e.instrucciones)
            respuesta = MensajeAsistente.objects.create(conversacion=conv, rol='asistente', texto='', estado='procesando', modelo=e.modelo_solicitado)
            e.conversacion = conv
            e.respuesta = respuesta
            e.save(update_fields=['conversacion', 'respuesta'])
        _procesar(respuesta.pk, [{'rol': 'usuario', 'texto': e.instrucciones}], usuario.pk, False, e.modelo_solicitado or None,
                  perfil.pk if perfil else None, exigir_perfil_activo=not e.es_general)
        respuesta = MensajeAsistente.objects.filter(pk=respuesta.pk).first()
        if not respuesta:
            raise ErrorNegocio('La conversación se eliminó durante esta ejecución.')
        _terminar(pk, estado='listo' if respuesta.estado == 'listo' else 'error', resultado=respuesta.texto,
                  error=respuesta.error or ('' if respuesta.estado == 'listo' else 'La respuesta no pudo terminar.'), modelo_usado=respuesta.modelo)
        auditar(usuario, 'asistente.automatizacion_terminada', e, {'estado': respuesta.estado, 'modelo': respuesta.modelo})
        return True
    except ErrorNegocio as exc:
        _terminar(pk, estado='error', error=exc.mensaje[:500])
        return True
    except Exception:
        from .views import log
        log.exception('Error de ejecución de automatización IA %s', pk)
        if not connection.in_atomic_block:
            connection.close()
        _terminar(pk, estado='error', error='No se pudo completar la tarea. Revisa el motor y vuelve a ejecutarla.')
        return True
    finally:
        if not connection.in_atomic_block:
            connection.close()
