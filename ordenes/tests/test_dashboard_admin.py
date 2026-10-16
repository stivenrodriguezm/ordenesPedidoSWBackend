"""Panel general del administrador (2026-10-09): /api/dashboard-admin/."""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from ordenes import business_time
from ordenes.models import OrdenPedido
from ordenes.tests.utils import LottusTestCase

HOY = date(2026, 10, 20)  # día 15 del período 6 oct – 5 nov


class DashboardAdminTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.ana = self.crear_usuario('ana', role='vendedor', first_name='Ana')
        self.beto = self.crear_usuario('beto', role='vendedor', first_name='Beto')
        parche = mock.patch.object(business_time, 'hoy', return_value=HOY)
        parche.start()
        self.addCleanup(parche.stop)

    def panel(self, user=None):
        r = self.api(user or self.admin).get('/api/dashboard-admin/')
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_ritmo_frente_al_mismo_dia_del_periodo_anterior(self):
        self.venta(self.ana, valor='300', fecha=HOY)
        self.venta(self.ana, valor='100', fecha=date(2026, 10, 6))
        self.venta(self.beto, valor='999', fecha=HOY, estado='anulada')
        self.venta(self.beto, valor='200', fecha=date(2026, 9, 10))   # dentro del corte anterior (día 5)
        self.venta(self.beto, valor='500', fecha=date(2026, 10, 1))   # después del corte, mismo período anterior
        d = self.panel()
        v = d['ventas']
        self.assertEqual((d['periodo']['dia'], d['periodo']['dias']), (15, 31))
        self.assertEqual((v['total'], v['cantidad'], v['hoy_total']), (400.0, 2, 300.0))
        self.assertEqual((v['anterior_corte'], v['anterior_total']), (200.0, 700.0))
        self.assertEqual(v['variacion_pct'], 100.0)
        self.assertEqual(len(v['serie_actual']), 15)
        self.assertEqual(v['serie_actual'][-1], 400.0)
        self.assertEqual(len(v['serie_anterior']), 30)

    def test_asesores_reparten_las_compartidas(self):
        venta = self.venta(self.ana, valor='300', fecha=HOY)
        venta.vendedores_compartidos.add(self.beto)
        self.venta(self.ana, valor='100', fecha=HOY)
        filas = {a['nombre']: (a['total'], a['ventas']) for a in self.panel()['asesores']}
        self.assertEqual(filas, {'Ana': (250.0, 2), 'Beto': (150.0, 1)})

    def test_atencion_cuenta_solo_lo_reciente_y_lo_vencido(self):
        self.venta(self.ana, fecha=HOY - timedelta(days=10))                    # gestión atrasada
        self.venta(self.ana, fecha=HOY - timedelta(days=1))                     # aún en plazo
        self.venta(self.ana, fecha=HOY - timedelta(days=200))                   # antigua: fuera de la ventana
        self.venta(self.ana, fecha=HOY - timedelta(days=10), estado_pedidos=True)
        OrdenPedido.objects.create(proveedor=self.proveedor(), usuario=self.ana, fecha_esperada=HOY - timedelta(days=1), estado='en_proceso')
        OrdenPedido.objects.create(proveedor=self.proveedor(), usuario=self.ana, fecha_esperada=HOY - timedelta(days=1), estado='recibido')
        items = {i['clave']: i for i in self.panel()['atencion']}
        self.assertEqual(items['gestion_atrasada']['cantidad'], 1)
        self.assertEqual(items['op_atrasadas']['cantidad'], 1)
        self.assertEqual(items['op_atrasadas']['ruta'], '/ordenes')
        self.assertIn('nomina_abierta', items)

    def test_permisos(self):
        self.assertEqual(self.api(self.ana).get('/api/dashboard-admin/').status_code, 403)
        self.permisos('auxiliar', ['VER_DASHBOARD_GENERAL', 'VER_ORDENES'])
        aux = self.crear_usuario('aux', role='auxiliar')
        d = self.panel(aux)
        self.assertEqual([i['clave'] for i in d['atencion']], ['op_atrasadas'])
        self.assertEqual(d['dinero'], {'ventana_dias': 90})
        self.assertIsNone(d['ia'])
        self.assertEqual(d['ultimas_ventas'], [])
