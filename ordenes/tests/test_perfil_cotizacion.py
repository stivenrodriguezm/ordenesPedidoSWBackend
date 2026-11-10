"""Teléfono y enlace del QR del asesor para el imprimible de cotizaciones (2026-11-04)."""
from ordenes.models import CustomUser
from ordenes.tests.utils import LottusTestCase


class PerfilCotizacionTests(LottusTestCase):
    def setUp(self):
        self.vendedor = self.crear_usuario('vendedor1')

    def test_cada_usuario_edita_su_telefono_y_enlace(self):
        r = self.api(self.vendedor).patch('/api/user/', {'telefono': '300 123 4567', 'enlace_qr': 'https://ejemplo.invalid/asesor'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['telefono'], '300 123 4567')
        self.assertEqual(r.data['enlace_qr'], 'https://ejemplo.invalid/asesor')
        self.assertEqual(self.api(self.vendedor).get('/api/user/').data['telefono'], '300 123 4567')

    def test_no_cambia_otros_datos_propios(self):
        r = self.api(self.vendedor).patch('/api/user/', {'role': 'administrador', 'telefono': '3001234567'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.vendedor.refresh_from_db()
        self.assertEqual(self.vendedor.role, 'vendedor')

    def test_valores_invalidos_se_rechazan(self):
        self.assertEqual(self.api(self.vendedor).patch('/api/user/', {'telefono': 'llámame'}, format='json').status_code, 400)
        self.assertEqual(self.api(self.vendedor).patch('/api/user/', {'enlace_qr': 'javascript:alert(1)'}, format='json').status_code, 400)

    def test_se_puede_vaciar(self):
        CustomUser.objects.filter(pk=self.vendedor.pk).update(telefono='3001234567', enlace_qr='https://ejemplo.invalid')
        r = self.api(self.vendedor).patch('/api/user/', {'telefono': '', 'enlace_qr': ''}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.vendedor.refresh_from_db()
        self.assertEqual((self.vendedor.telefono, self.vendedor.enlace_qr), ('', ''))

    def test_administrador_lo_edita_en_gestion_de_usuarios(self):
        admin = self.crear_usuario('admin', role='administrador')
        r = self.api(admin).patch(f'/api/usuarios/{self.vendedor.pk}/', {'telefono': '3109876543', 'enlace_qr': 'https://ejemplo.invalid/v1'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.vendedor.refresh_from_db()
        self.assertEqual(self.vendedor.telefono, '3109876543')
