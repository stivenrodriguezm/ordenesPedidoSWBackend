from ordenes.models import CustomUser
from ordenes.tests.utils import LottusTestCase


class AccesoRapidoIATests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.uno = self.crear_usuario('uno', role='vendedor')
        self.dos = self.crear_usuario('dos', role='vendedor')

    def test_admin_activa_y_desactiva_por_cuenta_sin_alterar_el_rol(self):
        c = self.api(self.admin)
        url = f'/api/usuarios/{self.uno.pk}/'
        r = c.patch(url, {'acceso_rapido_ia': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.uno.refresh_from_db()
        self.assertTrue(self.api(self.uno).get('/api/user/').data['acceso_rapido_ia'])
        self.assertFalse(self.api(self.dos).get('/api/user/').data['acceso_rapido_ia'])
        self.assertEqual(self.api(self.uno).get('/api/asistente/estado/').status_code, 403)
        self.assertTrue(c.get(url).data['acceso_rapido_ia'])
        self.assertEqual(c.patch(url, {'acceso_rapido_ia': False}, format='json').status_code, 200)
        self.uno.refresh_from_db()
        self.assertFalse(self.uno.acceso_rapido_ia)
        self.assertEqual(self.uno.role, 'vendedor')

    def test_gestor_no_administrador_no_puede_configurar_el_boton(self):
        self.permisos('vendedor', ['VER_USUARIOS', 'ADMINISTRAR_USUARIOS'])
        c = self.api(self.uno)
        for cuenta in [self.uno, self.dos]:
            r = c.patch(f'/api/usuarios/{cuenta.pk}/', {'acceso_rapido_ia': True}, format='json')
            self.assertEqual(r.status_code, 403)
        r = c.post('/api/usuarios/', {'username': 'nuevo', 'role': 'vendedor', 'acceso_rapido_ia': True}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(CustomUser.objects.filter(username='nuevo').exists())
        # Continúa pudiendo gestionar campos ordinarios sin el interruptor IA.
        self.assertEqual(c.patch(f'/api/usuarios/{self.dos.pk}/', {'first_name': 'Dos'}, format='json').status_code, 200)

    def test_admin_puede_crear_con_preferencia_y_nuevas_cuentas_quedan_apagadas(self):
        self.assertFalse(self.admin.acceso_rapido_ia)
        c = self.api(self.admin)
        r = c.post('/api/usuarios/', {'username': 'con-boton', 'role': 'vendedor', 'acceso_rapido_ia': True}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['acceso_rapido_ia'])
