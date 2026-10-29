"""(2026-10-28) Agente Desarrollador: solo el superusuario lo usa; el plan se aprueba antes de
implementar; el servicio aparte solo avanza los estados permitidos por el canal con token."""
from unittest import mock

from django.core import mail
from django.test import override_settings

from ordenes.models import PerfilAsistente, TareaDesarrollo
from ordenes.tests.utils import LottusTestCase

TOKEN = 'token-de-prueba-desarrollador'


@override_settings(DESARROLLADOR_TOKEN=TOKEN, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DesarrolladorTests(LottusTestCase):
    def setUp(self):
        self.jefe = self.crear_usuario('jefe_dev', 'administrador', is_superuser=True, email='jefe@lottus.test')
        self.admin = self.crear_usuario('admin_dev', 'administrador')
        self.c = self.api(self.jefe)
        self.avisar = mock.patch('ordenes.desarrollador_views.requests.post').start()
        self.addCleanup(mock.patch.stopall)

    def crear(self, pedido='Agrega la columna Ciudad en la tabla de Ventas'):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.c.post('/api/desarrollador/tareas/', {'pedido': pedido}, format='json')
        return r

    def interno(self, pk, metodo='patch', token=TOKEN, **datos):
        return getattr(self.client, metodo)(f'/api/desarrollador/interno/tareas/{pk}/', datos, content_type='application/json',
                                             HTTP_X_DESARROLLADOR_TOKEN=token)

    def test_solo_el_superusuario_lo_usa_y_ve_el_agente(self):
        self.assertEqual(self.api(self.admin).post('/api/desarrollador/tareas/', {'pedido': 'x' * 20}, format='json').status_code, 403)
        self.assertEqual(self.api(self.admin).get('/api/desarrollador/estado/').status_code, 403)
        perfil = PerfilAsistente.objects.get(clave_sistema='desarrollador')
        self.assertEqual(perfil.zona.ambiente, 'creativo')
        ids = lambda c: [p['id'] for p in c.get('/api/asistente/perfiles/').data]
        self.assertNotIn(perfil.pk, ids(self.api(self.admin)))
        self.assertIn(perfil.pk, ids(self.c))
        self.assertTrue(next(p for p in self.c.get('/api/asistente/perfiles/').data if p['id'] == perfil.pk)['desarrollador'])

    def test_flujo_pedido_plan_aprobacion_y_pruebas(self):
        r = self.crear()
        self.assertEqual((r.status_code, r.data['estado']), (201, 'planificando'))
        self.avisar.assert_called_once()  # se le avisa al servicio
        self.assertEqual(self.crear('corto').status_code, 400)
        pk = r.data['id']
        # No se aprueba algo que aún no tiene plan.
        self.assertEqual(self.c.post(f'/api/desarrollador/tareas/{pk}/aprobar/').status_code, 409)
        # El servicio entrega el plan (y se avisa por correo).
        with self.captureOnCommitCallbacks(execute=True):
            r = self.interno(pk, estado='plan_listo', plan={'riesgo': 'bajo', 'pasos': ['Editar Ventas.jsx']}, eventos=['Plan listo'], tokens_suma=1200)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('plan listo', mail.outbox[0].subject)
        # El servicio no puede aprobar por su cuenta.
        self.assertEqual(self.interno(pk, estado='aprobada').status_code, 409)
        # Ajuste → vuelve a planear; nuevo plan → aprobación del usuario.
        self.assertEqual(self.c.post(f'/api/desarrollador/tareas/{pk}/ajustar/', {'texto': 'Que también salga en el Excel'}, format='json').data['estado'], 'planificando')
        with self.captureOnCommitCallbacks(execute=True):
            self.interno(pk, estado='plan_listo', plan={'riesgo': 'medio'})
        r = self.c.post(f'/api/desarrollador/tareas/{pk}/aprobar/')
        self.assertEqual((r.status_code, r.data['estado']), (200, 'aprobada'))
        self.interno(pk, estado='implementando')
        with self.captureOnCommitCallbacks(execute=True):
            r = self.interno(pk, estado='en_pruebas', resultado={'resumen': 'Columna agregada', 'rama': 'desarrollador/t1'},
                             diff='+ ciudad', vista_previa='https://pruebas.example/')
        t = TareaDesarrollo.objects.get(pk=pk)
        self.assertEqual((t.estado, t.tokens, t.ajustes, t.vista_previa), ('en_pruebas', 1200, ['Que también salga en el Excel'], 'https://pruebas.example/'))
        self.assertEqual(len(mail.outbox), 3)
        # Descartar lo que está en pruebas pide restaurar la versión de pruebas.
        r = self.c.post(f'/api/desarrollador/tareas/{pk}/descartar/')
        self.assertTrue(r.data['resultado']['restaurar_pruebas'])
        pendientes = self.client.get('/api/desarrollador/interno/pendientes/', HTTP_X_DESARROLLADOR_TOKEN=TOKEN).json()
        self.assertEqual([p['id'] for p in pendientes], [pk])

    def test_canal_interno_exige_token(self):
        pk = self.crear().data['id']
        self.assertEqual(self.interno(pk, token='otro', estado='plan_listo').status_code, 403)
        self.assertEqual(self.client.get('/api/desarrollador/interno/pendientes/').status_code, 403)
        with override_settings(DESARROLLADOR_TOKEN=''):  # sin token configurado, el canal está apagado
            self.assertEqual(self.interno(pk, token='', estado='plan_listo').status_code, 403)
        self.assertEqual(self.client.post('/api/desarrollador/interno/latido/', HTTP_X_DESARROLLADOR_TOKEN=TOKEN).status_code, 200)
        self.assertTrue(self.c.get('/api/desarrollador/estado/').data['servicio_activo'])

    def test_otro_superusuario_no_ve_tareas_ajenas(self):
        pk = self.crear().data['id']
        otro = self.crear_usuario('otro_jefe', 'administrador', is_superuser=True)
        self.assertEqual(self.api(otro).get(f'/api/desarrollador/tareas/{pk}/').status_code, 404)

    def test_aplicada_se_deshace_solo_por_el_usuario(self):
        pk = self.crear().data['id']
        TareaDesarrollo.objects.filter(pk=pk).update(estado='implementando')
        with self.captureOnCommitCallbacks(execute=True):
            r = self.interno(pk, estado='aplicada', resultado={'resumen': 'Sidebar azul', 'aplicado': {'repositorios': ['frontend']}})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('aplicada', mail.outbox[-1].subject)
        self.assertEqual(self.c.post(f'/api/desarrollador/tareas/{pk}/descartar/').status_code, 409)  # se usa Deshacer
        self.assertEqual(self.interno(pk, estado='deshecha').status_code, 409)  # el servicio no deshace por su cuenta
        self.avisar.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.c.post(f'/api/desarrollador/tareas/{pk}/deshacer/')
        self.assertEqual(r.data['estado'], 'deshaciendo')
        self.avisar.assert_called_once()
        pendientes = self.client.get('/api/desarrollador/interno/pendientes/', HTTP_X_DESARROLLADOR_TOKEN=TOKEN).json()
        self.assertEqual([(p['id'], p['estado']) for p in pendientes], [(pk, 'deshaciendo')])
        self.assertEqual(self.interno(pk, estado='deshecha').data['estado'], 'deshecha')
        self.assertEqual(self.c.post(f'/api/desarrollador/tareas/{pk}/deshacer/').status_code, 409)

    def test_borra_solo_tareas_cerradas_y_propias(self):
        pk = self.crear().data['id']
        self.assertEqual(self.c.delete(f'/api/desarrollador/tareas/{pk}/').status_code, 409)  # planificando
        otro = self.crear_usuario('otro_jefe2', 'administrador', is_superuser=True)
        TareaDesarrollo.objects.filter(pk=pk).update(estado='aplicada')
        self.assertEqual(self.c.delete(f'/api/desarrollador/tareas/{pk}/').status_code, 409)  # se perdería Deshacer
        TareaDesarrollo.objects.filter(pk=pk).update(estado='deshecha')
        self.assertEqual(self.api(otro).delete(f'/api/desarrollador/tareas/{pk}/').status_code, 404)
        self.assertEqual(self.c.delete(f'/api/desarrollador/tareas/{pk}/').status_code, 204)
        self.assertFalse(TareaDesarrollo.objects.filter(pk=pk).exists())
