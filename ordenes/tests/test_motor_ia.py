"""Arranque local y recuperación del motor; sin red ni operaciones comerciales."""
import io
import tempfile
import threading
from contextlib import ExitStack
from unittest import mock

from django.core.management import get_commands
from django.db import OperationalError
from django.test import SimpleTestCase, override_settings

from ordenes.management.commands import ejecutar_automatizaciones_ia as worker
from ordenes.management.commands import runserver


class MotorLocalTests(SimpleTestCase):
    def test_runserver_registrado_conserva_staticfiles(self):
        self.assertEqual(get_commands()['runserver'], 'ordenes')
        self.assertTrue(issubclass(runserver.Command, runserver.Runserver))

    @mock.patch.dict('os.environ', {'RUN_MAIN': ''})
    def test_padre_inicia_motor_y_lo_detiene_al_cerrar(self):
        command = runserver.Command(stdout=io.StringIO())
        with mock.patch.object(runserver.threading, 'Thread') as hilo, \
                mock.patch.object(runserver.Runserver, 'run', return_value='servidor'):
            self.assertEqual(command.run(use_reloader=True), 'servidor')
        hilo.return_value.start.assert_called_once()
        self.assertTrue(hilo.call_args.kwargs['args'][0].is_set())

    def test_recarga_y_opcion_externa_no_duplican_motor(self):
        for entorno, opciones in [({'RUN_MAIN':'true'}, {}), ({'RUN_MAIN':''}, {'sin_motor_ia':True})]:
            with mock.patch.dict('os.environ', entorno), \
                    mock.patch.object(runserver.threading, 'Thread') as hilo, \
                    mock.patch.object(runserver.Runserver, 'run') as servidor:
                runserver.Command().run(**opciones)
                hilo.assert_not_called()
                servidor.assert_called_once_with(**opciones)

    def test_motor_comparte_settings_y_reinicia_si_falla(self):
        detener = mock.Mock()
        detener.is_set.side_effect = [False, False, True]
        with mock.patch.object(runserver, 'call_command', side_effect=[RuntimeError('fallo'), None]) as llamar, \
                mock.patch.object(runserver.connections, 'close_all') as cerrar, \
                mock.patch.object(runserver.log, 'exception'):
            runserver.Command()._motor(detener)
        self.assertEqual(llamar.call_count, 2)
        self.assertEqual(llamar.call_args.args, ('ejecutar_automatizaciones_ia',))
        self.assertIs(llamar.call_args.kwargs['detener'], detener)
        self.assertEqual(cerrar.call_count, 2)


class RecuperacionMotorTests(SimpleTestCase):
    def test_conexion_se_revisa_antes_de_esperar_sin_reabrirla_cada_ciclo(self):
        # Cerrar todo en cada ciclo abría ~360 conexiones/hora y agotaba el límite del hosting.
        detener = mock.Mock()
        detener.is_set.side_effect = [False, False, True]
        opciones = {'continuo':True, 'intervalo':10, 'trabajadores':2, 'limite':20, 'detener':detener}
        with ExitStack() as stack:
            for modulo, nombres in [(worker.tareas, ['latido','recuperar_interrumpidas']),
                                    (worker.coordinacion, ['recuperar_interrumpidos','encolar_programado']),
                                    (worker.vida_oficina, ['impulsar']),
                                    (worker.agente, ['recuperar_interrumpidos'])]:
                for nombre in nombres:
                    stack.enter_context(mock.patch.object(modulo, nombre))
            revisar = stack.enter_context(mock.patch.object(worker, 'close_old_connections'))
            stack.enter_context(mock.patch.object(worker.log, 'exception'))
            encolar = stack.enter_context(mock.patch.object(worker.tareas, 'encolar_vencidas',
                                                           side_effect=[OperationalError('socket cerrado'), []]))
            cerrar = stack.enter_context(mock.patch.object(worker.connections, 'close_all'))
            trabajos = stack.enter_context(mock.patch.object(worker.TrabajoAgenteIA.objects, 'filter'))
            trabajos.return_value.order_by.return_value.values_list.return_value = [7]
            informes = stack.enter_context(mock.patch.object(worker.InformeAreas.objects, 'filter'))
            informes.return_value.values_list.return_value = []
            privados = stack.enter_context(mock.patch.object(worker.EjecucionAutomatizacionIA.objects, 'filter'))
            privados.return_value.exclude.return_value.order_by.return_value.values_list.return_value = []
            ejecutar = stack.enter_context(mock.patch.object(worker.agente, 'procesar', return_value=True))
            cierres = []
            detener.wait.side_effect = lambda intervalo: cierres.append(revisar.call_count)
            worker.Command(stdout=io.StringIO())._atender(opciones)
        self.assertEqual(encolar.call_count, 2)
        self.assertEqual(cierres, [2, 4])
        cerrar.assert_not_called()
        ejecutar.assert_called_once_with(7)

    def test_bloqueo_se_libera_incluso_si_falla_el_motor(self):
        with tempfile.TemporaryDirectory() as carpeta, override_settings(BASE_DIR=carpeta), \
                mock.patch.object(worker.connections, 'close_all'), \
                mock.patch.object(worker.Command, '_atender', side_effect=[RuntimeError('fallo'), None]) as atender:
            with self.assertRaises(RuntimeError):
                worker.Command().handle()
            worker.Command().handle()
            self.assertEqual(atender.call_count, 2)


