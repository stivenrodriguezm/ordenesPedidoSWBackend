"""Regresiones de conexiones ociosas, cuota y selección explícita de modelo."""
from datetime import timedelta
from unittest import mock

import requests
from django.db import OperationalError
from django.test import override_settings
from django.utils import timezone

from ordenes.asistente import gemini, views
from ordenes.models import ConversacionAsistente, MensajeAsistente
from ordenes.tests.test_asistente import respuesta_texto
from ordenes.tests.utils import LottusTestCase


@override_settings(GEMINI_API_KEY='test', GEMINI_MODELOS=['modelo-a', 'modelo-b'], ASISTENTE_EN_SEGUNDO_PLANO=False)
class ChatResilienciaTests(LottusTestCase):
    def setUp(self):
        gemini._saturados.clear()
        gemini._motivos.clear()
        self.usuario = self.crear_usuario('admin', 'administrador')
        self.api_chat = self.api(self.usuario)

    def test_selector_y_modelo_explicito_no_usan_otro(self):
        estado = self.api_chat.get('/api/asistente/estado/').data
        self.assertEqual([m['id'] for m in estado['modelos']], ['modelo-a', 'modelo-b'])
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('OK')) as llamar:
            r = self.api_chat.post('/api/asistente/preguntar/', {'texto': 'hola', 'modelo': 'modelo-b'}, format='json')
        self.assertEqual(r.data['respuesta']['modelo'], 'modelo-b')
        self.assertEqual(llamar.call_args.args[0], 'modelo-b')
        with mock.patch.object(gemini, '_llamar', side_effect=gemini._Saturado('Cuota agotada')) as llamar:
            r = self.api_chat.post('/api/asistente/preguntar/', {'texto': 'hola', 'modelo': 'modelo-b'}, format='json')
        self.assertEqual(llamar.call_count, 1)
        self.assertEqual(r.data['respuesta']['estado'], 'error')
        self.assertIn('Cuota', r.data['respuesta']['error'])

    def test_modelo_fuera_de_lista_no_crea_mensajes(self):
        r = self.api_chat.post('/api/asistente/preguntar/', {'texto': 'hola', 'modelo': '../../otro'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(MensajeAsistente.objects.exists())

    def test_cierra_mysql_antes_de_esperar_al_proveedor(self):
        with mock.patch.object(gemini, 'connection') as conexion:
            conexion.in_atomic_block = False
            def proveedor(*args):
                conexion.close.assert_called_once()
                return respuesta_texto('OK')
            with mock.patch.object(gemini, '_llamar', side_effect=proveedor):
                self.assertEqual(gemini.responder([{'rol': 'usuario', 'texto': 'hola'}], self.usuario)['texto'], 'OK')
            conexion.in_atomic_block = True
            conexion.close.reset_mock()
            gemini.liberar_conexion()
            conexion.close.assert_not_called()

    def test_socket_muerto_al_guardar_reconecta_sin_repetir_generacion(self):
        with mock.patch.object(views, 'connection') as conexion, mock.patch.object(MensajeAsistente.objects, 'filter') as filtro:
            conexion.in_atomic_block = False
            filtro.return_value.update.side_effect = [OperationalError(2006, 'gone away'), 1]
            self.assertEqual(views._guardar_resultado(99, estado='listo', texto='Resultado'), 1)
            conexion.close.assert_called_once()
            self.assertEqual(filtro.return_value.update.call_count, 2)
            filtro.assert_called_with(pk=99, estado='procesando')

    def test_429_explica_cuota_y_respaldo_automatico_funciona(self):
        cuota = mock.Mock(status_code=429)
        bien = mock.Mock(status_code=200)
        bien.json.return_value = respuesta_texto('Modelo de respaldo')
        with mock.patch.object(gemini.requests, 'post', side_effect=[cuota, bien]) as post:
            r = gemini.responder([{'rol': 'usuario', 'texto': 'hola'}], self.usuario)
        self.assertEqual((r['texto'], r['modelo']), ('Modelo de respaldo', 'modelo-b'))
        self.assertIn('cuota', gemini.modelos_disponibles()[0]['aviso'])
        self.assertNotIn('params', post.call_args.kwargs)
        self.assertNotIn('thinkingConfig', post.call_args.kwargs['json']['generationConfig'])

    def test_timeout_y_503_no_se_confunden_con_cuota(self):
        for resultado, esperado in [(requests.Timeout(), 'tiempo'), (mock.Mock(status_code=503), 'temporalmente')]:
            with mock.patch.object(gemini.requests, 'post', side_effect=resultado if isinstance(resultado, Exception) else None,
                                   return_value=resultado):
                with self.assertRaisesRegex(gemini._Saturado, esperado):
                    gemini._llamar('modelo-a', {})

    def test_error_proveedor_no_filtra_su_mensaje(self):
        fallo = mock.Mock(status_code=403)
        fallo.json.return_value = {'error': {'message': 'clave-secreta-en-URL'}}
        with mock.patch.object(gemini.requests, 'post', return_value=fallo):
            with self.assertRaises(gemini.ErrorAsistente) as error:
                gemini._llamar('modelo-a', {})
        self.assertNotIn('clave-secreta', str(error.exception))

    def test_respuesta_ya_lista_no_la_pisa_el_vencimiento(self):
        c = ConversacionAsistente.objects.create(usuario=self.usuario, titulo='Prueba')
        m = MensajeAsistente.objects.create(conversacion=c, rol='asistente', estado='procesando')
        m.creado = timezone.now() - timedelta(minutes=6)
        MensajeAsistente.objects.filter(pk=m.pk).update(estado='listo', texto='Terminada')
        self.assertEqual(views._mensaje(m)['texto'], 'Terminada')
        self.assertEqual(m.estado, 'listo')

    def test_tiempo_total_agotado_no_hace_otra_peticion(self):
        with mock.patch.object(gemini, '_llamar') as llamar:
            with self.assertRaisesRegex(gemini.ErrorAsistente, 'límite de tiempo'):
                gemini._conversar('modelo-a', [], self.usuario, None, {}, 0)
            llamar.assert_not_called()
