"""Regresiones de caja (H02, H03, H31 · P03-02/P03-03 · anexo A)."""
from decimal import Decimal

from ordenes.models import Caja
from ordenes.tests.utils import LottusTestCase


class CajaMovimientosTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')

    def post(self, user, **data):
        return self.api(user).post('/api/caja/', data, format='json')

    def test_negative_cash_income(self):
        """Un ingreso negativo se rechaza sin crear movimiento ni cambiar el saldo."""
        r = self.post(self.admin, tipo='ingreso', valor='-100', concepto='prueba')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Caja.objects.count(), 0)
        self.assertEqual(self.saldo_caja(), Decimal('0'))

    def test_valor_cero_rechazado(self):
        r = self.post(self.admin, tipo='ingreso', valor='0', concepto='prueba')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Caja.objects.count(), 0)

    def test_egreso_negativo_no_aumenta_saldo(self):
        self.post(self.admin, tipo='ingreso', valor='100', concepto='base')
        r = self.post(self.admin, tipo='egreso', valor='-50', concepto='truco')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.saldo_caja(), Decimal('100'))

    def test_read_only_cash_permission_can_set_balance(self):
        """Un lector de caja no puede crear un cierre ni fijar el saldo."""
        lector = self.crear_usuario('lector', role='marketing')
        self.permisos('marketing', ['VER_CAJA'])
        r = self.post(lector, tipo='cierre', valor='900000', concepto='prueba')
        self.assertIn(r.status_code, (400, 403))
        self.assertEqual(Caja.objects.count(), 0)
        self.assertEqual(self.saldo_caja(), Decimal('0'))

    def test_cierre_rechazado_en_alta_generica_incluso_para_admin(self):
        self.post(self.admin, tipo='ingreso', valor='100', concepto='base')
        r = self.post(self.admin, tipo='cierre', valor='900000', concepto='prueba')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.saldo_caja(), Decimal('100'))

    def test_tipo_desconocido_rechazado(self):
        r = self.post(self.admin, tipo='ajuste', valor='10', concepto='x')
        self.assertEqual(r.status_code, 400)

    def test_egreso_con_caja_vacia_rechazado(self):
        r = self.post(self.admin, tipo='egreso', valor='1', concepto='x')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Caja.objects.count(), 0)

    def test_totales_filtrados_suman_solo_el_conjunto(self):
        self.post(self.admin, tipo='ingreso', valor='100', concepto='venta mostrador')
        self.post(self.admin, tipo='ingreso', valor='40', concepto='otro concepto')
        self.post(self.admin, tipo='egreso', valor='25', concepto='papelería')
        c = self.api(self.admin)
        r = c.get('/api/caja/')
        self.assertEqual(Decimal(str(r.data['totales_filtrados']['ingresos'])), Decimal('140'))
        self.assertEqual(Decimal(str(r.data['totales_filtrados']['egresos'])), Decimal('25'))
        r = c.get('/api/caja/', {'query': 'mostrador'})
        self.assertEqual(Decimal(str(r.data['totales_filtrados']['ingresos'])), Decimal('100'))
        self.assertEqual(Decimal(str(r.data['totales_filtrados']['egresos'])), Decimal('0'))

    def test_egreso_hasta_saldo_exacto(self):
        self.post(self.admin, tipo='ingreso', valor='100', concepto='base')
        self.assertEqual(self.post(self.admin, tipo='egreso', valor='100', concepto='x').status_code, 201)
        self.assertEqual(self.saldo_caja(), Decimal('0'))
        self.assertEqual(self.post(self.admin, tipo='egreso', valor='0.01', concepto='x').status_code, 400)
        self.assertEqual(self.saldo_caja(), Decimal('0'))

    def test_saldo_no_lo_fija_el_cliente(self):
        r = self.post(self.admin, tipo='ingreso', valor='100', concepto='x', total_acumulado='999999')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.saldo_caja(), Decimal('100'))


class CierreCajaTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')

    def test_cierre_requiere_permiso_propio(self):
        lector = self.crear_usuario('lector', role='marketing')
        self.permisos('marketing', ['VER_CAJA'])
        r = self.api(lector).post('/api/caja/cierre/', {'descuadre': 0}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Caja.objects.count(), 0)

    def test_cierre_conserva_saldo(self):
        self.api(self.admin).post('/api/caja/', {'tipo': 'ingreso', 'valor': '250', 'concepto': 'x'}, format='json')
        r = self.api(self.admin).post('/api/caja/cierre/', {'descuadre': '10', 'signo': 'faltante'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.saldo_caja(), Decimal('250'))
        cierre = Caja.objects.get(tipo='cierre')
        self.assertEqual(cierre.valor, Decimal('0'))
