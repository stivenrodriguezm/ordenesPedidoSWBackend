from unittest import mock

from django.core.cache import cache

from lottusPedidos.throttling import ApiUserRateThrottle
from ordenes.tests.utils import LottusTestCase


class LimitesApiTests(LottusTestCase):
    def setUp(self):
        cache.clear()  # Caché en memoria del perfil de pruebas.
        self.addCleanup(cache.clear)
        self.u = self.crear_usuario('admin', 'administrador')
        self.otro = self.crear_usuario('otro', 'administrador')
        self.c = self.api(self.u)
        self.clock = mock.patch.object(ApiUserRateThrottle, 'timer', return_value=1000000)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        rates = mock.patch.object(ApiUserRateThrottle, 'THROTTLE_RATES', {
            'user': '3/day', 'session': '2/min',
            'office_live': '4/min', 'office_presence': '2/min',
        })
        rates.start()
        self.addCleanup(rates.stop)

    def test_contador_anterior_agotado_no_bloquea_la_nueva_politica(self):
        anterior = [1000000] * 3
        cache.set(f'throttle_user_{self.u.pk}', anterior, 86400)
        for url in ('/api/user/', '/api/oficina/estado/', '/api/vendedores/'):
            self.assertEqual(self.c.get(url).status_code, 200, url)
        self.assertEqual(cache.get(f'throttle_user_{self.u.pk}'), anterior)
        self.assertEqual(len(cache.get(f'throttle_api_user_{self.u.pk}')), 1)

    def test_sesion_y_oficina_funcionan_con_cupo_operativo_agotado(self):
        cache.set(f'throttle_api_user_{self.u.pk}', [1000000] * 3, 86400)
        self.assertEqual(self.c.get('/api/vendedores/').status_code, 429)
        self.assertEqual(self.c.get('/api/user/').status_code, 200)
        self.assertEqual(self.c.get('/api/oficina/estado/').status_code, 200)

    def test_sondeos_tienen_limite_y_no_consumen_sesion_ni_operaciones(self):
        for url in ('/api/oficina/estado/', '/api/oficina/interacciones/',
                    '/api/asistente/conversaciones/', '/api/asistente/oficina-actividad/'):
            self.assertEqual(self.c.get(url).status_code, 200, url)
        limitado = self.c.get('/api/oficina/estado/')
        self.assertEqual(limitado.status_code, 429)
        self.assertEqual(limitado['Retry-After'], '60')
        self.assertIsNone(cache.get(f'throttle_api_user_{self.u.pk}'))
        self.assertEqual(self.c.get('/api/user/').status_code, 200)
        self.assertEqual(self.c.get('/api/vendedores/').status_code, 200)
        self.assertEqual(self.api(self.otro).get('/api/oficina/estado/').status_code, 200)
        with mock.patch.object(ApiUserRateThrottle, 'timer', return_value=1000061):
            self.assertEqual(self.c.get('/api/oficina/estado/').status_code, 200)

    def test_sesion_conserva_su_limite_y_se_recupera_en_un_minuto(self):
        for _ in range(2):
            self.assertEqual(self.c.get('/api/user/').status_code, 200)
        self.assertEqual(self.c.get('/api/user/').status_code, 429)
        self.assertEqual(self.c.get('/api/oficina/estado/').status_code, 200)
        self.assertEqual(self.api(self.otro).get('/api/user/').status_code, 200)
        with mock.patch.object(ApiUserRateThrottle, 'timer', return_value=1000061):
            self.assertEqual(self.c.get('/api/user/').status_code, 200)

    def test_escrituras_no_utilizan_el_cupo_de_sondeos(self):
        for _ in range(3):
            # Validación 400: no modifica datos, pero sí cuenta la solicitud.
            self.assertEqual(self.c.post('/api/asistente/preguntar/', {}, format='json').status_code, 400)
        self.assertEqual(self.c.post('/api/asistente/preguntar/', {}, format='json').status_code, 429)
        self.assertEqual(self.c.get('/api/asistente/conversaciones/').status_code, 200)
        self.assertEqual(self.c.get('/api/user/').status_code, 200)

    def test_la_sesion_sigue_exigiendo_autenticacion(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get('/api/user/').status_code, 401)

    def test_latidos_tienen_limite_propio_sin_agotar_operaciones(self):
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().post('/api/oficina/presencia/', {})
        request.user = self.u
        for _ in range(2):
            self.assertTrue(ApiUserRateThrottle().allow_request(request, None))
        self.assertFalse(ApiUserRateThrottle().allow_request(request, None))
        self.assertIsNone(cache.get(f'throttle_api_user_{self.u.pk}'))
        self.assertEqual(self.c.get('/api/vendedores/').status_code, 200)
