"""Reservas y consumo con conexiones MySQL independientes; ningún servicio externo."""
import threading
import unittest
from datetime import time, timedelta
from unittest import mock

from django.db import connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ordenes.asistente import automatizaciones as tareas, gemini
from ordenes.models import (AutomatizacionAsistente, ConversacionAsistente, CustomUser,
                           EjecucionAutomatizacionIA, MensajeAsistente, PerfilAsistente)


def competir(funcion):
    barrera = threading.Barrier(2)
    resultados, errores = [None, None], []

    def hilo(i):
        try:
            barrera.wait(timeout=10)
            resultados[i] = funcion(i)
        except Exception as exc:
            errores.append(exc)
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=hilo, args=(i,)) for i in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=20)
    if any(h.is_alive() for h in hilos):
        raise AssertionError('Los trabajadores no terminaron en 20 segundos.')
    if errores:
        raise errores[0]
    return resultados


@unittest.skipUnless(connection.vendor == 'mysql', 'Requiere MySQL aislado (settings_test_mysql)')
@override_settings(GEMINI_API_KEY='solo-prueba', GEMINI_MODELOS=['modelo-aislado'], ASISTENTE_EN_SEGUNDO_PLANO=False)
class ConcurrenciaAutomatizacionesIATests(TransactionTestCase):
    def setUp(self):
        self.usuario = CustomUser.objects.create(username='responsable_aislado', role='administrador')
        self.perfil = PerfilAsistente.objects.create(nombre='Agente aislado', rol='Ventas',
            instrucciones='Consulta los datos permitidos.', areas=['ventas'])
        self.a = AutomatizacionAsistente.objects.create(usuario=self.usuario, perfil=self.perfil,
            perfil_nombre=self.perfil.nombre, nombre='Tarea aislada', instrucciones='Resume el período consultando solamente datos actuales.',
            frecuencia='diaria', hora=time(9), proxima_ejecucion=timezone.now()-timedelta(minutes=1))

    def test_dos_motores_reservan_la_misma_franja_una_sola_vez(self):
        resultados = competir(lambda i: tareas.reservar(self.a.pk))
        self.assertEqual(sum(e is not None for e in resultados), 1)
        self.assertEqual(self.a.ejecuciones.count(), 1)
        self.a.refresh_from_db()
        self.assertGreater(self.a.proxima_ejecucion, timezone.now())

    def test_dos_reintentos_manuales_recuperan_la_misma_ejecucion(self):
        resultados = competir(lambda i: tareas.reservar(self.a.pk, usuario_id=self.usuario.pk, clave='intento-aislado'))
        self.assertEqual(resultados[0].pk, resultados[1].pk)
        self.assertEqual(self.a.ejecuciones.count(), 1)

    def test_dos_trabajadores_no_consumen_dos_consultas(self):
        e = tareas.reservar(self.a.pk)
        with mock.patch.object(gemini, 'responder', return_value={'texto':'Respuesta aislada', 'herramientas':[], 'modelo':'modelo-aislado', 'tokens':10}) as proveedor:
            resultados = competir(lambda i: tareas.ejecutar(e.pk))
        self.assertEqual(sorted(resultados), [False, True])
        self.assertEqual(proveedor.call_count, 1)
        e.refresh_from_db()
        self.assertEqual(e.estado, 'listo')
        self.assertEqual(ConversacionAsistente.objects.filter(usuario=self.usuario).count(), 1)
        self.assertEqual(MensajeAsistente.objects.filter(rol='usuario').count(), 1)

    def test_tareas_del_mismo_usuario_respetan_el_limite_compartido(self):
        c = ConversacionAsistente.objects.create(usuario=self.usuario)
        MensajeAsistente.objects.bulk_create([MensajeAsistente(conversacion=c, rol='usuario', texto='Pregunta aislada') for _ in range(39)])
        otra = AutomatizacionAsistente.objects.create(usuario=self.usuario, es_general=True, perfil_nombre='IA Lottus',
            nombre='Otra tarea', instrucciones='Otra revisión aislada.', frecuencia='diaria', hora=time(9), proxima_ejecucion=timezone.now()-timedelta(minutes=1))
        ids = [tareas.reservar(self.a.pk).pk, tareas.reservar(otra.pk).pk]
        with mock.patch.object(gemini, 'responder', return_value={'texto':'Respuesta aislada', 'herramientas':[], 'modelo':'modelo-aislado', 'tokens':10}) as proveedor:
            competir(lambda i: tareas.ejecutar(ids[i]))
        self.assertEqual(proveedor.call_count, 1)
        self.assertEqual(MensajeAsistente.objects.filter(rol='usuario').count(), 40)
        self.assertEqual(sorted(EjecucionAutomatizacionIA.objects.values_list('estado',flat=True)), ['error','listo'])

    def test_chat_y_tarea_simultaneos_no_superan_la_cuota(self):
        c = ConversacionAsistente.objects.create(usuario=self.usuario)
        MensajeAsistente.objects.bulk_create([MensajeAsistente(conversacion=c, rol='usuario', texto='Pregunta aislada') for _ in range(39)])
        e = tareas.reservar(self.a.pk)
        def accion(i):
            if i == 0:
                return tareas.ejecutar(e.pk)
            api = APIClient();api.force_authenticate(self.usuario)
            return api.post('/api/asistente/preguntar/', {'texto':'Pregunta aislada concurrente.'}, format='json').status_code
        with mock.patch.object(gemini, 'responder', return_value={'texto':'Respuesta aislada', 'herramientas':[], 'modelo':'modelo-aislado', 'tokens':10}) as proveedor:
            resultados = competir(accion)
        self.assertIn(resultados[1], [202,429])
        self.assertEqual(proveedor.call_count, 1)
        self.assertEqual(MensajeAsistente.objects.filter(rol='usuario').count(), 40)
