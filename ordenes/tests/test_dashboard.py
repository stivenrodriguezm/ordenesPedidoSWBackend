"""Estadísticas personales de ventas compartidas (H13, H31 · P05-01, P05-05).

Reemplaza el antiguo script test_dashboard.py de la raíz, que consultaba la base
al importarse y rompía el descubrimiento de pruebas."""
from datetime import date, timedelta
from decimal import Decimal

from ordenes.tests.utils import LottusTestCase


class DashboardVentasCompartidasTests(LottusTestCase):
    def setUp(self):
        self.dueno = self.crear_usuario('owner', role='vendedor')
        self.seller = self.crear_usuario('seller', role='vendedor')
        self.tercero = self.crear_usuario('third', role='vendedor')
        self.admin = self.crear_usuario('admin', role='administrador')

    def dashboard(self, user):
        r = self.api(user).get('/api/dashboard-stats/')
        self.assertEqual(r.status_code, 200)
        return r.data

    def test_shared_sales_three_people(self):
        venta = self.venta(self.dueno, valor='300')
        venta.vendedores_compartidos.add(self.seller, self.tercero)
        for u in (self.dueno, self.seller, self.tercero):
            self.assertEqual(Decimal(str(self.dashboard(u)['ventas_dia'])), Decimal('100'))
        # La empresa conserva el 100 %
        self.assertEqual(Decimal(str(self.dashboard(self.admin)['ventas_dia'])), Decimal('300'))

    def test_cancelled_sale_in_dashboard(self):
        venta = self.venta(self.dueno, valor='300')
        venta.vendedores_compartidos.add(self.seller, self.tercero)
        self.venta(self.seller, valor='600', estado='anulada')
        self.assertEqual(Decimal(str(self.dashboard(self.seller)['ventas_dia'])), Decimal('100'))
        self.assertEqual(Decimal(str(self.dashboard(self.admin)['ventas_dia'])), Decimal('300'))

    def test_principal_repetido_entre_compartidos_no_cuenta_dos_veces(self):
        venta = self.venta(self.dueno, valor='300')
        venta.vendedores_compartidos.add(self.dueno, self.seller)
        self.assertEqual(Decimal(str(self.dashboard(self.dueno)['ventas_dia'])), Decimal('150'))
        self.assertEqual(Decimal(str(self.dashboard(self.seller)['ventas_dia'])), Decimal('150'))

    def test_uno_y_dos_participantes(self):
        self.venta(self.dueno, valor='200')
        self.assertEqual(Decimal(str(self.dashboard(self.dueno)['ventas_dia'])), Decimal('200'))
        v = self.venta(self.seller, valor='100')
        v.vendedores_compartidos.add(self.tercero)
        self.assertEqual(Decimal(str(self.dashboard(self.tercero)['ventas_dia'])), Decimal('50'))

    def test_grafico_excluye_anuladas_y_reparte(self):
        venta = self.venta(self.dueno, valor='300')
        venta.vendedores_compartidos.add(self.seller, self.tercero)
        self.venta(self.seller, valor='600', estado='anulada')
        r = self.api(self.seller).get('/api/sales-chart-data/')
        self.assertEqual(r.status_code, 200)
        actual = r.data['datasets'][1]['data']
        self.assertEqual(sum(Decimal(str(x)) for x in actual), Decimal('100'))
        r = self.api(self.admin).get('/api/sales-chart-data/')
        self.assertEqual(sum(Decimal(str(x)) for x in r.data['datasets'][1]['data']), Decimal('300'))


class PeriodoComercialTests(LottusTestCase):
    """Período comercial del 6 al 5 (P05-05)."""

    def test_limites_del_periodo(self):
        from ordenes.business_time import periodo_comercial
        self.assertEqual(periodo_comercial(date(2026, 10, 6)), (date(2026, 10, 6), date(2026, 11, 5)))
        self.assertEqual(periodo_comercial(date(2026, 10, 5)), (date(2026, 9, 6), date(2026, 10, 5)))
        self.assertEqual(periodo_comercial(date(2026, 12, 20)), (date(2026, 12, 6), date(2027, 1, 5)))
        self.assertEqual(periodo_comercial(date(2027, 1, 3)), (date(2026, 12, 6), date(2027, 1, 5)))

    def test_periodo_por_mes(self):
        from ordenes.business_time import periodo_de_mes
        self.assertEqual(periodo_de_mes(12, 2026), (date(2026, 12, 6), date(2027, 1, 5)))
        self.assertEqual(periodo_de_mes(1, 2027), (date(2027, 1, 6), date(2027, 2, 5)))

    def test_dia_local_nocturno(self):
        """23:30 en Bogotá (04:30 UTC del día siguiente) pertenece al día local."""
        from datetime import datetime, timezone as dt_tz
        from ordenes.business_time import rango_dia_local, fecha_local
        instante = datetime(2026, 10, 3, 4, 30, tzinfo=dt_tz.utc)
        self.assertEqual(fecha_local(instante), date(2026, 10, 2))
        inicio, fin = rango_dia_local(date(2026, 10, 2))
        self.assertTrue(inicio <= instante < fin)
        self.assertEqual(fin - inicio, timedelta(days=1))