class ServidorConHilosTests(SimpleTestCase):
    """El servidor local reutiliza hilos (y sus conexiones a MySQL) en vez de uno por petición."""

    def test_runserver_usa_el_grupo_de_hilos_salvo_nothreading(self):
        for opciones, esperado, servidor in [({'use_threading': True}, False, runserver.ServidorConHilos),
                                             ({'use_threading': False}, False, runserver.Runserver.server_cls)]:
            command = runserver.Command()
            with mock.patch.object(runserver.Runserver, 'inner_run') as interno:
                command.inner_run(**opciones)
            self.assertIs(interno.call_args.kwargs['use_threading'], esperado)
            self.assertIs(command.server_cls, servidor)

    def test_atiende_peticiones_en_paralelo_sin_un_hilo_por_peticion(self):
        import http.client
        from django.core.servers.basehttp import WSGIRequestHandler

        nombres, inicio = set(), threading.Barrier(3, timeout=5)

        def app(environ, start_response):
            nombres.add(threading.current_thread().name)
            if environ['PATH_INFO'] == '/lenta':
                inicio.wait()
            start_response('200 OK', [('Content-Type', 'text/plain'), ('Content-Length', '2')])
            return [b'ok']

        class Silencioso(WSGIRequestHandler):
            def log_message(self, *args):
                pass

        servidor = runserver.ServidorConHilos(('127.0.0.1', 0), Silencioso)
        servidor.set_app(app)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        puerto = servidor.server_address[1]

        def pedir(ruta):
            c = http.client.HTTPConnection('127.0.0.1', puerto, timeout=5)
            c.request('GET', ruta)
            r = c.getresponse()
            return r.status, r.getheader('Connection'), r.read()

        try:
            # Dos peticiones lentas a la vez: el grupo las atiende en paralelo.
            hilos = [threading.Thread(target=pedir, args=('/lenta',)) for _ in range(2)]
            [h.start() for h in hilos]
            inicio.wait()
            [h.join(5) for h in hilos]
            for _ in range(20):
                self.assertEqual(pedir('/'), (200, 'close', b'ok'))
        finally:
            servidor.shutdown()
            servidor.server_close()
        self.assertTrue(all(n.startswith('lottus-http') for n in nombres))
        self.assertLessEqual(len(nombres), runserver.ServidorConHilos.hilos)


class ArranqueSinBaseDeDatosTests(SimpleTestCase):
    """Si MySQL no responde al arrancar, el servidor reintenta y arranca igual (no queda sin servir)."""

    def comando(self):
        cmd = runserver.Command(stdout=io.StringIO(), stderr=io.StringIO())
        cmd.esperas_arranque = (0, 0)
        return cmd

    def test_reintenta_y_continua_cuando_vuelve(self):
        cmd = self.comando()
        fallas = [OperationalError(2003, 'timed out'), None]
        def revisar(_self):
            error = fallas.pop(0)
            if error:
                raise error
        with mock.patch.object(runserver.Runserver, 'check_migrations', revisar), mock.patch.object(runserver.time, 'sleep') as dormir:
            cmd.check_migrations()
        self.assertEqual(fallas, [])
        dormir.assert_called_once_with(0)

    def test_si_sigue_caida_arranca_igual_sin_excepcion(self):
        cmd = self.comando()
        with mock.patch.object(runserver.Runserver, 'check_migrations', side_effect=OperationalError(2003, 'timed out')) as revisar, \
                mock.patch.object(runserver.time, 'sleep'):
            self.assertIsNone(cmd.check_migrations())
        self.assertEqual(revisar.call_count, 3)
        self.assertIn('arranca igual', cmd.stderr.getvalue())
