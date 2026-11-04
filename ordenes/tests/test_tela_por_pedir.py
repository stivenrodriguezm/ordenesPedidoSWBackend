"""«Pendiente» es el nombre antiguo de «Por pedir» en la tela de una orden (2026-11-04): se guarda
siempre como «Por pedir», venga de donde venga, para que la orden aparezca al pedir su tela."""
from datetime import date

from ordenes.models import OrdenPedido
from ordenes.tests.utils import LottusTestCase


class TelaPendienteSeGuardaPorPedirTests(LottusTestCase):
    def test_cualquier_guardado_normaliza_pendiente(self):
        admin = self.crear_usuario('admin_pendiente', role='administrador')
        orden = OrdenPedido.objects.create(proveedor=self.proveedor(), usuario=admin, fecha_esperada=date.today(), tela='Pendiente')
        orden.refresh_from_db()
        self.assertEqual(orden.tela, 'Por pedir')
        orden.tela = 'Pendiente'
        orden.save(update_fields=['tela'])
        orden.refresh_from_db()
        self.assertEqual(orden.tela, 'Por pedir')
