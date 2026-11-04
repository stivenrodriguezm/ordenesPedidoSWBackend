"""Ventas que reciben recibos de caja (2026-11-04): la gestión finalizada es solo la gestión de
pedidos; la venta sigue pendiente y sigue recibiendo pagos. Para crear pedidos no se ofrece."""
from datetime import date

from ordenes.tests.utils import LottusTestCase


class PendientesParaRecibosTests(LottusTestCase):
    def setUp(self):
        self.asesor = self.crear_usuario('asesor')
        self.permisos('vendedor', ['VER_PROPIAS_VENTAS'])
        self.api_asesor = self.api(self.asesor)
        self.abierta = self.venta(self.asesor, valor='414', fecha=date(2026, 10, 1), abono=200)
        self.finalizada = self.venta(self.asesor, valor='500', fecha=date(2026, 10, 2), abono=100)
        self.finalizada.estado_pedidos = True
        self.finalizada.save(update_fields=['estado_pedidos'])

    def test_recibos_incluyen_la_venta_con_gestion_finalizada(self):
        r = self.api_asesor.get('/api/get-pendientes-ids/', {'para': 'recibos'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {self.abierta.pk, self.finalizada.pk})

    def test_pedidos_siguen_sin_la_venta_con_gestion_finalizada(self):
        r = self.api_asesor.get('/api/get-pendientes-ids/')
        self.assertEqual(set(r.data), {self.abierta.pk})
